from __future__ import annotations

import random

from app.customer_trust import CustomerTrustSimulationEngine
from app.db import Database
from app.detailed_analytics import normalize_period, section_text


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CustomerTrustSimulationEngine(db, speed=1.0, rng=random.Random(91))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    return db


def test_period_normalization():
    assert normalize_period("7") == "7"
    assert normalize_period("30") == "30"
    assert normalize_period("all") == "all"
    assert normalize_period("broken") == "30"


def test_all_detailed_analytics_sections_render(tmp_path):
    db = make_system(tmp_path)

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
               ) VALUES (1001, ?, ?, ?, ?, 1, 8000, 3000, 520, 82, 'completed')""",
            (client["id"], employee["id"], batch["id"], batch["product_id"]),
        )
        conn.execute(
            """INSERT INTO order_ratings(
                   order_id, player_id, client_id, product_id, employee_id,
                   product_rating, courier_rating
               ) VALUES (?, 1001, ?, ?, ?, 5, 4)""",
            (order.lastrowid, client["id"], batch["product_id"], employee["id"]),
        )
        conn.execute(
            """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
               VALUES (1001, 8000, 'sale', 'order', ?, 'test sale')""",
            (order.lastrowid,),
        )

    expected = {
        "overview": "Сводка",
        "daily": "По дням",
        "products": "По товарам",
        "finance": "Финансы",
        "staff": "Сотрудники",
        "quality": "Качество",
        "customers": "Клиенты",
    }
    for section, heading in expected.items():
        rendered = section_text(db, 1001, section, "30")
        assert heading in rendered
        assert isinstance(rendered, str)
        assert len(rendered) > 20

    assert "8,000 ₽" in section_text(db, 1001, "overview", "30")
    assert "5.00" in section_text(db, 1001, "quality", "30")


def test_unknown_section_falls_back_to_overview(tmp_path):
    db = make_system(tmp_path)
    rendered = section_text(db, 1001, "missing", "7")
    assert "Сводка" in rendered
    assert "7 дней" in rendered
