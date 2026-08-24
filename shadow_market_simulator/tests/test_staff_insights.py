from __future__ import annotations

import random
from datetime import timedelta

from app.db import Database
from app.simulation import iso, utcnow
from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(41))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = CourierManagementGameService(db, simulation, rng=random.Random(42))
    return db, simulation, game


def test_new_game_does_not_put_inventory_on_retail_staff(tmp_path):
    db, simulation, _ = make_system(tmp_path)
    with db.connect() as conn:
        couriers = conn.execute(
            "SELECT id, deposit FROM employees WHERE player_id=1001 AND role='courier' AND active=1"
        ).fetchall()
        positions = conn.execute(
            "SELECT COUNT(*) FROM retail_positions WHERE player_id=1001 AND position_count>0"
        ).fetchone()[0]
    assert couriers
    assert positions == 0
    with db.connect() as conn:
        assert all(simulation.employee_exposure(conn, 1001, row["id"]) == 0 for row in couriers)


def test_profile_separates_current_activity_from_inventory(tmp_path):
    db, simulation, game = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        batch = conn.execute(
            "SELECT * FROM batches WHERE player_id=1001 AND remaining>=10 ORDER BY id LIMIT 1"
        ).fetchone()
        warehouse = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' ORDER BY id LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE batches SET remaining=remaining-10 WHERE id=?", (batch["id"],))
        cur = conn.execute(
            """INSERT INTO retail_allocations(
                   player_id, batch_id, wholesale_employee_id, retail_employee_id,
                   product_id, quantity, unit_cost, quality, status, received_at
               ) VALUES (1001, ?, ?, ?, ?, 10, ?, ?, 'preparing', CURRENT_TIMESTAMP)""",
            (batch["id"], warehouse["id"], courier["id"], batch["product_id"], batch["unit_cost"], batch["quality"]),
        )
        allocation_id = cur.lastrowid
        conn.execute(
            """INSERT INTO employee_tasks(
                   player_id, employee_id, kind, batch_id, allocation_id,
                   product_id, quantity, completes_at, note
               ) VALUES (1001, ?, 'prepare_positions', ?, ?, ?, 10, ?, 'test')""",
            (courier["id"], batch["id"], allocation_id, batch["product_id"], iso(utcnow() + timedelta(hours=2))),
        )

    text = game.employee_details(1001, courier["id"])
    assert "Статус: <b>готовит позиции" in text
    assert "Задача: Подготовка позиций к публикации" in text
    assert "на руках 10 ед." in text
    assert "<b>Товар</b>" in text


def test_publication_history_drives_productivity_and_inventory(tmp_path):
    db, simulation, game = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        batch = conn.execute(
            "SELECT * FROM batches WHERE player_id=1001 AND remaining>=12 ORDER BY id LIMIT 1"
        ).fetchone()
        warehouse = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' ORDER BY id LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE batches SET remaining=remaining-12 WHERE id=?", (batch["id"],))
        cur = conn.execute(
            """INSERT INTO retail_allocations(
                   player_id, batch_id, wholesale_employee_id, retail_employee_id,
                   product_id, quantity, unit_cost, quality, status, received_at
               ) VALUES (1001, ?, ?, ?, ?, 12, ?, ?, 'preparing', CURRENT_TIMESTAMP)""",
            (batch["id"], warehouse["id"], courier["id"], batch["product_id"], batch["unit_cost"], batch["quality"]),
        )
        allocation_id = cur.lastrowid
        simulation._publish_allocation(conn, 1001, allocation_id)

    with db.connect() as conn:
        event = conn.execute(
            "SELECT * FROM publication_events WHERE player_id=1001 AND employee_id=?",
            (courier["id"],),
        ).fetchone()
        positions = conn.execute(
            "SELECT COALESCE(SUM(position_count),0) FROM retail_positions WHERE employee_id=?",
            (courier["id"],),
        ).fetchone()[0]
    assert event is not None
    assert event["positions"] == positions

    text = game.employee_details(1001, courier["id"])
    assert "витрина" in text
    productivity = "\n".join(game._productivity_lines(1001, int(courier["id"])))
    assert "Средняя: <b>" in productivity
    assert "поз. / игровые сутки" in productivity


def test_short_eta_is_safe_for_html_parse_mode(tmp_path):
    db, _, game = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='courier' ORDER BY id LIMIT 1"
        ).fetchone()
        batch = conn.execute(
            "SELECT * FROM batches WHERE player_id=1001 AND remaining>=5 ORDER BY id LIMIT 1"
        ).fetchone()
        warehouse = conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND role='warehouse' ORDER BY id LIMIT 1"
        ).fetchone()
        cur = conn.execute(
            """INSERT INTO retail_allocations(
                   player_id, batch_id, wholesale_employee_id, retail_employee_id,
                   product_id, quantity, unit_cost, quality, status, received_at
               ) VALUES (1001, ?, ?, ?, ?, 5, ?, ?, 'preparing', CURRENT_TIMESTAMP)""",
            (batch["id"], warehouse["id"], courier["id"], batch["product_id"], batch["unit_cost"], batch["quality"]),
        )
        conn.execute(
            """INSERT INTO employee_tasks(
                   player_id, employee_id, kind, batch_id, allocation_id,
                   product_id, quantity, completes_at, note
               ) VALUES (1001, ?, 'prepare_positions', ?, ?, ?, 5, ?, 'short eta')""",
            (courier["id"], batch["id"], cur.lastrowid, batch["product_id"], iso(utcnow() + timedelta(minutes=20))),
        )

    text = game.employee_details(1001, courier["id"])
    assert "менее 1 ч" in text
    assert "<1 ч" not in text
    assert "<1 мин" not in text
