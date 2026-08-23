import random
from datetime import timedelta

from app.db import Database
from app.procurement_market import (
    PROCUREMENT_BATCH_SIZES,
    ProcurementMarketGameService,
    ProcurementMarketSimulationEngine,
)
from app.simulation import iso, utcnow


def make_game(tmp_path, seed=7):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = ProcurementMarketSimulationEngine(db, speed=1.0, rng=random.Random(seed))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = ProcurementMarketGameService(db, simulation, rng=random.Random(seed + 1))
    return db, simulation, game


def market_counts(db):
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT product_id, quantity, COUNT(*) count
               FROM supplier_offers
               WHERE player_id=1001 AND status='open'
               GROUP BY product_id, quantity"""
        ).fetchall()
    return {(int(row["product_id"]), int(row["quantity"])): int(row["count"]) for row in rows}


def test_market_has_one_to_five_offers_per_product_and_size(tmp_path):
    db, simulation, game = make_game(tmp_path)
    counts = market_counts(db)

    assert len(counts) == 3 * len(PROCUREMENT_BATCH_SIZES)
    assert all(1 <= value <= 5 for value in counts.values())

    products = game.procurement_products(1001)
    assert len(products) == 3
    for product in products:
        assert set(product["counts"]) == set(PROCUREMENT_BATCH_SIZES)
        assert all(1 <= count <= 5 for count in product["counts"].values())


def test_one_rotation_replaces_only_one_or_two_offers(tmp_path):
    db, simulation, _ = make_game(tmp_path, seed=11)

    counts = market_counts(db)
    if not any(value > 1 for value in counts.values()):
        with db.connect() as conn:
            simulation._create_market_offer_conn(conn, 1001, 1, 50, utcnow())

    with db.connect() as conn:
        before = {int(row[0]) for row in conn.execute(
            "SELECT id FROM supplier_offers WHERE player_id=1001 AND status='open'"
        ).fetchall()}
        conn.execute(
            "UPDATE procurement_market_state SET last_rotation_at=? WHERE player_id=1001",
            (iso(utcnow() - timedelta(minutes=16)),),
        )

    simulation.refresh_procurement_market(1001)

    with db.connect() as conn:
        after = {int(row[0]) for row in conn.execute(
            "SELECT id FROM supplier_offers WHERE player_id=1001 AND status='open'"
        ).fetchall()}

    removed = before - after
    added = after - before
    assert 1 <= len(removed) <= 2
    assert 1 <= len(added) <= 2
    assert all(1 <= value <= 5 for value in market_counts(db).values())


def test_market_rotation_uses_real_time_not_game_speed(tmp_path):
    db, simulation, _ = make_game(tmp_path, seed=19)
    with db.connect() as conn:
        before = {int(row[0]) for row in conn.execute(
            "SELECT id FROM supplier_offers WHERE player_id=1001 AND status='open'"
        ).fetchall()}
        conn.execute("UPDATE settings SET time_multiplier=60 WHERE player_id=1001")
        conn.execute(
            "UPDATE procurement_market_state SET last_rotation_at=? WHERE player_id=1001",
            (iso(utcnow() - timedelta(minutes=5)),),
        )

    changed = simulation.refresh_procurement_market(1001)
    with db.connect() as conn:
        after = {int(row[0]) for row in conn.execute(
            "SELECT id FROM supplier_offers WHERE player_id=1001 AND status='open'"
        ).fetchall()}

    assert changed == 0
    assert before == after


def test_offer_specific_quality_is_used_on_purchase(tmp_path):
    db, simulation, game = make_game(tmp_path, seed=23)
    offer = game.offers(1001, 1)[0]
    with db.connect() as conn:
        conn.execute(
            """UPDATE supplier_offers
               SET offer_quality_mean=98, offer_quality_sigma=2, offer_reliability=1.0
               WHERE id=?""",
            (offer["id"],),
        )
        employee = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' AND active=1 LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE shops SET balance=100000000 WHERE player_id=1001")

    result = game.buy_offer_for_employee(1001, int(offer["id"]), int(employee["id"]))
    assert "Партия куплена" in result

    with db.connect() as conn:
        batch = conn.execute(
            "SELECT quality FROM batches WHERE player_id=1001 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert float(batch["quality"]) >= 90.0
