from __future__ import annotations

import json
import random
from datetime import timedelta

from app.db import Database
from app.delayed_disputes import DelayedDisputeGameService, DelayedDisputeSimulationEngine
from app.simulation import iso, parse_dt, utcnow


def make_game(tmp_path, speed: float = 1.0):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = DelayedDisputeSimulationEngine(db, speed=speed, rng=random.Random(51))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = DelayedDisputeGameService(db, simulation, rng=random.Random(52))
    return db, simulation, game


def create_dispute(db):
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' AND active=1 ORDER BY id LIMIT 1"
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


def test_employee_explanation_is_delayed_between_5_and_120_game_minutes(tmp_path):
    db, simulation, game = make_game(tmp_path)
    dispute_id = create_dispute(db)
    before = utcnow()

    status = game.ask_employee_about_dispute(1001, dispute_id)

    with db.connect() as conn:
        row = conn.execute(
            "SELECT courier_reply, courier_reply_pending, courier_reply_due_at FROM disputes WHERE id=?",
            (dispute_id,),
        ).fetchone()
    assert "Запрос отправлен" in status
    assert row["courier_reply"] is None
    assert row["courier_reply_pending"]
    assert row["courier_reply_due_at"]
    game_minutes = (parse_dt(row["courier_reply_due_at"]) - before).total_seconds() / 60.0 * simulation.effective_speed(1001)
    assert 4.9 <= game_minutes <= 120.1


def test_repeated_request_does_not_create_new_timer(tmp_path):
    db, _, game = make_game(tmp_path)
    dispute_id = create_dispute(db)
    game.ask_employee_about_dispute(1001, dispute_id)
    with db.connect() as conn:
        first_due = conn.execute(
            "SELECT courier_reply_due_at FROM disputes WHERE id=?",
            (dispute_id,),
        ).fetchone()[0]

    status = game.ask_employee_about_dispute(1001, dispute_id)

    with db.connect() as conn:
        second_due = conn.execute(
            "SELECT courier_reply_due_at FROM disputes WHERE id=?",
            (dispute_id,),
        ).fetchone()[0]
    assert "уже запрошено" in status
    assert second_due == first_due


def test_tick_fast_forward_materializes_pending_reply(tmp_path):
    db, simulation, game = make_game(tmp_path)
    dispute_id = create_dispute(db)
    game.ask_employee_about_dispute(1001, dispute_id)

    simulation.fast_forward_timers(1001, 2.0)

    with db.connect() as conn:
        row = conn.execute(
            "SELECT courier_reply, courier_reply_pending, courier_reply_due_at FROM disputes WHERE id=?",
            (dispute_id,),
        ).fetchone()
    assert row["courier_reply"]
    assert row["courier_reply_pending"] is None
    assert row["courier_reply_due_at"] is None
    assert "Пояснение запрошено" not in game.dispute_details(1001, dispute_id)


def test_speed_rescale_preserves_remaining_game_time(tmp_path):
    db, simulation, game = make_game(tmp_path)
    dispute_id = create_dispute(db)
    game.ask_employee_about_dispute(1001, dispute_id)
    now = utcnow()
    with db.connect() as conn:
        due_before = parse_dt(conn.execute(
            "SELECT courier_reply_due_at FROM disputes WHERE id=?",
            (dispute_id,),
        ).fetchone()[0])
    remaining_game_before = max(0.0, (due_before - now).total_seconds()) * 1.0

    with db.connect() as conn:
        conn.execute("UPDATE settings SET time_multiplier=60 WHERE player_id=1001")
    simulation.rescale_existing_timers(1001, 1.0, 60.0, now=now)

    with db.connect() as conn:
        due_after = parse_dt(conn.execute(
            "SELECT courier_reply_due_at FROM disputes WHERE id=?",
            (dispute_id,),
        ).fetchone()[0])
    remaining_game_after = max(0.0, (due_after - now).total_seconds()) * 60.0
    assert abs(remaining_game_after - remaining_game_before) < 1.0
