from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from app.analytics.business_analytics import finance_text, normalize_period, overview_text, products_text
from app.staff.couriers.management import CourierManagementSimulationEngine
from app.core.database import Database


PLAYER = 1001
NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(91))
    simulation.seed_catalog()
    simulation.ensure_player(PLAYER, "tester")
    return db


def set_old_shop(db, days: int = 40):
    with db.connect() as conn:
        conn.execute(
            "UPDATE shops SET created_at=? WHERE player_id=?",
            ((NOW - timedelta(days=days)).isoformat(), PLAYER),
        )


def entities(conn, product_id: int = 1):
    employee = conn.execute(
        "SELECT id FROM employees WHERE player_id=? AND role='courier' ORDER BY id LIMIT 1",
        (PLAYER,),
    ).fetchone()
    client = conn.execute(
        "SELECT id FROM clients WHERE player_id=? ORDER BY id LIMIT 1",
        (PLAYER,),
    ).fetchone()
    batch = conn.execute(
        "SELECT id FROM batches WHERE player_id=? AND product_id=? ORDER BY id LIMIT 1",
        (PLAYER, product_id),
    ).fetchone()
    return int(employee["id"]), int(client["id"]), int(batch["id"])


def add_order(
    conn,
    *,
    when: datetime,
    product_id: int = 1,
    revenue: int = 10_000,
    cost: int = 4_000,
    employee_cost: int = 1_000,
    quantity: int = 1,
    repeat: int = 0,
    product_rating: int | None = 5,
    courier_rating: int | None = 5,
):
    employee_id, client_id, batch_id = entities(conn, product_id)
    cur = conn.execute(
        """INSERT INTO orders(
               player_id, client_id, employee_id, batch_id, product_id, quantity,
               revenue, cost, employee_cost, quality, customer_was_repeat, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 85, ?, ?)""",
        (
            PLAYER,
            client_id,
            employee_id,
            batch_id,
            product_id,
            quantity,
            revenue,
            cost,
            employee_cost,
            repeat,
            when.isoformat(),
        ),
    )
    if product_rating is not None and courier_rating is not None:
        conn.execute(
            """INSERT INTO order_ratings(
                   order_id, player_id, client_id, employee_id, product_id,
                   product_rating, courier_rating, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(cur.lastrowid),
                PLAYER,
                client_id,
                employee_id,
                product_id,
                product_rating,
                courier_rating,
                when.isoformat(),
            ),
        )
    return int(cur.lastrowid)


def add_shop_refund(conn, order_id: int, amount: int, when: datetime, source: str = "shop"):
    conn.execute(
        """INSERT INTO disputes(
               player_id, order_id, true_cause, message, evidence_json, status,
               decision, refund_amount, refund_source, deadline_at, created_at, resolved_at
           ) VALUES (?, ?, 'QUALITY_COMPLAINT', 'test', '{}', 'resolved',
                     'refund', ?, ?, ?, ?, ?)""",
        (
            PLAYER,
            order_id,
            amount,
            source,
            (when + timedelta(hours=1)).isoformat(),
            when.isoformat(),
            when.isoformat(),
        ),
    )


def assert_clean(text: str):
    lowered = text.lower()
    assert "none" not in lowered
    assert "nan" not in lowered
    assert "inf" not in lowered
    assert "/0" not in lowered


def test_periods_are_only_seven_or_thirty_days():
    assert normalize_period("7") == "7"
    assert normalize_period("30") == "30"
    assert normalize_period("all") == "7"
    assert normalize_period("broken") == "7"


def test_new_game_without_sales_is_human_readable(tmp_path):
    db = make_system(tmp_path)

    overview = overview_text(db, PLAYER, "7", now=NOW)
    products = products_text(db, PLAYER, "7", now=NOW)
    finance = finance_text(db, PLAYER, "7", now=NOW)

    assert "Продаж за период пока нет" in overview
    assert "пока нет оценок" in overview
    assert "пока нет заказов" in overview
    assert "сравнение появится позже" in overview
    assert "Пока нет продаж" in products
    assert "Продажи: <b>0 ₽</b>" in finance
    assert "Серьёзных денежных потерь за период нет" in finance
    for text in (overview, products, finance):
        assert_clean(text)


def test_no_active_employees_is_reported_without_crash(tmp_path):
    db = make_system(tmp_path)
    with db.connect() as conn:
        conn.execute("UPDATE employees SET active=0, available=0 WHERE player_id=?", (PLAYER,))

    text = overview_text(db, PLAYER, "7", now=NOW)
    assert "Магазин не может нормально продавать" in text
    assert "Нет сотрудников" in text
    assert_clean(text)


def test_improvement_compares_exact_previous_period(tmp_path):
    db = make_system(tmp_path)
    set_old_shop(db)
    with db.connect() as conn:
        previous_when = NOW - timedelta(days=10)
        current_when = NOW - timedelta(days=2)
        for _ in range(4):
            add_order(conn, when=previous_when, revenue=8_000, cost=4_000, employee_cost=1_000, product_rating=4, courier_rating=4)
        for _ in range(8):
            add_order(conn, when=current_when, revenue=10_000, cost=4_000, employee_cost=1_000, repeat=1, product_rating=5, courier_rating=5)

    text = overview_text(db, PLAYER, "7", now=NOW)
    assert "Магазин растёт" in text
    assert "Заработано: <b>+40,000 ₽</b> ↑" in text
    assert "Заказов: <b>8</b> ↑" in text
    assert "Товар: <b>5.0/5</b> ↑" in text
    assert "Возвращаются: <b>100%</b> ↑" in text
    assert_clean(text)


def test_worsening_and_losses_are_visible(tmp_path):
    db = make_system(tmp_path)
    set_old_shop(db)
    with db.connect() as conn:
        previous_when = NOW - timedelta(days=10)
        current_when = NOW - timedelta(days=2)
        for _ in range(6):
            add_order(conn, when=previous_when, revenue=10_000, cost=3_000, employee_cost=1_000, product_rating=5, courier_rating=5)
        current_order = add_order(
            conn,
            when=current_when,
            revenue=8_000,
            cost=5_000,
            employee_cost=1_500,
            product_rating=3,
            courier_rating=3,
        )
        add_shop_refund(conn, current_order, 3_000, current_when)

    overview = overview_text(db, PLAYER, "7", now=NOW)
    finance = finance_text(db, PLAYER, "7", now=NOW)
    assert "Магазин сейчас теряет деньги" in overview
    assert "На возвратах потеряно 3,000 ₽" in overview
    assert "Возвраты покупателям: <b>3,000 ₽</b>" in finance
    assert "Заработано:</b> <b>-1,500 ₽</b> ↓" in finance
    assert_clean(overview)
    assert_clean(finance)


def test_earned_uses_accruals_and_excludes_investment_and_employee_paid_refund(tmp_path):
    db = make_system(tmp_path)
    set_old_shop(db)
    when = NOW - timedelta(days=1)
    with db.connect() as conn:
        order_id = add_order(
            conn,
            when=when,
            revenue=10_000,
            cost=3_000,
            employee_cost=1_000,
            product_rating=5,
            courier_rating=5,
        )
        add_shop_refund(conn, order_id, 2_000, when, source="shop")
        second = add_order(
            conn,
            when=when,
            revenue=0,
            cost=0,
            employee_cost=0,
            product_rating=None,
            courier_rating=None,
        )
        add_shop_refund(conn, second, 2_000, when, source="employee")
        conn.execute(
            """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note, created_at)
               VALUES (?, -5000, 'staff_investment', 'employee', 1, 'test investment', ?)""",
            (PLAYER, when.isoformat()),
        )

    text = finance_text(db, PLAYER, "7", now=NOW)
    assert "Заработано:</b> <b>+4,000 ₽</b>" in text
    assert "Вложено в развитие: <b>5,000 ₽</b>" in text
    assert "Возвраты и потери: −2,000 ₽" in text
    assert_clean(text)


def test_period_boundaries_do_not_double_count_orders(tmp_path):
    db = make_system(tmp_path)
    set_old_shop(db)
    current_start = NOW - timedelta(days=7)
    previous_start = NOW - timedelta(days=14)
    with db.connect() as conn:
        add_order(conn, when=previous_start, revenue=7_000, cost=3_000, employee_cost=1_000)
        add_order(conn, when=current_start, revenue=9_000, cost=3_000, employee_cost=1_000)
        add_order(conn, when=NOW, revenue=99_000, cost=0, employee_cost=0)

    text = overview_text(db, PLAYER, "7", now=NOW)
    assert "Заказов: <b>1</b>" in text
    assert "+5,000 ₽" in text
    assert "99,000" not in text
    assert_clean(text)


def test_products_show_leaders_and_actionable_problems(tmp_path):
    db = make_system(tmp_path)
    set_old_shop(db)
    with db.connect() as conn:
        previous_when = NOW - timedelta(days=10)
        current_when = NOW - timedelta(days=2)
        for _ in range(4):
            add_order(conn, when=previous_when, product_id=1, revenue=8_000, cost=3_000, employee_cost=1_000, product_rating=4)
        for _ in range(8):
            add_order(conn, when=current_when, product_id=1, revenue=9_000, cost=3_000, employee_cost=1_000, product_rating=5)
        for _ in range(3):
            add_order(conn, when=current_when, product_id=2, revenue=8_000, cost=4_000, employee_cost=1_000, product_rating=3)

    text = products_text(db, PLAYER, "7", now=NOW)
    assert "Хорошо идут" in text
    assert "Требуют внимания" in text
    assert "Amphetamine" in text
    assert "MDMA" in text
    assert "Оценка 3.0/5" in text
    assert "заработано" in text
    assert_clean(text)
