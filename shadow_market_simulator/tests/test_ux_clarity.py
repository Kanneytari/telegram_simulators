from __future__ import annotations

import asyncio
import random

from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine, TRANSPORT
from app.courier_recruitment import CourierRecruitmentService
from app.db import Database
from app.ui_commerce import render_product_root
from app.ui_navigation import _home_snapshot, home_keyboard
from app.ui_staff import render_allocation, render_batches
from app.ui_staff_handlers import render_batch

PLAYER_ID = 77881


def make_system(tmp_path):
    db = Database(str(tmp_path / "ux.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(7001))
    simulation.ensure_player(PLAYER_ID, "ux")
    game = CourierManagementGameService(db, simulation, rng=random.Random(7002))
    recruitment = CourierRecruitmentService(db, speed=1.0, rng=random.Random(7003))
    return db, simulation, game, recruitment



class Target:
    def __init__(self):
        self.text = None
        self.reply_markup = None
        self.photo = None

    async def edit_text(self, text, **kwargs):
        self.text = text
        self.reply_markup = kwargs.get("reply_markup")

    async def answer(self, text, **kwargs):
        self.text = text
        self.reply_markup = kwargs.get("reply_markup")

    async def delete(self):
        return None

    async def answer_photo(self, photo, caption=None, **kwargs):
        self.text = caption
        self.reply_markup = kwargs.get("reply_markup")


def button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_main_menu_uses_product_and_storefront(tmp_path):
    db, simulation, game, _ = make_system(tmp_path)
    text, opened, urgent = _home_snapshot(db, game, simulation, PLAYER_ID)
    labels = button_texts(home_keyboard(opened, urgent))
    assert "📦 Товар" in labels
    assert "🏷 Витрина" in labels
    assert "🔄 Обновить" in labels
    assert "Баланс:" in text
    assert "Свободно:" in text
    assert "Передай товар закладчику" not in text
    assert "<blockquote>Стафф уже на складе!\nНажми на кнопку 📦 Товар</blockquote>" in text


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


def test_first_handoff_tutorial_guides_product_warehouse_and_batch(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    assert game.needs_first_handoff_tutorial(PLAYER_ID) is True
    target = Target()
    asyncio.run(render_product_root(target, db, game, PLAYER_ID))
    assert "<blockquote>Нажми на кнопку 🚚 Склад</blockquote>" in target.text
    product_labels = button_texts(target.reply_markup)
    assert any("🚚 Склад" in label for label in product_labels)
    assert not any("Обновить" in label for label in product_labels)
    asyncio.run(render_batches(target, game, PLAYER_ID))
    assert "<blockquote>Выбери партию стаффа, которую хочешь передать закладчику.</blockquote>" in target.text
    with db.connect() as conn:
        batch = conn.execute("SELECT id FROM batches WHERE player_id=? AND status='warehouse' AND remaining>0 ORDER BY id LIMIT 1", (PLAYER_ID,)).fetchone()
    assert batch
    batch_id = int(batch["id"])
    asyncio.run(render_batch(target, game, PLAYER_ID, batch_id))
    assert "<blockquote>Выбери закладчика, которому передашь стафф.</blockquote>" in target.text
    _, staff = game.retail_staff_for_batch(PLAYER_ID, batch_id)
    recipient = max(staff, key=lambda row: int(row["recommended_quantity"]))
    quantity = int(recipient["recommended_quantity"])
    assert quantity > 0
    asyncio.run(render_allocation(target, game, PLAYER_ID, batch_id, int(recipient["id"]), quantity))
    assert f"<blockquote>Проверь количество и нажми кнопку «✅ Отправить {quantity} ед.».</blockquote>" in target.text
    allocation_rows = [[button.text for button in row] for row in target.reply_markup.inline_keyboard]
    assert allocation_rows[0] == ["−5", f"📦 {quantity} ед.", "+5"]
    assert allocation_rows[1] == [f"✅ Отправить {quantity} ед."]
    assert allocation_rows[-1] == ["← Назад", "🏠 Меню"]
    assert not any("Всё" in label for row in allocation_rows for label in row)


def test_first_handoff_tutorial_disappears_after_transfer(tmp_path):
    db, simulation, game, _ = make_system(tmp_path)
    with db.connect() as conn:
        batch = conn.execute("SELECT id FROM batches WHERE player_id=? AND status='warehouse' AND remaining>=5 ORDER BY id LIMIT 1", (PLAYER_ID,)).fetchone()
        courier = conn.execute("SELECT id FROM employees WHERE player_id=? AND role='courier' AND active=1 ORDER BY deposit DESC LIMIT 1", (PLAYER_ID,)).fetchone()
    assert batch and courier
    result = game.allocate_to_retail(PLAYER_ID, int(batch["id"]), int(courier["id"]), 5)
    assert "Назначено" in result
    assert game.needs_first_handoff_tutorial(PLAYER_ID) is False
    home, _, _ = _home_snapshot(db, game, simulation, PLAYER_ID)
    assert "Стафф уже на складе!" not in home
    target = Target()
    asyncio.run(render_product_root(target, db, game, PLAYER_ID))
    assert "Нажми на кнопку 🚚 Склад" not in target.text
    asyncio.run(render_batches(target, game, PLAYER_ID))
    assert "Выбери партию стаффа" not in target.text
