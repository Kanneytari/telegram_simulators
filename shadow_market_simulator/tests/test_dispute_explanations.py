from __future__ import annotations

import json
import random
from datetime import timedelta

from app.db import Database
from app.procurement_market import ProcurementMarketGameService, ProcurementMarketSimulationEngine
from app.simulation import iso, utcnow


def make_game(tmp_path, speed: float = 1.0):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = ProcurementMarketSimulationEngine(db, speed=speed, rng=random.Random(51))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = ProcurementMarketGameService(db, simulation, rng=random.Random(52))
    return db, simulation, game


def create_dispute(db):
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' AND active=1 ORDER BY id LIMIT 1"
        ).fetchone()
        client = conn.execute("SELECT * FROM clients WHERE player_id=1001 ORDER BY id LIMIT 1").fetchone()
        batch = conn.execute("SELECT * FROM batches WHERE player_id=1001 ORDER BY id LIMIT 1").fetchone()
        order = conn.execute(
            """INSERT INTO orders(
                   player_id, client_id, employee_id, batch_id, product_id, quantity,
                   revenue, cost, employee_cost, quality, status
               ) VALUES (1001, ?, ?, ?, ?, 1, 8000, 3000, 1500, 80, 'disputed')""",
            (client["id"], employee["id"], batch["id"], batch["product_id"]),
        )
        dispute = conn.execute(
            """INSERT INTO disputes(
                   player_id, order_id, true_cause, message, evidence_json, deadline_at
               ) VALUES (1001, ?, 'EMPLOYEE_ERROR', 'test', ?, ?)""",
            (order.lastrowid, json.dumps({}), iso(utcnow() + timedelta(hours=3))),
        )
        return int(dispute.lastrowid)


def test_employee_explanation_is_immediate(tmp_path):
    db, _, game = make_game(tmp_path)
    dispute_id = create_dispute(db)
    reply = game.ask_employee_about_dispute(1001, dispute_id)
    with db.connect() as conn:
        stored = conn.execute("SELECT courier_reply FROM disputes WHERE id=?", (dispute_id,)).fetchone()[0]
    assert reply
    assert stored == reply


def test_repeated_request_returns_same_explanation(tmp_path):
    db, _, game = make_game(tmp_path)
    dispute_id = create_dispute(db)
    first = game.ask_employee_about_dispute(1001, dispute_id)
    second = game.ask_employee_about_dispute(1001, dispute_id)
    assert second == first


def test_dispute_details_include_immediate_explanation(tmp_path):
    _, _, game = make_game(tmp_path)
    dispute_id = create_dispute(game.db)
    game.ask_employee_about_dispute(1001, dispute_id)
    details = game.dispute_details(1001, dispute_id)
    assert details is not None
    assert "Ответ сотрудника" in details
