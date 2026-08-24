from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"
TESTS = ROOT / "shadow_market_simulator" / "tests"

def read(path): return Path(path).read_text(encoding="utf-8")
def write(path, text): Path(path).write_text(text, encoding="utf-8")
def repl(path, old, new, *, minimum=1):
    text = read(path); count = text.count(old)
    if count < minimum: raise RuntimeError(f"{path}: expected >= {minimum} matches, got {count}: {old!r}")
    write(path, text.replace(old, new))

# Dead imports left after removing the duplicate router from ui_staff.py.
ui = APP / "ui_staff.py"
text = read(ui)
text = text.replace("from aiogram import F, Router\n", "")
text = text.replace("from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message", "from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message")
text = text.replace("from .employee_rename import rename_employee\n", "")
text = text.replace("from .recruitment import CHANNELS, DURATION_OPTIONS, VOLUME_OPTIONS", "from .recruitment import CHANNELS, DURATION_OPTIONS")
write(ui, text)

# Current terminology in non-primary profile/event text too.
workflow = APP / "workflow.py"
text = read(workflow)
text = text.replace('"receive_batch": "принимает партию"', '"receive_batch": "получает партию"')
text = text.replace('"handoff": "готовит передачу рознице"', '"handoff": "готовит передачу закладчику"')
text = text.replace('"prepare_positions": "готовит позиции"', '"prepare_positions": "готовит товар"')
text = text.replace('"Подготовка розничных позиций"', '"Подготовка товара к витрине"')
text = text.replace('role = "оптовый" if employee["role"] == "warehouse" else "розничный"', 'role = "складмен" if employee["role"] == "warehouse" else "закладчик"')
text = text.replace('f"Роль: {role}\\nТовар на ответственности: 0 ₽\\n"', 'f"Роль: {role}\\nТовар на руках: 0 ₽\\n"')
write(workflow, text)

# Compact navigation expectations.
compact = TESTS / "test_compact_ui.py"
text = read(compact).replace('"📦 Закупки"', '"📦 Товар"').replace('"🏷 Продажа"', '"🏷 Витрина"')
write(compact, text)

# Direct candidate fixtures now use the actual three-level transport requirement.
for name in ("test_courier_core.py", "test_courier_management.py"):
    path = TESTS / name
    text = read(path).replace('"car_required": 0,', '"transport_required": 0,')
    write(path, text)

# Delayed dispute tests are obsolete: explanation is an intentional instant game convention.
write(TESTS / "test_delayed_disputes.py", r'''from __future__ import annotations

import json
import random
from datetime import timedelta

from app.db import Database
from app.delayed_disputes import DelayedDisputeGameService, DelayedDisputeSimulationEngine
from app.simulation import iso, utcnow


def make_game(tmp_path, speed: float = 1.0):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = DelayedDisputeSimulationEngine(db, speed=speed, rng=random.Random(51))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = DelayedDisputeGameService(db, simulation, rng=random.Random(52))
    return db, simulation, game


def create_dispute(db):
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=1001 AND role='courier' AND active=1 ORDER BY id LIMIT 1"
        ).fetchone()
        client = conn.execute("SELECT * FROM clients WHERE player_id=1001 ORDER BY id LIMIT 1").fetchone()
        batch = conn.execute("SELECT * FROM batches WHERE player_id=1001 ORDER BY id LIMIT 1").fetchone()
        order = conn.execute(
            """INSERT INTO orders(
                   player_id, client_id, employee_id, batch_id, product_id, quantity,
                   revenue, cost, employee_cost, quality, status
               ) VALUES (1001, ?, ?, ?, ?, 1, 8000, 3000, 1500, 80, 'disputed')""",
            (client["id"], employee["id"], batch["id"], batch["product_id"]),
        )
        dispute = conn.execute(
            """INSERT INTO disputes(
                   player_id, order_id, true_cause, message, evidence_json, deadline_at
               ) VALUES (1001, ?, 'EMPLOYEE_ERROR', 'test', ?, ?)""",
            (order.lastrowid, json.dumps({}), iso(utcnow() + timedelta(hours=3))),
        )
        return int(dispute.lastrowid)


def test_employee_explanation_is_immediate(tmp_path):
    db, _, game = make_game(tmp_path)
    dispute_id = create_dispute(db)

    reply = game.ask_employee_about_dispute(1001, dispute_id)

    with db.connect() as conn:
        stored = conn.execute("SELECT courier_reply FROM disputes WHERE id=?", (dispute_id,)).fetchone()[0]
    assert reply
    assert stored == reply
    assert "Пояснение" not in reply


def test_repeated_request_returns_same_explanation(tmp_path):
    db, _, game = make_game(tmp_path)
    dispute_id = create_dispute(db)
    first = game.ask_employee_about_dispute(1001, dispute_id)
    second = game.ask_employee_about_dispute(1001, dispute_id)
    assert second == first


def test_dispute_details_include_immediate_explanation(tmp_path):
    _, _, game = make_game(tmp_path)
    dispute_id = create_dispute(game.db)
    game.ask_employee_about_dispute(1001, dispute_id)
    details = game.dispute_details(1001, dispute_id)
    assert details is not None
    assert "Ответ сотрудника" in details
''')

# Expected player-facing wording changes.
updates = {
    "test_procurement_market.py": [("Партия куплена", "✅ Куплено")],
    "test_staff_insights.py": [
        ("Статус: <b>готовит позиции", "Статус: <b>готовит товар"),
        ("поз. / игровые сутки", "фасовок / игровые сутки"),
    ],
    "test_staff_responsibility.py": [("Ответственный", "Складмен")],
    "test_wholesale_compensation.py": [
        ("Оплата будет начислена после успешной передачи товара рознице", "Оплата складмену будет начислена после успешной передачи товара")
    ],
    "test_workflow_pipeline.py": [("оптовый", "складмен")],
}
for name, pairs in updates.items():
    path = TESTS / name
    text = read(path)
    for old, new in pairs:
        if old not in text: raise RuntimeError(f"{name}: missing {old!r}")
        text = text.replace(old, new)
    write(path, text)

ui_scenarios = TESTS / "test_ui_scenarios.py"
text = read(ui_scenarios)
text = text.replace('assert "Закупки" in target.text', 'assert "Товар" in target.text')
text = text.replace('assert "Продажа" in target.text', 'assert "Витрина" in target.text')
text = text.replace('assert "Витрина" not in text', 'assert "Продажа" not in text')
write(ui_scenarios, text)

print("test alignment ok")
