from __future__ import annotations

import random
from datetime import timedelta

from app.staff.compensation import CompensationGameService, CompensationSimulationEngine
from app.core.database import Database
from app.engine.simulation import iso, utcnow


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CompensationSimulationEngine(db, speed=1.0, rng=random.Random(201))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = CompensationGameService(db, simulation, rng=random.Random(202))
    return db, simulation, game


def test_default_terms_are_global_by_role(tmp_path):
    db, _, game = make_system(tmp_path)
    retail = game.compensation_policy(1001, "courier")
    wholesale = game.compensation_policy(1001, "warehouse")

    assert retail == {
        "fixed_fee": 200,
        "base_rate_bps": 400,
        "risk_rate_bps": 0,
        "deposit_contribution_pct": 20,
    }
    assert wholesale == {
        "fixed_fee": 0,
        "base_rate_bps": 200,
        "risk_rate_bps": 100,
        "deposit_contribution_pct": 25,
    }



def test_changing_role_terms_affects_all_active_employees_of_that_role(tmp_path):
    db, _, game = make_system(tmp_path)
    with db.connect() as conn:
        couriers = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='courier' AND active=1 ORDER BY id"
        ).fetchall()
        assert len(couriers) >= 2
        conn.execute(
            "UPDATE employees SET loyalty=0.50, stress=20 WHERE player_id=1001 AND role='courier' AND active=1"
        )

    result = game.adjust_compensation_policy(1001, "courier", "fixed_fee", 50)
    assert result["changed"] is True
    assert result["policy"]["fixed_fee"] == 250

    with db.connect() as conn:
        updated = conn.execute(
            "SELECT loyalty, stress FROM employees WHERE player_id=1001 AND role='courier' AND active=1"
        ).fetchall()
    assert all(float(row["loyalty"]) > 0.50 for row in updated)
    assert all(float(row["stress"]) < 20.0 for row in updated)


def test_already_earned_deposit_split_is_frozen_when_policy_changes(tmp_path):
    db, simulation, game = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        employee_id = int(employee["id"])
        old_deposit = int(employee["deposit"])
        conn.execute(
            "UPDATE employees SET wages_accrued=10000, deposit_accrued=2000 WHERE id=?",
            (employee_id,),
        )
        conn.execute("UPDATE shops SET balance=50000 WHERE player_id=1001")

    game.adjust_compensation_policy(1001, "courier", "deposit_contribution_pct", 5)
    assert game.compensation_policy(1001, "courier")["deposit_contribution_pct"] == 25

    with db.connect() as conn:
        conn.execute(
            "UPDATE settings SET last_payroll_at=? WHERE player_id=1001",
            (iso(utcnow() - timedelta(hours=25 / simulation.effective_speed(1001))),),
        )

    result = game.process_payroll(1001)
    assert result["status"] == "paid"
    assert result["gross"] == 10000
    assert result["cash"] == 8000
    assert result["deposit"] == 2000

    with db.connect() as conn:
        updated = conn.execute(
            "SELECT wages_accrued, deposit_accrued, deposit FROM employees WHERE id=?",
            (employee_id,),
        ).fetchone()
    assert int(updated["wages_accrued"]) == 0
    assert int(updated["deposit_accrued"]) == 0
    assert int(updated["deposit"]) == old_deposit + 2000
