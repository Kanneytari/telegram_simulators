from __future__ import annotations

import json
import random
from datetime import timedelta

from app.compensation import CompensationGameService, CompensationSimulationEngine
from app.db import Database
from app.recruitment_runtime import NightshiftRecruitmentService
from app.simulation import iso, parse_dt, utcnow


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CompensationSimulationEngine(db, speed=1.0, rng=random.Random(7))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = CompensationGameService(db, simulation, rng=random.Random(8))
    recruitment = RecruitmentService(db, speed=1.0, rng=random.Random(9))
    return db, simulation, game, recruitment


def test_game_day_payroll_uses_frozen_cash_and_deposit_split(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        employee_id = int(employee["id"])
        old_deposit = int(employee["deposit"])
        conn.execute(
            "UPDATE employees SET wages_accrued=10000, deposit_accrued=2000 WHERE id=?",
            (employee_id,),
        )
        conn.execute("UPDATE shops SET balance=50000 WHERE player_id=1001")
        conn.execute(
            "UPDATE settings SET last_payroll_at=? WHERE player_id=1001",
            (iso(utcnow() - timedelta(hours=25)),),
        )

    result = game.process_payroll(1001)

    assert result["status"] == "paid"
    assert result["gross"] == 10000
    assert result["cash"] == 8000
    assert result["deposit"] == 2000
    with db.connect() as conn:
        employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
        balance = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) FROM payroll_runs WHERE player_id=1001").fetchone()[0]
    assert int(employee["wages_accrued"]) == 0
    assert int(employee["deposit_accrued"]) == 0
    assert int(employee["deposit"]) == old_deposit + 2000
    assert int(balance) == 42000
    assert int(runs) == 1


def test_payroll_at_x60_is_due_after_about_24_real_minutes(tmp_path):
    db, simulation, game, recruitment = make_system(tmp_path)
    recruitment.set_player_multiplier(1001, 60)
    assert simulation.effective_speed(1001) == 60

    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        conn.execute(
            "UPDATE employees SET wages_accrued=10000, deposit_accrued=2000 WHERE id=?",
            (employee["id"],),
        )
        conn.execute("UPDATE shops SET balance=50000 WHERE player_id=1001")
        conn.execute(
            "UPDATE settings SET last_payroll_at=? WHERE player_id=1001",
            (iso(utcnow() - timedelta(minutes=25)),),
        )

    result = game.process_payroll(1001)
    assert result is not None
    assert result["status"] == "paid"
    assert result["gross"] == 10000


def test_payroll_at_x60_is_not_due_before_game_day_ends(tmp_path):
    db, simulation, game, recruitment = make_system(tmp_path)
    recruitment.set_player_multiplier(1001, 60)
    assert simulation.effective_speed(1001) == 60

    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        conn.execute(
            "UPDATE employees SET wages_accrued=10000, deposit_accrued=2000 WHERE id=?",
            (employee["id"],),
        )
        conn.execute(
            "UPDATE settings SET last_payroll_at=? WHERE player_id=1001",
            (iso(utcnow() - timedelta(minutes=20)),),
        )

    assert game.process_payroll(1001) is None


def test_speed_multiplier_is_per_player(tmp_path):
    _, simulation, _, recruitment = make_system(tmp_path)
    simulation.ensure_player(2002, "other")
    recruitment.set_player_multiplier(1001, 60)
    assert simulation.player_multiplier(1001) == 60
    assert simulation.player_multiplier(2002) == 1
    assert simulation.effective_speed(1001) == 60
    assert simulation.effective_speed(2002) == 1


def test_speed_change_rescales_existing_game_deadline(tmp_path):
    db, simulation, _, recruitment = make_system(tmp_path)
    now = utcnow()
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO inbox(player_id, kind, priority, title, body, expires_at)
               VALUES (1001, 'tutorial', 'normal', 'timer', 'timer', ?)""",
            (iso(now + timedelta(hours=2)),),
        )
        item_id = int(cur.lastrowid)

    old, new = recruitment.set_player_multiplier(1001, 60)
    simulation.rescale_existing_timers(1001, old, new, now=now)
    with db.connect() as conn:
        expires = conn.execute("SELECT expires_at FROM inbox WHERE id=?", (item_id,)).fetchone()[0]
    remaining_minutes = (parse_dt(expires) - now).total_seconds() / 60
    assert 1.9 <= remaining_minutes <= 2.1


def test_leave_request_uses_game_time_not_real_time(tmp_path):
    db, _, game, recruitment = make_system(tmp_path)
    recruitment.set_player_multiplier(1001, 60)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        cur = conn.execute(
            """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json)
               VALUES (1001, 'leave_request', 'normal', 'Пауза', 'test', ?)""",
            (json.dumps({"employee_id": employee["id"]}),),
        )
        item_id = int(cur.lastrowid)
    before = utcnow()
    game.handle_inbox_action(1001, item_id, "approve")
    with db.connect() as conn:
        until = conn.execute(
            "SELECT unavailable_until FROM employees WHERE id=?",
            (employee["id"],),
        ).fetchone()[0]
    real_minutes = (parse_dt(until) - before).total_seconds() / 60
    assert 5.8 <= real_minutes <= 6.2


def test_simulation_does_not_create_individual_raise_requests(tmp_path):
    db, simulation, _, _ = make_system(tmp_path)

    now = utcnow()
    for _ in range(20):
        with db.connect() as conn:
            simulation._simulate_management_events(conn, 1001, 12.0, now)

    with db.connect() as conn:
        count = int(conn.execute(
            "SELECT COUNT(*) FROM inbox WHERE player_id=1001 AND kind='raise_request'"
        ).fetchone()[0])
    assert count == 0
