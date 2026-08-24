from __future__ import annotations

import random

from app.compensation import CompensationGameService, CompensationSimulationEngine
from app.db import Database
from app.recruitment_runtime import NightshiftRecruitmentService


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CompensationSimulationEngine(db, rng=random.Random(12))
    simulation.ensure_player(1001, "tester")
    game = CompensationGameService(db, simulation, rng=random.Random(13))
    recruitment = NightshiftRecruitmentService(db, rng=random.Random(14))
    return db, simulation, game, recruitment


def test_starter_batches_are_assigned_to_wholesale_employee(tmp_path):
    db, _, _, _ = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='warehouse' AND active=1"
        ).fetchone()
        batches = conn.execute(
            "SELECT * FROM batches WHERE player_id=1001 AND remaining>0"
        ).fetchall()
    assert employee is not None
    assert batches
    assert all(row["responsible_employee_id"] == employee["id"] for row in batches)


def test_offer_can_exceed_deposit_and_reports_unsecured_exposure(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='warehouse' LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE employees SET deposit=100000 WHERE id=?", (employee["id"],))
        cur = conn.execute(
            """INSERT INTO supplier_offers(
                   player_id, supplier_id, product_id, quantity, unit_cost,
                   quality_hint, expires_at
               ) VALUES (1001, 1, 1, 100, 4000, 'обычное', datetime('now','+1 day'))"""
        )
        offer_id = cur.lastrowid
    staff = game.warehouse_staff_for_offer(1001, offer_id)
    selected = next(row for row in staff if row["id"] == employee["id"])
    assert selected["required"] == 400000
    assert selected["eligible"] is True
    assert selected["unsecured_after"] > 0


def test_procurement_assigns_batch_but_does_not_pay_wholesale_employee(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='warehouse' LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE employees SET deposit=2000000, wages_accrued=0 WHERE id=?", (employee["id"],))
        conn.execute("UPDATE shops SET balance=3000000 WHERE player_id=1001")
        conn.execute("UPDATE suppliers SET reliability=1.0 WHERE id=1")
        cur = conn.execute(
            """INSERT INTO supplier_offers(
                   player_id, supplier_id, product_id, quantity, unit_cost,
                   quality_hint, offer_quality_mean, offer_quality_sigma,
                   offer_reliability, market_profile, expires_at
               ) VALUES (1001, 1, 1, 50, 3000, 'стабильное', 82, 2, 1.0, 'normal', datetime('now','+1 day'))"""
        )
        offer_id = cur.lastrowid

    result = game.buy_offer_for_employee(1001, offer_id, int(employee["id"]))

    with db.connect() as conn:
        batch = conn.execute(
            "SELECT * FROM batches WHERE player_id=1001 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        updated = conn.execute("SELECT * FROM employees WHERE id=?", (employee["id"],)).fetchone()
        task = conn.execute(
            "SELECT * FROM employee_tasks WHERE batch_id=? AND kind='receive_batch'",
            (batch["id"],),
        ).fetchone()
    assert "Ответственный" in result
    assert "Оплата будет начислена после успешной передачи" in result
    assert batch["responsible_employee_id"] == employee["id"]
    assert batch["status"] == "receiving"
    assert task is not None
    assert int(updated["wages_accrued"]) == 0


def test_wholesale_employee_cannot_be_fired_with_inventory(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' LIMIT 1"
        ).fetchone()
    result = game.fire_employee(1001, int(employee["id"]))
    assert result["status"] == "inventory"


def test_review_links_product_pack_and_retail_employee(tmp_path):
    db, simulation, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        client = conn.execute("SELECT * FROM clients WHERE player_id=1001 LIMIT 1").fetchone()
        courier = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' LIMIT 1"
        ).fetchone()
        batch = conn.execute("SELECT * FROM batches WHERE player_id=1001 LIMIT 1").fetchone()
        cur = conn.execute(
            """INSERT INTO orders(
                   player_id, client_id, employee_id, batch_id, product_id,
                   quantity, revenue, cost, employee_cost, quality
               ) VALUES (1001, ?, ?, ?, ?, 2, 12000, 6000, 680, 91)""",
            (client["id"], courier["id"], batch["id"], batch["product_id"]),
        )
        order_id = cur.lastrowid

    review_id = simulation.create_review_for_order(1001, order_id, force=True)
    assert review_id is not None
    product_reviews = game.product_reviews(1001, int(batch["product_id"]))
    employee_reviews = game.employee_reviews(1001, int(courier["id"]))
    assert any(row["order_id"] == order_id and row["quantity"] == 2 for row in product_reviews)
    assert any(row["order_id"] == order_id for row in employee_reviews)


def test_recruitment_can_target_wholesale_role_with_global_terms(tmp_path):
    db, _, _, recruitment = make_system(tmp_path)
    recruitment.update_draft(1001, "role", "warehouse")
    draft = recruitment.ensure_draft(1001)
    quote = recruitment.quote(1001, draft)
    assert draft["role"] == "warehouse"
    assert draft["min_deposit"] == 300000
    assert quote["policy"]["base_rate_bps"] == 200
    assert quote["policy"]["risk_rate_bps"] == 100
    assert quote["policy"]["deposit_contribution_pct"] == 25

    recruitment.update_draft(1001, "traffic_multiplier", 4)
    recruitment.update_draft(1001, "duration_hours", 24)
    recruitment.start_campaign(1001)
    recruitment.fast_forward(1001, 30)
    with db.connect() as conn:
        candidates = conn.execute(
            "SELECT * FROM candidates WHERE player_id=1001 AND campaign_id IS NOT NULL"
        ).fetchall()
    assert all(row["role"] == "warehouse" for row in candidates)
