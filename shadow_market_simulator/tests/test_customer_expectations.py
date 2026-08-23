import random

from app.customer_expectations import PriceExpectationSimulationEngine
from app.db import Database


def test_price_adjustment_rewards_discount_and_penalizes_markup_more_strongly():
    assert PriceExpectationSimulationEngine.price_quality_adjustment(0.80) > 0
    assert PriceExpectationSimulationEngine.price_quality_adjustment(1.20) < 0
    assert abs(PriceExpectationSimulationEngine.price_quality_adjustment(1.20)) > abs(
        PriceExpectationSimulationEngine.price_quality_adjustment(0.80)
    )


def test_good_quality_can_support_markup_better_than_average_quality():
    average_at_markup = PriceExpectationSimulationEngine.perceived_quality(80, 1.20)
    excellent_at_markup = PriceExpectationSimulationEngine.perceived_quality(94, 1.20)
    assert average_at_markup < 80
    assert excellent_at_markup >= 80


def test_same_batch_quality_gets_better_review_when_sold_below_market(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = PriceExpectationSimulationEngine(db, speed=1.0, rng=random.Random(7))
    simulation.ensure_player(1001, "tester")

    with db.connect() as conn:
        client = conn.execute(
            "SELECT id FROM clients WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        employee = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        batch = conn.execute(
            "SELECT id FROM batches WHERE player_id=1001 AND product_id=1 ORDER BY id LIMIT 1"
        ).fetchone()
        product = conn.execute("SELECT base_market_price FROM products WHERE id=1").fetchone()
        market = int(product["base_market_price"])

        cheap = conn.execute(
            """INSERT INTO orders(
                   player_id, client_id, employee_id, batch_id, product_id, quantity,
                   revenue, cost, employee_cost, quality
               ) VALUES (1001, ?, ?, ?, 1, 1, ?, 3000, 1500, 80)""",
            (client["id"], employee["id"], batch["id"], int(market * 0.80)),
        ).lastrowid
        expensive = conn.execute(
            """INSERT INTO orders(
                   player_id, client_id, employee_id, batch_id, product_id, quantity,
                   revenue, cost, employee_cost, quality
               ) VALUES (1001, ?, ?, ?, 1, 1, ?, 3000, 1500, 80)""",
            (client["id"], employee["id"], batch["id"], int(market * 1.20)),
        ).lastrowid

    simulation.create_review_for_order(1001, cheap, force=True)
    simulation.create_review_for_order(1001, expensive, force=True)

    with db.connect() as conn:
        cheap_rating = conn.execute(
            "SELECT rating FROM reviews WHERE order_id=?", (cheap,)
        ).fetchone()[0]
        expensive_rating = conn.execute(
            "SELECT rating FROM reviews WHERE order_id=?", (expensive,)
        ).fetchone()[0]

    assert cheap_rating > expensive_rating
    assert cheap_rating == 4
    assert expensive_rating == 3
