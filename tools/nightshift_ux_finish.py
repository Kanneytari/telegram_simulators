from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"
TESTS = ROOT / "shadow_market_simulator" / "tests"

def read(path): return Path(path).read_text(encoding="utf-8")
def write(path, text): Path(path).write_text(text, encoding="utf-8")
def section(path, start, end, new):
    text = read(path); i = text.find(start); j = text.find(end, i + len(start))
    if i < 0 or j < 0: raise RuntimeError(f"{path}: section missing {start!r} -> {end!r}")
    write(path, text[:i] + new.rstrip() + "\n\n" + text[j:])

# Fix no-skladmen branch in generated batch UI.
handlers = APP / "ui_staff_handlers.py"
text = read(handlers)
old = '        rows.append([InlineKeyboardButton(text="Назначить складмена", callback_data=f"team:reassign:{batch_id}")]) if warehouse_count else [InlineKeyboardButton(text="Нанять сотрудника", callback_data="team:recruit")]'
new = '        if warehouse_count:\n            rows.append([InlineKeyboardButton(text="Назначить складмена", callback_data=f"team:reassign:{batch_id}")])\n        else:\n            rows.append([InlineKeyboardButton(text="Нанять сотрудника", callback_data="team:recruit")])'
if old not in text: raise RuntimeError("batch no-skladmen branch not found")
write(handlers, text.replace(old, new, 1))

# Disputes: immediate explanation and current role name.
disputes = APP / "ui_disputes.py"
section(disputes, "def decision_keyboard(", "async def render_dispute(", r'''def decision_keyboard(dispute_id: int, page: int = 0, *, has_reply: bool = False) -> InlineKeyboardMarkup:
    back = f"inbox:page:{page}" if page else "menu:inbox"
    rows: list[list[InlineKeyboardButton]] = []
    if not has_reply:
        rows.append([InlineKeyboardButton(text="Запросить пояснение", callback_data=f"dispute:ask:{dispute_id}:{page}")])
    rows.extend([
        [
            InlineKeyboardButton(text="Вернуть 100%", callback_data=f"dispute:amount:{dispute_id}:refund:{page}"),
            InlineKeyboardButton(text="Вернуть 50%", callback_data=f"dispute:amount:{dispute_id}:partial:{page}"),
        ],
        [InlineKeyboardButton(text="Отказать", callback_data=f"dispute:reject:{dispute_id}:{page}")],
        nav_row(back, "← Входящие"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)''')
section(disputes, "async def render_dispute(", "def source_keyboard(", r'''async def render_dispute(target: Message, game, player_id: int, dispute_id: int, *, page: int = 0) -> bool:
    row = _dispute_context(game, player_id, dispute_id)
    if not row or row["status"] != "open":
        return False
    product_rating = rating(float(row["product_rating"] or 0), 1 if row["product_rating"] else 0)
    courier_rating = rating(float(row["courier_rating"] or 0), 1 if row["courier_rating"] else 0)
    text = (
        f"<b>⚖️ Заказ #{row['order_id']} · {money(row['revenue'])}</b>\n\n"
        f"{clean(row['message'])}\n\n"
        f"Товар: {clean(row['product_title'])} · оценка {product_rating}\n"
        f"Закладчик: {clean(row['employee_alias'])} · оценка {courier_rating}"
    )
    if row["courier_reply"]:
        text += f"\n\n<b>Пояснение закладчика</b>\n{clean(row['courier_reply'])}"
    else:
        text += "\n\nПояснение закладчика не запрошено."
    await present(target, text, decision_keyboard(dispute_id, page, has_reply=bool(row["courier_reply"])))
    return True''')

# Analytics vocabulary.
analytics = APP / "business_analytics.py"
text = read(analytics).replace("Курьеры:", "Закладчики:").replace("курьеров", "закладчиков").replace("Денег сейчас:", "Баланс сейчас:")
write(analytics, text)

# UX regression coverage.
write(TESTS / "test_ux_clarity.py", r'''from __future__ import annotations

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
''')

print("finish UX transform ok")
