from __future__ import annotations

import random
from datetime import timedelta

from app.db import Database
from app.game import GameService
from app.courier_management import CourierManagementSimulationEngine, iso, utcnow


def make_game(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    rng = random.Random(42)
    simulation = CourierManagementSimulationEngine(db, speed=8.0, rng=rng)
    game = GameService(db, simulation, rng=rng)
    simulation.ensure_player(1001, "tester")
    return db, simulation, game


def test_new_player_has_operational_state(tmp_path):
    db, _, game = make_game(tmp_path)
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM employees WHERE player_id=1001").fetchone()[0] >= 2
        assert conn.execute("SELECT COUNT(*) FROM clients WHERE player_id=1001").fetchone()[0] >= 20
        assert conn.execute("SELECT SUM(remaining) FROM batches WHERE player_id=1001").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM listings WHERE player_id=1001").fetchone()[0] == 18
    assert "Свободные деньги" in game.dashboard(1001)


def test_time_advance_creates_orders_and_updates_stock(tmp_path):
    db, simulation, _ = make_game(tmp_path)
    before = utcnow() - timedelta(hours=4)
    with db.connect() as conn:
        conn.execute("UPDATE shops SET last_simulated_at=? WHERE player_id=1001", (iso(before),))
        initial_stock = conn.execute("SELECT SUM(remaining) FROM batches WHERE player_id=1001").fetchone()[0]
    result = simulation.advance(1001, utcnow())
    with db.connect() as conn:
        orders = conn.execute("SELECT COUNT(*) FROM orders WHERE player_id=1001").fetchone()[0]
        stock = conn.execute("SELECT SUM(remaining) FROM batches WHERE player_id=1001").fetchone()[0]
    assert result.orders_created == orders
    assert orders > 0
    assert stock < initial_stock


def test_procurement_spends_cash_and_creates_ledger_entry(tmp_path):
    db, _, game = make_game(tmp_path)
    offer = game.offers(1001)[0]
    total = offer["quantity"] * offer["unit_cost"]
    with db.connect() as conn:
        conn.execute("UPDATE shops SET balance=1000000 WHERE player_id=1001")
        before = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
    game.buy_offer(1001, offer["id"])
    with db.connect() as conn:
        after = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
        ledger = conn.execute("SELECT COUNT(*) FROM ledger WHERE player_id=1001 AND kind='procurement'").fetchone()[0]
    assert after == before - total
    assert ledger == 1


def test_listing_price_changes_by_five_percent(tmp_path):
    _, _, game = make_game(tmp_path)
    listing = game.listings(1001)[0]
    old = listing["price"]
    game.change_listing_price(1001, listing["id"], 5)
    new = [row for row in game.listings(1001) if row["id"] == listing["id"]][0]["price"]
    assert new > old
