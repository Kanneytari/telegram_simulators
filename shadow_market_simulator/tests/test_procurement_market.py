import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from app.core.database import Database
from app.commerce.procurement import (
    MINIMUM_BATCH_SIZE,
    PROCUREMENT_BATCH_SIZES,
    ProcurementMarketGameService,
    ProcurementMarketSimulationEngine,
)
from app.engine.simulation import iso, utcnow


CURRENT_PRODUCT_COUNT = 7
OFFERS_PER_PRODUCT = 5


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
    return {
        (int(row["product_id"]), int(row["quantity"])): int(row["count"])
        for row in rows
    }


def test_market_keeps_five_offers_per_product_with_minimum_lot(tmp_path):
    db, _, game = make_game(tmp_path)
    counts = market_counts(db)

    product_ids = {product_id for product_id, _ in counts}
    assert len(product_ids) == CURRENT_PRODUCT_COUNT
    assert all(quantity in PROCUREMENT_BATCH_SIZES for _, quantity in counts)
    assert all(value >= 1 for value in counts.values())
    for product_id in product_ids:
        assert sum(
            value
            for (candidate_id, _), value in counts.items()
            if candidate_id == product_id
        ) == OFFERS_PER_PRODUCT
        assert counts.get((product_id, MINIMUM_BATCH_SIZE), 0) >= 1

    products = game.procurement_products(1001)
    assert len(products) == CURRENT_PRODUCT_COUNT
    for product in products:
        assert set(product["counts"]) == set(PROCUREMENT_BATCH_SIZES)
        offers = game.offers(1001, int(product["id"]))
        assert product["total"] == len(offers)
        with db.connect() as conn:
            free_cash = game._free_cash_conn(conn, 1001)
        assert all(
            int(offer["quantity"] * offer["unit_cost"]) <= free_cash
            for offer in offers
        )


def test_one_rotation_replaces_only_one_or_two_offers(tmp_path):
    db, simulation, _ = make_game(tmp_path, seed=11)

    counts = market_counts(db)
    if not any(value > 1 for value in counts.values()):
        with db.connect() as conn:
            simulation._create_market_offer_conn(conn, 1001, 1, 50, utcnow())

    with db.connect() as conn:
        before = {
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM supplier_offers WHERE player_id=1001 AND status='open'"
            ).fetchall()
        }
        conn.execute(
            "UPDATE procurement_market_state SET last_rotation_at=? WHERE player_id=1001",
            (iso(utcnow() - timedelta(minutes=16)),),
        )

    simulation.refresh_procurement_market(1001)

    with db.connect() as conn:
        after = {
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM supplier_offers WHERE player_id=1001 AND status='open'"
            ).fetchall()
        }

    removed = before - after
    added = after - before
    assert 1 <= len(removed) <= 2
    assert 1 <= len(added) <= 2
    assert all(value >= 1 for value in market_counts(db).values())


def test_market_rotation_uses_real_time_not_game_speed(tmp_path):
    db, simulation, _ = make_game(tmp_path, seed=19)
    with db.connect() as conn:
        before = {
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM supplier_offers WHERE player_id=1001 AND status='open'"
            ).fetchall()
        }
        conn.execute("UPDATE settings SET time_multiplier=60 WHERE player_id=1001")
        conn.execute(
            "UPDATE procurement_market_state SET last_rotation_at=? WHERE player_id=1001",
            (iso(utcnow() - timedelta(minutes=5)),),
        )

    changed = simulation.refresh_procurement_market(1001)
    with db.connect() as conn:
        after = {
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM supplier_offers WHERE player_id=1001 AND status='open'"
            ).fetchall()
        }

    assert changed == 0
    assert before == after


def test_minimum_50_unit_offer_is_restored_for_every_product(tmp_path):
    db, simulation, _ = make_game(tmp_path, seed=17)
    with db.connect() as conn:
        conn.execute(
            """UPDATE supplier_offers SET status='rotated'
               WHERE player_id=1001 AND status='open' AND quantity=?""",
            (MINIMUM_BATCH_SIZE,),
        )
        product_ids = [
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM products WHERE active=1 ORDER BY id"
            ).fetchall()
        ]

    simulation.ensure_procurement_bounds(1001)

    with db.connect() as conn:
        for product_id in product_ids:
            count = int(
                conn.execute(
                    """SELECT COUNT(*) FROM supplier_offers
                       WHERE player_id=1001 AND product_id=? AND quantity=? AND status='open'""",
                    (product_id, MINIMUM_BATCH_SIZE),
                ).fetchone()[0]
            )
            assert count >= 1
            total = int(
                conn.execute(
                    """SELECT COUNT(*) FROM supplier_offers
                       WHERE player_id=1001 AND product_id=? AND status='open'""",
                    (product_id,),
                ).fetchone()[0]
            )
            assert total == OFFERS_PER_PRODUCT


def test_unaffordable_offers_are_hidden_and_purchase_uses_free_cash(tmp_path):
    db, _, game = make_game(tmp_path, seed=21)
    with db.connect() as conn:
        conn.execute(
            "UPDATE employees SET deposit=0, wages_accrued=0 WHERE player_id=1001 AND active=1"
        )
        conn.execute(
            "UPDATE shops SET balance=100000, reserve_target=20000 WHERE player_id=1001"
        )
        conn.execute(
            "UPDATE supplier_offers SET unit_cost=100000 WHERE player_id=1001 AND status='open'"
        )
        cheap = conn.execute(
            """SELECT id FROM supplier_offers
               WHERE player_id=1001 AND product_id=1 AND quantity=50 AND status='open'
               ORDER BY id LIMIT 1"""
        ).fetchone()
        expensive = conn.execute(
            """SELECT id FROM supplier_offers
               WHERE player_id=1001 AND product_id=1 AND quantity=100 AND status='open'
               ORDER BY id LIMIT 1"""
        ).fetchone()
        employee = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' AND active=1 LIMIT 1"
        ).fetchone()
        assert cheap and expensive and employee
        conn.execute(
            "UPDATE supplier_offers SET unit_cost=1000 WHERE id=?", (cheap["id"],)
        )
        conn.execute(
            "UPDATE supplier_offers SET unit_cost=1000 WHERE id=?", (expensive["id"],)
        )

    offers = game.offers(1001, 1)
    ids = {int(row["id"]) for row in offers}
    assert int(cheap["id"]) in ids
    assert int(expensive["id"]) not in ids
    assert all(int(row["quantity"] * row["unit_cost"]) <= 80000 for row in offers)

    products = game.procurement_products(1001)
    assert len(products) == CURRENT_PRODUCT_COUNT
    by_id = {int(row["id"]): row for row in products}
    assert int(by_id[1]["total"]) == 1
    assert all(
        int(row["total"]) == 0
        for product_id, row in by_id.items()
        if product_id != 1
    )

    with db.connect() as conn:
        balance_before = int(
            conn.execute(
                "SELECT balance FROM shops WHERE player_id=1001"
            ).fetchone()[0]
        )
    result = game.buy_offer_for_employee(
        1001, int(expensive["id"]), int(employee["id"])
    )
    assert "Недостаточно свободных денег" in result
    with db.connect() as conn:
        balance_after = int(
            conn.execute(
                "SELECT balance FROM shops WHERE player_id=1001"
            ).fetchone()[0]
        )
    assert balance_after == balance_before


def test_offer_specific_quality_is_used_on_purchase(tmp_path):
    db, _, game = make_game(tmp_path, seed=23)
    with db.connect() as conn:
        conn.execute(
            "UPDATE shops SET balance=100000000, reserve_target=0 WHERE player_id=1001"
        )
        conn.execute(
            "UPDATE employees SET deposit=0, wages_accrued=0 WHERE player_id=1001 AND active=1"
        )

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

    result = game.buy_offer_for_employee(
        1001, int(offer["id"]), int(employee["id"])
    )
    assert "✅ Куплено" in result

    with db.connect() as conn:
        batch = conn.execute(
            "SELECT quality FROM batches WHERE player_id=1001 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert float(batch["quality"]) >= 90.0


def test_same_offer_cannot_create_two_batches_under_concurrent_callbacks(tmp_path):
    db, _, game = make_game(tmp_path, seed=29)
    with db.connect() as conn:
        conn.execute(
            "UPDATE shops SET balance=100000000, reserve_target=0 WHERE player_id=1001"
        )
        conn.execute(
            "UPDATE employees SET deposit=0, wages_accrued=0 WHERE player_id=1001 AND active=1"
        )
        employee = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' AND active=1 LIMIT 1"
        ).fetchone()
        assert employee

    offer = game.offers(1001, 1)[0]
    offer_id = int(offer["id"])
    employee_id = int(employee["id"])
    total = int(offer["quantity"] * offer["unit_cost"])
    with db.connect() as conn:
        conn.execute(
            "UPDATE supplier_offers SET offer_reliability=1.0 WHERE id=?",
            (offer_id,),
        )
        balance_before = int(
            conn.execute(
                "SELECT balance FROM shops WHERE player_id=1001"
            ).fetchone()[0]
        )
        batches_before = int(
            conn.execute(
                "SELECT COUNT(*) FROM batches WHERE player_id=1001"
            ).fetchone()[0]
        )

    original_free_cash = game._free_cash_conn
    barrier = threading.Barrier(2)
    counter_lock = threading.Lock()
    call_count = 0

    def synchronized_free_cash(conn, player_id):
        nonlocal call_count
        value = original_free_cash(conn, player_id)
        with counter_lock:
            call_count += 1
            should_wait = call_count <= 2
        if should_wait:
            barrier.wait(timeout=5)
        return value

    game._free_cash_conn = synchronized_free_cash
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: game.buy_offer_for_employee(1001, offer_id, employee_id),
                range(2),
            )
        )

    assert sum(result.startswith("✅ Куплено") for result in results) == 1
    assert sum(result == "Предложение уже недоступно." for result in results) == 1

    with db.connect() as conn:
        balance_after = int(
            conn.execute(
                "SELECT balance FROM shops WHERE player_id=1001"
            ).fetchone()[0]
        )
        batches_after = int(
            conn.execute(
                "SELECT COUNT(*) FROM batches WHERE player_id=1001"
            ).fetchone()[0]
        )
        ledger_count = int(
            conn.execute(
                """SELECT COUNT(*) FROM ledger
                   WHERE player_id=1001 AND kind='procurement'
                     AND reference_type='offer' AND reference_id=?""",
                (offer_id,),
            ).fetchone()[0]
        )

    assert balance_before - balance_after == total
    assert batches_after - batches_before == 1
    assert ledger_count == 1
