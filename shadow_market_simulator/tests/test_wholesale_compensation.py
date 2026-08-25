from __future__ import annotations

import random
from datetime import timedelta

from app.staff.compensation import CompensationGameService, CompensationSimulationEngine
from app.core.database import Database
from app.engine.simulation import iso, utcnow


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CompensationSimulationEngine(db, speed=1.0, rng=random.Random(91))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = CompensationGameService(db, simulation, rng=random.Random(92))
    return db, simulation, game


def create_certain_offer(db) -> int:
    with db.connect() as conn:
        conn.execute("UPDATE shops SET balance=5000000 WHERE player_id=1001")
        offer = conn.execute(
            """INSERT INTO supplier_offers(
                   player_id, supplier_id, product_id, quantity, unit_cost,
                   quality_hint, offer_quality_mean, offer_quality_sigma,
                   offer_reliability, market_profile, expires_at
               ) VALUES (
                   1001, 1, 1, 100, 2500,
                   'test', 82, 2, 1.0, 'normal', ?
               )""",
            (iso(utcnow() + timedelta(days=1)),),
        )
        return int(offer.lastrowid)


def finish_task(simulation, db, task_id: int) -> None:
    now = utcnow()
    with db.connect() as conn:
        conn.execute(
            "UPDATE employee_tasks SET completes_at=? WHERE id=?",
            (iso(now - timedelta(minutes=1)), task_id),
        )
        simulation._process_tasks(conn, 1001, now)


def test_wholesale_is_paid_percentage_on_successful_handoff_not_procurement(tmp_path):
    db, simulation, game = make_system(tmp_path)
    offer_id = create_certain_offer(db)

    with db.connect() as conn:
        wholesale = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='warehouse' AND active=1 ORDER BY id LIMIT 1"
        ).fetchone()
        retail = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' AND active=1 ORDER BY id LIMIT 1"
        ).fetchone()
        wholesale_id = int(wholesale["id"])
        before_jobs = int(wholesale["jobs_done"])
        before_wages = int(wholesale["wages_accrued"])
        conn.execute("UPDATE employees SET deposit=0 WHERE id=?", (wholesale_id,))

    result = game.buy_offer_for_employee(1001, offer_id, wholesale_id)
    assert "Оплата складмену будет начислена после успешной передачи товара" in result

    with db.connect() as conn:
        after_purchase = conn.execute(
            "SELECT jobs_done, wages_accrued FROM employees WHERE id=?",
            (wholesale_id,),
        ).fetchone()
        receive_task = conn.execute(
            """SELECT * FROM employee_tasks
               WHERE player_id=1001 AND employee_id=? AND kind='receive_batch' AND status='active'
               ORDER BY id DESC LIMIT 1""",
            (wholesale_id,),
        ).fetchone()
    assert int(after_purchase["jobs_done"]) == before_jobs
    assert int(after_purchase["wages_accrued"]) == before_wages
    assert receive_task is not None

    finish_task(simulation, db, int(receive_task["id"]))
    with db.connect() as conn:
        batch = conn.execute(
            """SELECT * FROM batches
               WHERE player_id=1001 AND responsible_employee_id=? AND status='warehouse'
               ORDER BY id DESC LIMIT 1""",
            (wholesale_id,),
        ).fetchone()
    assert batch is not None

    game.allocate_to_retail(1001, int(batch["id"]), int(retail["id"]), 20)
    with db.connect() as conn:
        handoff = conn.execute(
            """SELECT * FROM employee_tasks
               WHERE player_id=1001 AND employee_id=? AND kind='handoff' AND status='active'
               ORDER BY id DESC LIMIT 1""",
            (wholesale_id,),
        ).fetchone()
    assert handoff is not None

    goods_value = 20 * int(batch["unit_cost"])
    expected_base = round(goods_value * 0.02)
    expected_risk = round(goods_value * 0.01)
    expected_total = expected_base + expected_risk

    finish_task(simulation, db, int(handoff["id"]))
    with db.connect() as conn:
        after_handoff = conn.execute(
            "SELECT jobs_done, wages_accrued, deposit_accrued FROM employees WHERE id=?",
            (wholesale_id,),
        ).fetchone()
        payment = conn.execute(
            "SELECT * FROM wholesale_delivery_payments WHERE allocation_id=?",
            (handoff["allocation_id"],),
        ).fetchone()

    assert payment is not None
    assert int(payment["goods_value"]) == goods_value
    assert int(payment["uncovered_value"]) == goods_value
    assert int(payment["base_amount"]) == expected_base
    assert int(payment["risk_amount"]) == expected_risk
    assert int(payment["amount"]) == expected_total
    assert int(after_handoff["jobs_done"]) == before_jobs + 1
    assert int(after_handoff["wages_accrued"]) == before_wages + expected_total
    assert int(after_handoff["deposit_accrued"]) == round(expected_total * 0.25)

    with db.connect() as conn:
        simulation._process_tasks(conn, 1001, utcnow() + timedelta(hours=1))
        count = int(conn.execute(
            "SELECT COUNT(*) FROM wholesale_delivery_payments WHERE allocation_id=?",
            (handoff["allocation_id"],),
        ).fetchone()[0])
    assert count == 1
