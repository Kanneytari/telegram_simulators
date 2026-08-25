from __future__ import annotations

import random

from app.trust.customer import (
    CustomerTrustGameService,
    CustomerTrustSimulationEngine,
    premium_allowance,
)
from app.core.database import Database


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CustomerTrustSimulationEngine(db, rng=random.Random(301))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = CustomerTrustGameService(db, simulation, rng=random.Random(302))
    return db, simulation, game


def test_product_and_courier_ratings_are_separate(tmp_path):
    db, simulation, _ = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        client = conn.execute("SELECT * FROM clients WHERE player_id=1001 ORDER BY id LIMIT 1").fetchone()
        batch = conn.execute("SELECT * FROM batches WHERE player_id=1001 ORDER BY id LIMIT 1").fetchone()
        conn.execute(
            "UPDATE employees SET attention=0.97, reliability=0.97, loyalty=0.90, stress=5 WHERE id=?",
            (courier["id"],),
        )
        order = conn.execute(
            """INSERT INTO orders(
                   player_id, client_id, employee_id, batch_id, product_id, quantity,
                   revenue, cost, employee_cost, quality
               ) VALUES (1001, ?, ?, ?, ?, 1, 6000, 3000, 440, 58)""",
            (client["id"], courier["id"], batch["id"], batch["product_id"]),
        )
        employee = conn.execute("SELECT * FROM employees WHERE id=?", (courier["id"],)).fetchone()
        simulation._record_rating_conn(conn, int(order.lastrowid), employee)
        rating = conn.execute(
            "SELECT product_rating, courier_rating FROM order_ratings WHERE order_id=?",
            (order.lastrowid,),
        ).fetchone()
    assert rating["product_rating"] == 2
    assert rating["courier_rating"] >= 4


def test_high_quality_does_not_hide_bad_courier(tmp_path):
    db, simulation, _ = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        client = conn.execute("SELECT * FROM clients WHERE player_id=1001 ORDER BY id LIMIT 1").fetchone()
        batch = conn.execute("SELECT * FROM batches WHERE player_id=1001 ORDER BY id LIMIT 1").fetchone()
        conn.execute(
            "UPDATE employees SET attention=0.35, reliability=0.40, loyalty=0.40, stress=90 WHERE id=?",
            (courier["id"],),
        )
        order = conn.execute(
            """INSERT INTO orders(
                   player_id, client_id, employee_id, batch_id, product_id, quantity,
                   revenue, cost, employee_cost, quality
               ) VALUES (1001, ?, ?, ?, ?, 1, 6000, 3000, 440, 96)""",
            (client["id"], courier["id"], batch["id"], batch["product_id"]),
        )
        employee = conn.execute("SELECT * FROM employees WHERE id=?", (courier["id"],)).fetchone()
        simulation._record_rating_conn(conn, int(order.lastrowid), employee)
        rating = conn.execute(
            "SELECT product_rating, courier_rating FROM order_ratings WHERE order_id=?",
            (order.lastrowid,),
        ).fetchone()
    assert rating["product_rating"] == 5
    assert rating["courier_rating"] <= 2


def test_repeat_and_regular_customer_progression(tmp_path):
    db, simulation, game = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        conn.execute(
            "UPDATE employees SET attention=0.99, reliability=0.99, loyalty=0.95, stress=0 WHERE id=?",
            (courier["id"],),
        )
        client = conn.execute("SELECT * FROM clients WHERE player_id=1001 ORDER BY id LIMIT 1").fetchone()
        batch = conn.execute("SELECT * FROM batches WHERE player_id=1001 ORDER BY id LIMIT 1").fetchone()
        for i in range(4):
            order = conn.execute(
                """INSERT INTO orders(
                       player_id, client_id, employee_id, batch_id, product_id, quantity,
                       revenue, cost, employee_cost, quality,
                       customer_purchase_number, customer_was_repeat
                   ) VALUES (1001, ?, ?, ?, ?, 1, 6000, 3000, 440, 96, ?, ?)""",
                (client["id"], courier["id"], batch["id"], batch["product_id"], i + 1, int(i > 0)),
            )
            employee = conn.execute("SELECT * FROM employees WHERE id=?", (courier["id"],)).fetchone()
            simulation._record_rating_conn(conn, int(order.lastrowid), employee)
    metrics = game.customer_metrics(1001)
    assert metrics["repeat_clients"] >= 1
    assert metrics["regulars"] >= 1


def test_trust_unlocks_price_premium_but_is_capped():
    assert premium_allowance(50, 0.0) == 0.0
    assert premium_allowance(85, 0.25) > premium_allowance(65, 0.0)
    assert premium_allowance(100, 1.0) <= 0.30


def test_customer_metrics_expose_core_progression(tmp_path):
    _, _, game = make_system(tmp_path)
    metrics = game.customer_metrics(1001)
    assert 20 <= metrics["trust_score"] <= 98
    assert 0 <= metrics["availability"] <= 1
    assert 0 <= metrics["fairness"] <= 1
    assert 0 <= metrics["premium_allowance"] <= 0.30
