from __future__ import annotations

import random

from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine, TRANSPORT
from app.courier_recruitment import CourierRecruitmentService
from app.db import Database
from app.ui_navigation import _home_snapshot, home_keyboard

PLAYER_ID = 77881


def make_system(tmp_path):
    db = Database(str(tmp_path / "ux.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(7001))
    simulation.ensure_player(PLAYER_ID, "ux")
    game = CourierManagementGameService(db, simulation, rng=random.Random(7002))
    recruitment = CourierRecruitmentService(db, speed=1.0, rng=random.Random(7003))
    return db, simulation, game, recruitment


def button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_main_menu_uses_product_and_storefront(tmp_path):
    db, simulation, game, _ = make_system(tmp_path)
    text, opened, urgent = _home_snapshot(db, game, simulation, PLAYER_ID)
    labels = button_texts(home_keyboard(opened, urgent))
    assert "📦 Товар" in labels
    assert "🏷 Витрина" in labels
    assert "Баланс:" in text
    assert "Свободно:" in text
    assert "Передай товар закладчику" in text


def test_free_status_means_no_tasks_or_stock(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute("SELECT id FROM employees WHERE player_id=? AND role='courier' ORDER BY id LIMIT 1", (PLAYER_ID,)).fetchone()
        batch = conn.execute("SELECT * FROM batches WHERE player_id=? AND status='warehouse' ORDER BY id LIMIT 1", (PLAYER_ID,)).fetchone()
        warehouse = conn.execute("SELECT id FROM employees WHERE player_id=? AND role='warehouse' ORDER BY id LIMIT 1", (PLAYER_ID,)).fetchone()
        assert courier and batch and warehouse
        assert game._task_status(PLAYER_ID, int(courier["id"])) == "свободен"
        cur = conn.execute(
            """INSERT INTO retail_allocations(
                   player_id, batch_id, wholesale_employee_id, retail_employee_id,
                   product_id, quantity, unit_cost, quality, status, completed_at
               ) VALUES (?, ?, ?, ?, ?, 4, ?, ?, 'published', CURRENT_TIMESTAMP)""",
            (PLAYER_ID, int(batch["id"]), int(warehouse["id"]), int(courier["id"]), int(batch["product_id"]), int(batch["unit_cost"]), float(batch["quality"])),
        )
        conn.execute(
            """INSERT INTO retail_positions(
                   player_id, allocation_id, batch_id, employee_id, product_id,
                   pack_size, position_count, unit_cost, quality
               ) VALUES (?, ?, ?, ?, ?, 1, 4, ?, ?)""",
            (PLAYER_ID, int(cur.lastrowid), int(batch["id"]), int(courier["id"]), int(batch["product_id"]), int(batch["unit_cost"]), float(batch["quality"])),
        )
    assert game._task_status(PLAYER_ID, int(courier["id"])) == "ждёт продажи · 4 ед."


def test_recruitment_uses_transport_levels(tmp_path):
    _, _, _, recruitment = make_system(tmp_path)
    draft = recruitment.ensure_draft(PLAYER_ID)
    assert "transport_required" in draft.keys()
    recruitment.update_draft(PLAYER_ID, "transport_required", 1)
    assert int(recruitment.ensure_draft(PLAYER_ID)["transport_required"]) == 1
    recruitment.update_draft(PLAYER_ID, "transport_required", 2)
    assert int(recruitment.ensure_draft(PLAYER_ID)["transport_required"]) == 2
    assert TRANSPORT[1][0] == "велосипед"



def test_recommended_handoff_uses_free_deposit_and_rounds_to_five(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT id FROM employees WHERE player_id=? AND role='courier' ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        batch = conn.execute(
            "SELECT id, unit_cost FROM batches WHERE player_id=? AND status='warehouse' ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        assert courier and batch
        employee_id = int(courier["id"])
        batch_id = int(batch["id"])
        unit_cost = int(batch["unit_cost"])
        exposure = game._employee_exposure(PLAYER_ID, employee_id)
        conn.execute("UPDATE employees SET deposit=? WHERE id=?", (exposure + unit_cost * 27, employee_id))
        conn.execute("UPDATE batches SET remaining=18 WHERE id=?", (batch_id,))

    current_batch, staff = game.retail_staff_for_batch(PLAYER_ID, batch_id)
    employee = next(row for row in staff if int(row["id"]) == employee_id)
    assert int(current_batch["remaining"]) == 18
    assert int(employee["recommended_quantity"]) == 15


def test_recommended_handoff_is_zero_when_deposit_covers_less_than_five(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT id FROM employees WHERE player_id=? AND role='courier' ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        batch = conn.execute(
            "SELECT id, unit_cost FROM batches WHERE player_id=? AND status='warehouse' ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        assert courier and batch
        employee_id = int(courier["id"])
        unit_cost = int(batch["unit_cost"])
        exposure = game._employee_exposure(PLAYER_ID, employee_id)
        conn.execute("UPDATE employees SET deposit=? WHERE id=?", (exposure + unit_cost * 4, employee_id))

    _, staff = game.retail_staff_for_batch(PLAYER_ID, int(batch["id"]))
    employee = next(row for row in staff if int(row["id"]) == employee_id)
    assert int(employee["recommended_quantity"]) == 0
