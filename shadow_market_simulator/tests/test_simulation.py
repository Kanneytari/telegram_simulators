from __future__ import annotations

import random
from datetime import timedelta

from app.db import Database
from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from app.simulation import iso, utcnow


def make_game(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    rng = random.Random(42)
    simulation = CourierManagementSimulationEngine(db, speed=8.0, rng=rng)
    game = CourierManagementGameService(db, simulation, rng=rng)
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
def test_time_advance_without_retail_stock_creates_no_orders(tmp_path):
    db, simulation, _ = make_game(tmp_path)
    before = utcnow() - timedelta(hours=4)
    with db.connect() as conn:
        conn.execute("UPDATE shops SET last_simulated_at=? WHERE player_id=1001", (iso(before),))
        initial_stock = conn.execute("SELECT SUM(remaining) FROM batches WHERE player_id=1001").fetchone()[0]
    result = simulation.advance(1001, utcnow())
    with db.connect() as conn:
        orders = conn.execute("SELECT COUNT(*) FROM orders WHERE player_id=1001").fetchone()[0]
        stock = conn.execute("SELECT SUM(remaining) FROM batches WHERE player_id=1001").fetchone()[0]
    assert result.orders_created == 0
    assert orders == 0
    assert stock == initial_stock
def test_procurement_spends_cash_and_creates_ledger_entry(tmp_path):
    db, _, game = make_game(tmp_path)
    offer = game.offers(1001)[0]
    total = int(offer["quantity"] * offer["unit_cost"])
    with db.connect() as conn:
        conn.execute("UPDATE shops SET balance=100000000 WHERE player_id=1001")
        warehouse = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' AND active=1 LIMIT 1"
        ).fetchone()
        before = int(conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0])
        ledger_before = int(conn.execute(
            "SELECT COUNT(*) FROM ledger WHERE player_id=1001 AND kind='procurement'"
        ).fetchone()[0])
    game.buy_offer_for_employee(1001, int(offer["id"]), int(warehouse["id"]))
    with db.connect() as conn:
        after = int(conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0])
        ledger_after = int(conn.execute(
            "SELECT COUNT(*) FROM ledger WHERE player_id=1001 AND kind='procurement'"
        ).fetchone()[0])
    assert after == before - total
    assert ledger_after == ledger_before + 1


def test_listing_price_changes_by_five_percent(tmp_path):
    _, _, game = make_game(tmp_path)
    listing = game.listings(1001)[0]
    old = listing["price"]
    game.change_listing_price(1001, listing["id"], 5)
    new = [row for row in game.listings(1001) if row["id"] == listing["id"]][0]["price"]
    assert new > old
