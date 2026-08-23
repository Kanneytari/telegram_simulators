from __future__ import annotations

import random
from datetime import timedelta

from app.db import Database
from app.simulation import iso, utcnow
from app.staff_relationships import StaffRelationshipGameService, StaffRelationshipSimulationEngine


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = StaffRelationshipSimulationEngine(db, speed=1.0, rng=random.Random(301))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = StaffRelationshipGameService(db, simulation, rng=random.Random(302))
    return db, simulation, game


def create_dispute(db: Database, *, cause: str = "EMPLOYEE_ERROR") -> tuple[int, int]:
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        client = conn.execute(
            "SELECT * FROM clients WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        batch = conn.execute(
            "SELECT * FROM batches WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        order = conn.execute(
            """INSERT INTO orders(
                   player_id, client_id, employee_id, batch_id, product_id, quantity,
                   revenue, cost, employee_cost, quality, status
               ) VALUES (1001, ?, ?, ?, ?, 1, 10000, 3000, 1500, 82, 'disputed')""",
            (client["id"], employee["id"], batch["id"], batch["product_id"]),
        )
        dispute = conn.execute(
            """INSERT INTO disputes(
                   player_id, order_id, true_cause, message, evidence_json,
                   status, deadline_at
               ) VALUES (1001, ?, ?, 'test', '{}', 'open', ?)""",
            (order.lastrowid, cause, iso(utcnow() + timedelta(hours=2))),
        )
        return int(dispute.lastrowid), int(employee["id"])


def test_assigning_uncovered_wholesale_batch_increases_loyalty_and_stress(tmp_path):
    db, _, game = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' ORDER BY id LIMIT 1"
        ).fetchone()
        batch = conn.execute(
            "SELECT id FROM batches WHERE player_id=1001 AND status='warehouse' ORDER BY id LIMIT 1"
        ).fetchone()
        employee_id = int(employee["id"])
        batch_id = int(batch["id"])
        conn.execute(
            "UPDATE employees SET deposit=10000, loyalty=0.50, stress=10 WHERE id=?",
            (employee_id,),
        )
        conn.execute("UPDATE batches SET responsible_employee_id=NULL WHERE id=?", (batch_id,))

    result = game.assign_unassigned_batch(1001, batch_id, employee_id)
    assert "закреплена" in result

    with db.connect() as conn:
        employee = conn.execute(
            "SELECT loyalty, stress FROM employees WHERE id=?", (employee_id,)
        ).fetchone()
        event = conn.execute(
            """SELECT * FROM staff_relationship_events
               WHERE player_id=1001 AND employee_id=? AND kind='overexposure_trust'
               ORDER BY id DESC LIMIT 1""",
            (employee_id,),
        ).fetchone()

    assert float(employee["loyalty"]) > 0.50
    assert float(employee["stress"]) > 10.0
    assert event is not None
    assert event["reference_type"] == "batch"
    assert int(event["reference_id"]) == batch_id


def test_retail_employee_reacts_when_handoff_pushes_exposure_over_deposit(tmp_path):
    db, simulation, game = make_system(tmp_path)
    with db.connect() as conn:
        retail = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        batch = conn.execute(
            """SELECT id FROM batches
               WHERE player_id=1001 AND responsible_employee_id IS NOT NULL
                 AND status='warehouse' AND remaining>=10
               ORDER BY id LIMIT 1"""
        ).fetchone()
        retail_id = int(retail["id"])
        batch_id = int(batch["id"])
        conn.execute(
            "UPDATE employees SET deposit=1000, loyalty=0.50, stress=10 WHERE id=?",
            (retail_id,),
        )

    game.allocate_to_retail(1001, batch_id, retail_id, 10)
    now = utcnow()
    with db.connect() as conn:
        allocation = conn.execute(
            """SELECT id FROM retail_allocations
               WHERE player_id=1001 AND retail_employee_id=?
               ORDER BY id DESC LIMIT 1""",
            (retail_id,),
        ).fetchone()
        allocation_id = int(allocation["id"])
        conn.execute(
            "UPDATE employee_tasks SET completes_at=? WHERE allocation_id=? AND kind='handoff'",
            (iso(now - timedelta(seconds=2)), allocation_id),
        )

    with db.connect() as conn:
        simulation._process_tasks(conn, 1001, now)

    with db.connect() as conn:
        employee = conn.execute(
            "SELECT loyalty, stress FROM employees WHERE id=?", (retail_id,)
        ).fetchone()
        event = conn.execute(
            """SELECT * FROM staff_relationship_events
               WHERE player_id=1001 AND employee_id=? AND kind='overexposure_trust'
                 AND reference_type='allocation' AND reference_id=?""",
            (retail_id, allocation_id),
        ).fetchone()

    assert float(employee["loyalty"]) > 0.50
    assert float(employee["stress"]) > 10.0
    assert event is not None


def test_shop_paid_refund_is_positive_for_employee_relationship(tmp_path):
    db, _, game = make_system(tmp_path)
    dispute_id, employee_id = create_dispute(db, cause="EMPLOYEE_ERROR")
    with db.connect() as conn:
        conn.execute("UPDATE shops SET balance=500000 WHERE player_id=1001")
        conn.execute(
            "UPDATE employees SET loyalty=0.50, stress=50 WHERE id=?",
            (employee_id,),
        )

    game.resolve_dispute_with_source(1001, dispute_id, "partial", "shop")

    with db.connect() as conn:
        employee = conn.execute(
            "SELECT loyalty, stress FROM employees WHERE id=?", (employee_id,)
        ).fetchone()
        dispute = conn.execute(
            "SELECT status, refund_source FROM disputes WHERE id=?", (dispute_id,)
        ).fetchone()
        event = conn.execute(
            """SELECT * FROM staff_relationship_events
               WHERE player_id=1001 AND employee_id=? AND kind='shop_absorbed_refund'
               AND reference_id=?""",
            (employee_id, dispute_id),
        ).fetchone()

    assert dispute["status"] == "resolved"
    assert dispute["refund_source"] == "shop"
    assert float(employee["loyalty"]) > 0.50
    assert float(employee["stress"]) < 50.0
    assert event is not None


def test_employee_paid_refund_reduces_loyalty(tmp_path):
    db, _, game = make_system(tmp_path)
    dispute_id, employee_id = create_dispute(db, cause="EMPLOYEE_ERROR")
    with db.connect() as conn:
        conn.execute("UPDATE shops SET balance=500000 WHERE player_id=1001")
        conn.execute(
            "UPDATE employees SET deposit=100000, loyalty=0.50, stress=20 WHERE id=?",
            (employee_id,),
        )

    game.resolve_dispute_with_source(1001, dispute_id, "partial", "employee")

    with db.connect() as conn:
        employee = conn.execute(
            "SELECT loyalty, stress FROM employees WHERE id=?", (employee_id,)
        ).fetchone()
        dispute = conn.execute(
            "SELECT status, refund_source FROM disputes WHERE id=?", (dispute_id,)
        ).fetchone()
        event = conn.execute(
            """SELECT * FROM staff_relationship_events
               WHERE player_id=1001 AND employee_id=? AND kind='employee_deposit_refund'
               AND reference_id=?""",
            (employee_id, dispute_id),
        ).fetchone()

    assert dispute["status"] == "resolved"
    assert dispute["refund_source"] == "employee"
    assert float(employee["loyalty"]) < 0.50
    assert float(employee["stress"]) > 20.0
    assert event is not None
