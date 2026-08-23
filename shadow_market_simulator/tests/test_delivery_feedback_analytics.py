from __future__ import annotations

import random

from app.db import Database
from app.delivery_feedback_analytics import (
    delivery_staff_rows,
    delivery_staff_text,
    employee_delivery_reviews_text,
)
from app.wholesale_compensation import WholesaleCompensationSimulationEngine


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = WholesaleCompensationSimulationEngine(db, speed=1.0, rng=random.Random(141))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    return db


def add_review(db: Database, employee_id: int, index: int, delivery: str = "bad") -> None:
    with db.connect() as conn:
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
               ) VALUES (1001, ?, ?, ?, ?, 1, ?, 3000, 1500, 82, 'completed')""",
            (client["id"], employee_id, batch["id"], batch["product_id"], 8000 + index),
        )
        conn.execute(
            """INSERT INTO reviews(
                   player_id, order_id, client_id, product_id, employee_id,
                   rating, text, quality_sentiment, delivery_sentiment, created_at
               ) VALUES (1001, ?, ?, ?, ?, ?, ?, 'good', ?, datetime('now', ?))""",
            (
                order.lastrowid,
                client["id"],
                batch["product_id"],
                employee_id,
                2 if delivery == "bad" else 5,
                f"review-{index}",
                delivery,
                f"-{index} minutes",
            ),
        )


def test_delivery_negative_reviews_are_grouped_by_employee(tmp_path):
    db = make_system(tmp_path)
    with db.connect() as conn:
        employees = conn.execute(
            "SELECT id, alias FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id"
        ).fetchall()
    first = employees[0]
    second = employees[1]

    for index in range(3):
        add_review(db, int(first["id"]), index, "bad")
    add_review(db, int(first["id"]), 10, "good")
    add_review(db, int(second["id"]), 11, "good")

    rows = delivery_staff_rows(db, 1001, "30")
    first_row = next(row for row in rows if int(row["id"]) == int(first["id"]))
    assert int(first_row["review_count"]) == 4
    assert int(first_row["bad_delivery"]) == 3

    text = delivery_staff_text(db, 1001, "30")
    assert str(first["alias"]) in text
    assert "3 из 4 (75.0%)" in text
    assert "Всего негативных отзывов: <b>3</b> из 5 (60.0%)" in text


def test_employee_delivery_reviews_are_paginated_five_per_page(tmp_path):
    db = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT id, alias FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()

    for index in range(6):
        add_review(db, int(employee["id"]), index, "bad")

    first_page, pages, page = employee_delivery_reviews_text(
        db, 1001, int(employee["id"]), "30", 0
    )
    assert pages == 2
    assert page == 0
    assert "страница 1/2" in first_page
    assert first_page.count("review-") == 5
    assert "review-0" in first_page
    assert "review-4" in first_page
    assert "review-5" not in first_page

    second_page, pages, page = employee_delivery_reviews_text(
        db, 1001, int(employee["id"]), "30", 1
    )
    assert pages == 2
    assert page == 1
    assert "страница 2/2" in second_page
    assert second_page.count("review-") == 1
    assert "review-5" in second_page


def test_employee_without_delivery_negatives_has_empty_state(tmp_path):
    db = make_system(tmp_path)
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()

    add_review(db, int(employee["id"]), 1, "good")
    text, pages, page = employee_delivery_reviews_text(db, 1001, int(employee["id"]), "7", 0)
    assert pages == 1
    assert page == 0
    assert "Негативных отзывов за выбранный период нет." in text
