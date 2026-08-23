from __future__ import annotations

import json
import random
from datetime import timedelta

from app.db import Database
from app.nightshift import NightshiftSimulationEngine
from app.recruitment_runtime import NightshiftRecruitmentService
from app.services import FinalGameService
from app.simulation import iso, parse_dt, utcnow


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = NightshiftSimulationEngine(db, speed=1.0, rng=random.Random(7))
    simulation.ensure_player(1001, "tester")
    game = FinalGameService(db, simulation, rng=random.Random(8))
    recruitment = NightshiftRecruitmentService(db, speed=1.0, rng=random.Random(9))
    return db, simulation, game, recruitment


def test_starter_retail_wage_and_deposit_contribution(tmp_path):
    db, _, _, _ = make_system(tmp_path)
    with db.connect() as conn:
        employees = conn.execute(
            "SELECT pay_per_job, deposit_contribution_pct FROM employees WHERE player_id=1001 AND role='courier'"
        ).fetchall()
    assert employees
    assert all(row["pay_per_job"] == 1500 for row in employees)
    assert all(row["deposit_contribution_pct"] == 10 for row in employees)


def test_order_accrues_wage_instead_of_paying_immediately(tmp_path):
    db, simulation, _, _ = make_system(tmp_path)
    now = utcnow()
    with db.connect() as conn:
        listing = conn.execute(
            "SELECT l.*, p.complaint_modifier FROM listings l JOIN products p ON p.id=l.product_id WHERE l.player_id=1001 ORDER BY l.id LIMIT 1"
        ).fetchone()
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        before_balance = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
        simulation._create_order(conn, 1001, listing, employee, now)
        order = conn.execute("SELECT * FROM orders WHERE player_id=1001 ORDER BY id DESC LIMIT 1").fetchone()
        accrued = conn.execute(
            "SELECT wages_accrued FROM employees WHERE id=?",
            (employee["id"],),
        ).fetchone()[0]
        after_balance = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]

    assert accrued == employee["pay_per_job"]
    assert order["employee_cost"] == employee["pay_per_job"]
    assert after_balance == before_balance + order["revenue"]


def test_daily_payroll_pays_cash_and_grows_deposit(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        employee_id = employee["id"]
        old_deposit = employee["deposit"]
        conn.execute("UPDATE employees SET wages_accrued=10000 WHERE id=?", (employee_id,))
        conn.execute("UPDATE shops SET balance=50000 WHERE player_id=1001")
        conn.execute(
            "UPDATE settings SET last_payroll_at=? WHERE player_id=1001",
            (iso(utcnow() - timedelta(hours=25)),),
        )

    result = game.process_payroll(1001)

    assert result["status"] == "paid"
    assert result["gross"] == 10000
    assert result["cash"] == 9000
    assert result["deposit"] == 1000
    with db.connect() as conn:
        employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
        balance = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) FROM payroll_runs WHERE player_id=1001").fetchone()[0]
    assert employee["wages_accrued"] == 0
    assert employee["deposit"] == old_deposit + 1000
    assert balance == 41000
    assert runs == 1


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
        item_id = cur.lastrowid

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
        item_id = cur.lastrowid
    before = utcnow()
    game.handle_inbox_action(1001, item_id, "approve")
    with db.connect() as conn:
        until = conn.execute("SELECT unavailable_until FROM employees WHERE id=?", (employee["id"],)).fetchone()[0]
    real_minutes = (parse_dt(until) - before).total_seconds() / 60
    assert 5.8 <= real_minutes <= 6.2


def test_raise_request_can_be_negotiated_and_accepted(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        employee_id = employee["id"]
        payload = {
            "employee_id": employee_id,
            "requested_pay": 1800,
            "offer_pay": 1500,
            "floor_pay": 1650,
            "round": 0,
        }
        cur = conn.execute(
            """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json)
               VALUES (1001, 'raise_request', 'normal', 'Разговор об оплате', 'test', ?)""",
            (json.dumps(payload),),
        )
        item_id = cur.lastrowid

    state = game.adjust_raise_offer(1001, item_id, 200)
    assert state["payload"]["offer_pay"] == 1700
    result = game.submit_raise_offer(1001, item_id)
    assert result

    item = game.inbox_item(1001, item_id)
    if item and item["status"] == "open":
        game.accept_raise_request(1001, item_id)
    with db.connect() as conn:
        item = conn.execute("SELECT status FROM inbox WHERE id=?", (item_id,)).fetchone()
        new_pay = conn.execute("SELECT pay_per_job FROM employees WHERE id=?", (employee_id,)).fetchone()[0]
    assert item["status"] == "closed"
    assert new_pay >= 1650
