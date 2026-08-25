from __future__ import annotations

import json
import random
from datetime import timedelta

from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from app.db import Database
from app.simulation import iso, utcnow


CURRENT_PRODUCT_TITLES = [
    "Amphetamine",
    "MDMA",
    "Cocaine",
    "Mephedrone",
    "LSD",
    "Hash",
    "Weed",
]


def make_game(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, rng=random.Random(10))
    simulation.ensure_player(1001, "tester")
    game = CourierManagementGameService(db, simulation, rng=random.Random(11))
    return db, simulation, game


def create_dispute(db, revenue: int = 10000):
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
               ) VALUES (1001, ?, ?, ?, ?, 1, ?, 3000, 1500, 80, 'disputed')""",
            (client["id"], employee["id"], batch["id"], batch["product_id"], revenue),
        )
        dispute = conn.execute(
            """INSERT INTO disputes(
                   player_id, order_id, true_cause, message, evidence_json, deadline_at
               ) VALUES (1001, ?, 'EMPLOYEE_ERROR', 'test', ?, ?)""",
            (order.lastrowid, json.dumps({}), iso(utcnow() + timedelta(hours=2))),
        )
        conn.execute(
            """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json)
               VALUES (1001, 'dispute', 'important', 'test', 'test', ?)""",
            (json.dumps({"dispute_id": dispute.lastrowid}),),
        )
        return dispute.lastrowid, employee["id"]


def test_current_catalog_and_listing_prices(tmp_path):
    db, _, _ = make_game(tmp_path)
    with db.connect() as conn:
        products = conn.execute(
            "SELECT title FROM products WHERE active=1 ORDER BY id"
        ).fetchall()
        listings = conn.execute(
            "SELECT price FROM listings WHERE player_id=1001 AND pack_size=1 ORDER BY product_id"
        ).fetchall()
    assert [row["title"] for row in products] == CURRENT_PRODUCT_TITLES
    assert len(listings) == len(CURRENT_PRODUCT_TITLES)
    assert all(int(row["price"]) > 0 for row in listings)


def test_starter_stock_stays_off_storefront_until_manual_distribution(tmp_path):
    db, _, _ = make_game(tmp_path)
    with db.connect() as conn:
        warehouse_units = int(conn.execute(
            """SELECT COALESCE(SUM(remaining),0) FROM batches
               WHERE player_id=1001 AND product_id=1 AND status='warehouse'"""
        ).fetchone()[0])
        published_units = int(conn.execute(
            """SELECT COALESCE(SUM(position_count*pack_size),0) FROM retail_positions
               WHERE player_id=1001 AND product_id=1 AND position_count>0"""
        ).fetchone()[0])
    assert warehouse_units > 0
    assert published_units == 0


def test_partial_refund_can_be_paid_from_employee_deposit(tmp_path):
    db, _, game = make_game(tmp_path)
    dispute_id, employee_id = create_dispute(db, 10000)
    with db.connect() as conn:
        before_deposit = conn.execute("SELECT deposit FROM employees WHERE id=?", (employee_id,)).fetchone()[0]
        before_balance = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
        before_profit = conn.execute("SELECT total_profit FROM shops WHERE player_id=1001").fetchone()[0]

    result = game.resolve_dispute_with_source(1001, dispute_id, "partial", "employee")

    with db.connect() as conn:
        employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
        shop = conn.execute("SELECT * FROM shops WHERE player_id=1001").fetchone()
        dispute = conn.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
    assert "депозит" in result.lower()
    assert employee["deposit"] == before_deposit - 5000
    assert shop["balance"] == before_balance - 5000
    assert shop["total_profit"] == before_profit
    assert dispute["refund_amount"] == 5000
    assert dispute["refund_source"] == "employee"
    assert dispute["refund_employee_id"] == employee_id


def test_shop_refund_reduces_shop_profit(tmp_path):
    db, _, game = make_game(tmp_path)
    dispute_id, _ = create_dispute(db, 10000)
    with db.connect() as conn:
        before_balance = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
        before_profit = conn.execute("SELECT total_profit FROM shops WHERE player_id=1001").fetchone()[0]

    game.resolve_dispute_with_source(1001, dispute_id, "partial", "shop")

    with db.connect() as conn:
        shop = conn.execute("SELECT * FROM shops WHERE player_id=1001").fetchone()
        dispute = conn.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
    assert shop["balance"] == before_balance - 5000
    assert shop["total_profit"] == before_profit - 5000
    assert dispute["refund_source"] == "shop"
    assert dispute["refund_amount"] == 5000


def test_expired_dispute_records_automatic_shop_refund(tmp_path):
    db, simulation, _ = make_game(tmp_path)
    dispute_id, _ = create_dispute(db, 10000)
    now = utcnow()
    with db.connect() as conn:
        conn.execute(
            """UPDATE inbox SET expires_at=?
               WHERE player_id=1001 AND kind='dispute'
                 AND json_extract(payload_json, '$.dispute_id')=?""",
            (iso(now - timedelta(minutes=1)), dispute_id),
        )
        simulation._expire_items(conn, 1001, now)

    with db.connect() as conn:
        dispute = conn.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
    assert dispute["decision"] == "auto_partial"
    assert dispute["refund_source"] == "shop"
    assert dispute["refund_amount"] == 5000


def test_stale_reject_cannot_erase_completed_refund_metadata(tmp_path):
    db, _, game = make_game(tmp_path)
    dispute_id, _ = create_dispute(db, 10000)

    game.resolve_dispute_with_source(1001, dispute_id, "partial", "shop")
    with db.connect() as conn:
        balance_after_refund = int(
            conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
        )

    result = game.resolve_dispute_with_source(1001, dispute_id, "reject", "none")

    with db.connect() as conn:
        dispute = conn.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
        balance_after_stale_click = int(
            conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
        )
    assert "уже закрыт" in result.lower()
    assert dispute["decision"] == "partial"
    assert dispute["refund_source"] == "shop"
    assert dispute["refund_amount"] == 5000
    assert balance_after_stale_click == balance_after_refund


def test_refund_without_source_does_not_change_money_or_dispute(tmp_path):
    db, _, game = make_game(tmp_path)
    dispute_id, employee_id = create_dispute(db, 10000)
    with db.connect() as conn:
        before_balance = int(conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0])
        before_deposit = int(conn.execute("SELECT deposit FROM employees WHERE id=?", (employee_id,)).fetchone()[0])

    result = game.resolve_dispute_with_source(1001, dispute_id, "partial", "none")

    with db.connect() as conn:
        dispute = conn.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
        after_balance = int(conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0])
        after_deposit = int(conn.execute("SELECT deposit FROM employees WHERE id=?", (employee_id,)).fetchone()[0])
    assert "выберите источник" in result.lower()
    assert dispute["status"] == "open"
    assert after_balance == before_balance
    assert after_deposit == before_deposit


def test_good_employee_funded_refund_counts_as_won_dispute(tmp_path):
    db, _, game = make_game(tmp_path)
    dispute_id, _ = create_dispute(db, 10000)
    with db.connect() as conn:
        client_id = int(
            conn.execute(
                "SELECT o.client_id FROM disputes d JOIN orders o ON o.id=d.order_id WHERE d.id=?",
                (dispute_id,),
            ).fetchone()[0]
        )
        before_wins = int(conn.execute("SELECT disputes_won FROM clients WHERE id=?", (client_id,)).fetchone()[0])

    game.resolve_dispute_with_source(1001, dispute_id, "refund", "employee")

    with db.connect() as conn:
        after_wins = int(conn.execute("SELECT disputes_won FROM clients WHERE id=?", (client_id,)).fetchone()[0])
    assert after_wins == before_wins + 1
