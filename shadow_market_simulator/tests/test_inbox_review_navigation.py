from __future__ import annotations

import random
from types import SimpleNamespace

from app.customer_expectations import PriceExpectationSimulationEngine
from app.db import Database
from app.inbox_close_handlers import close_destination
from app.inbox_lifecycle import install_inbox_lifecycle
from app.product_review_handlers import load_product_review_page


def make_db(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = PriceExpectationSimulationEngine(db, speed=1.0, rng=random.Random(71))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    install_inbox_lifecycle(db)
    return db


def add_candidate(conn, alias: str, status: str = "open") -> int:
    cur = conn.execute(
        """INSERT INTO candidates(
               player_id, alias, role, desired_pay, deposit, has_car,
               reliability, attention, honesty, loyalty, summary,
               expires_at, status, campaign_id
           ) VALUES (1001, ?, 'courier', 1500, 25000, 0,
                     0.8, 0.8, 0.8, 0.8, 'test',
                     datetime('now','+1 day'), ?, 777)""",
        (alias, status),
    )
    return int(cur.lastrowid)


def test_recruitment_notification_closes_when_last_active_candidate_is_gone(tmp_path):
    db = make_db(tmp_path)
    with db.connect() as conn:
        first = add_candidate(conn, "A")
        second = add_candidate(conn, "B")
        item = conn.execute(
            """INSERT INTO inbox(player_id, kind, priority, title, body)
               VALUES (1001, 'recruitment_result', 'important', 'Новые кандидаты', 'test')"""
        ).lastrowid
        assert conn.execute("SELECT status FROM inbox WHERE id=?", (item,)).fetchone()[0] == "open"
        conn.execute("UPDATE candidates SET status='rejected' WHERE id=?", (first,))
        assert conn.execute("SELECT status FROM inbox WHERE id=?", (item,)).fetchone()[0] == "open"
        conn.execute("UPDATE candidates SET status='hired' WHERE id=?", (second,))
        assert conn.execute("SELECT status FROM inbox WHERE id=?", (item,)).fetchone()[0] == "closed"


def test_empty_recruitment_result_is_closed_immediately(tmp_path):
    db = make_db(tmp_path)
    with db.connect() as conn:
        item = conn.execute(
            """INSERT INTO inbox(player_id, kind, priority, title, body)
               VALUES (1001, 'recruitment_result', 'normal', 'Новые кандидаты', '0 анкет')"""
        ).lastrowid
        assert conn.execute("SELECT status FROM inbox WHERE id=?", (item,)).fetchone()[0] == "closed"


def test_close_destination_depends_on_remaining_open_messages(tmp_path):
    db = make_db(tmp_path)
    assert close_destination(db, 1001) == "home"
    with db.connect() as conn:
        item = conn.execute(
            """INSERT INTO inbox(player_id, kind, priority, title, body)
               VALUES (1001, 'payroll_report', 'normal', 'test', 'test')"""
        ).lastrowid
    assert close_destination(db, 1001) == "inbox"
    with db.connect() as conn:
        conn.execute("UPDATE inbox SET status='closed' WHERE id=?", (item,))
    assert close_destination(db, 1001) == "home"


def test_product_reviews_are_paginated_five_newest_first(tmp_path):
    db = make_db(tmp_path)
    game = SimpleNamespace(db=db)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        client = conn.execute(
            "SELECT id FROM clients WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
        batch = conn.execute(
            "SELECT id, product_id FROM batches WHERE player_id=1001 AND product_id=1 ORDER BY id LIMIT 1"
        ).fetchone()
        assert employee and client and batch
        for index in range(12):
            order_id = conn.execute(
                """INSERT INTO orders(
                       player_id, client_id, employee_id, batch_id, product_id,
                       quantity, revenue, cost, employee_cost, quality
                   ) VALUES (1001, ?, ?, ?, 1, 1, 6000, 3000, 1500, 80)""",
                (client["id"], employee["id"], batch["id"]),
            ).lastrowid
            conn.execute(
                """INSERT INTO reviews(
                       player_id, order_id, client_id, product_id, employee_id,
                       rating, text, quality_sentiment, delivery_sentiment, created_at
                   ) VALUES (1001, ?, ?, 1, ?, 4, ?, 'good', 'good', ?)""",
                (
                    order_id,
                    client["id"],
                    employee["id"],
                    f"review-{index}",
                    f"2026-08-24 00:{index:02d}:00",
                ),
            )

    first = load_product_review_page(game, 1001, 1, 0)
    second = load_product_review_page(game, 1001, 1, 1)
    third = load_product_review_page(game, 1001, 1, 2)

    assert first["total"] == 12
    assert len(first["rows"]) == 5
    assert len(second["rows"]) == 5
    assert len(third["rows"]) == 2
    assert [row["text"] for row in first["rows"]] == [
        "review-11", "review-10", "review-9", "review-8", "review-7"
    ]
    assert [row["text"] for row in third["rows"]] == ["review-1", "review-0"]
