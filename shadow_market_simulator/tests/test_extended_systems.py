from __future__ import annotations

import json
import random
from datetime import timedelta

from app.db import Database
from app.nightshift import NightshiftSimulationEngine
from app.recruitment_runtime import NightshiftRecruitmentService
from app.runtime import NightshiftGameService
from app.simulation import iso, utcnow


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = NightshiftSimulationEngine(db, speed=1.0, rng=random.Random(7))
    simulation.ensure_player(1001, "tester")
    game = NightshiftGameService(db, simulation, rng=random.Random(8))
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
    with db.connect() as conn:
        conn.execute(
            "UPDATE shops SET last_simulated_at=? WHERE player_id=1001",
            (iso(utcnow() - timedelta(hours=3)),),
        )
        before_balance = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
    result = simulation.advance(1001)
    assert result.orders_created > 0
    with db.connect() as conn:
        accrued = conn.execute(
            "SELECT COALESCE(SUM(wages_accrued),0) FROM employees WHERE player_id=1001"
        ).fetchone()[0]
        revenue = conn.execute(
            "SELECT COALESCE(SUM(revenue),0) FROM orders WHERE player_id=1001"
        ).fetchone()[0]
        after_balance = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
    assert accrued > 0
    assert after_balance == before_balance + revenue


def test_daily_payroll_pays_cash_and_grows_deposit(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        old_deposit = employee["deposit"]
        conn.execute("UPDATE employees SET wages_accrued=10000 WHERE id=?", (employee["id"],))
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
        employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee["id"],)).fetchone()
        balance = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) FROM payroll_runs WHERE player_id=1001").fetchone()[0]
    assert employee["wages_accrued"] == 0
    assert employee["deposit"] == old_deposit + 1000
    assert balance == 41000
    assert runs == 1


def test_speed_multiplier_is_per_player(tmp_path):
    db, simulation, _, recruitment = make_system(tmp_path)
    simulation.ensure_player(2002, "other")
    recruitment.set_player_multiplier(1001, 60)
    assert simulation.player_multiplier(1001) == 60
    assert simulation.player_multiplier(2002) == 1
    assert simulation.effective_speed(1001) == 60
    assert simulation.effective_speed(2002) == 1


def test_raise_request_can_be_negotiated_and_accepted(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        payload = {
            "employee_id": employee["id"],
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

    # The player can always finish the negotiation by accepting the current employee request.
    item = game.inbox_item(1001, item_id)
    if item and item["status"] == "open":
        game.accept_raise_request(1001, item_id)
    with db.connect() as conn:
        item = conn.execute("SELECT status FROM inbox WHERE id=?", (item_id,)).fetchone()
        new_pay = conn.execute("SELECT pay_per_job FROM employees WHERE id=?", (employee["id"],)).fetchone()[0]
    assert item["status"] == "closed"
    assert new_pay >= 1650
