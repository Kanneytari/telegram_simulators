from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"
TESTS = ROOT / "shadow_market_simulator" / "tests"


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"{path}: missing fragment {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


common = APP / "ui_common.py"
replace(
    common,
    "def clean(value: object) -> str:\n    return escape(str(value or \"\"))\n\n\ndef normalize_text",
    "def clean(value: object) -> str:\n    return escape(str(value or \"\"))\n\n\ndef tutorial_hint(text: str) -> str:\n    return f\"<blockquote>{clean(text)}</blockquote>\"\n\n\ndef normalize_text",
)

workflow = APP / "workflow.py"
replace(
    workflow,
    "class WorkflowGameService(OperationsGameService):\n\n    def _task_status",
    "class WorkflowGameService(OperationsGameService):\n\n    def needs_first_handoff_tutorial(self, player_id: int) -> bool:\n        with self.db.connect() as conn:\n            return conn.execute(\n                \"SELECT 1 FROM retail_allocations WHERE player_id=? LIMIT 1\",\n                (player_id,),\n            ).fetchone() is None\n\n    def _task_status",
)

nav = APP / "ui_navigation.py"
replace(nav, "from .ui_common import clean, money, notice, present, signed_pct_change", "from .ui_common import clean, money, notice, present, signed_pct_change, tutorial_hint")
replace(
    nav,
    "    elif ready_batch:\n        next_step = \"→ Партия получена. Передай товар закладчику.\"",
    "    elif ready_batch and game.needs_first_handoff_tutorial(player_id):\n        next_step = tutorial_hint(\"Стафф уже на складе!\\nНажми на кнопку 📦 Товар\")",
)

commerce = APP / "ui_commerce.py"
replace(commerce, "from .ui_common import claim_tip, clean, money, nav_row, notice, present, rating", "from .ui_common import claim_tip, clean, money, nav_row, notice, present, rating, tutorial_hint")
replace(commerce, 'rows.append([InlineKeyboardButton(text=f"Склад · {batch_count}", callback_data="team:batches")])', 'rows.append([InlineKeyboardButton(text=f"🚚 Склад · {batch_count}", callback_data="team:batches")])')
replace(
    commerce,
    '    body = f"<b>📦 Товар</b>\\n\\nСвободно: <b>{money(free_cash)}</b>"\n    await present(target, notice(flash, body), _procurement_products_keyboard(db, player_id, products))',
    '    body = f"<b>📦 Товар</b>\\n\\nСвободно: <b>{money(free_cash)}</b>"\n    if game.needs_first_handoff_tutorial(player_id):\n        body += "\\n\\n" + tutorial_hint("Нажми на кнопку 🚚 Склад")\n    await present(target, notice(flash, body), _procurement_products_keyboard(db, player_id, products))',
)

staff = APP / "ui_staff.py"
replace(staff, "from .ui_common import claim_tip, clean, money, nav_row, notice, pct, present, rating", "from .ui_common import claim_tip, clean, money, nav_row, notice, pct, present, rating, tutorial_hint")
replace(
    staff,
    '    body = f"<b>📦 Склад · {len(rows)}</b>"\n    if not rows:\n        body += "\\n\\nНа складе нет активных партий."',
    '    body = f"<b>🚚 Склад · {len(rows)}</b>"\n    if not rows:\n        body += "\\n\\nНа складе нет активных партий."\n    elif employee_id is None and game.needs_first_handoff_tutorial(player_id):\n        body += "\\n\\n" + tutorial_hint("Выбери партию стаффа, которую хочешь передать закладчику.")',
)
replace(
    staff,
    '    if quantity <= 0:\n        text += "\\n\\nСвободного залога недостаточно даже для 5 ед. Можно выбрать количество вручную, если готов оставить часть товара непокрытой."\n    else:\n        text += f"\\n🔴 Не покрыто депозитом: {money(unsecured)}" if unsecured else "\\n🟢 Полностью покрыто депозитом."\n    await present(target, text, InlineKeyboardMarkup(inline_keyboard=rows))',
    '    if quantity <= 0:\n        text += "\\n\\nСвободного залога недостаточно даже для 5 ед. Можно выбрать количество вручную, если готов оставить часть товара непокрытой."\n    else:\n        text += f"\\n🔴 Не покрыто депозитом: {money(unsecured)}" if unsecured else "\\n🟢 Полностью покрыто депозитом."\n    if game.needs_first_handoff_tutorial(player_id):\n        if quantity > 0:\n            text += "\\n\\n" + tutorial_hint(f"Проверь количество и нажми кнопку «Передать {quantity} ед.».")\n        else:\n            text += "\\n\\n" + tutorial_hint("Выбери количество от 5 ед. или вернись и выбери другого закладчика.")\n    await present(target, text, InlineKeyboardMarkup(inline_keyboard=rows))',
)

handlers = APP / "ui_staff_handlers.py"
replace(handlers, "from .ui_common import clean, money, nav_row, notice, pct, present", "from .ui_common import clean, money, nav_row, notice, pct, present, tutorial_hint")
replace(handlers, '    rows: list[list[InlineKeyboardButton]] = []\n    if not responsible:', '    rows: list[list[InlineKeyboardButton]] = []\n    tutorial = game.needs_first_handoff_tutorial(player_id)\n    if not responsible:')
replace(handlers, '        text += "\\n\\n🔴 Сначала назначь складмена."', '        text += "\\n\\n🔴 Сначала назначь складмена."\n        if tutorial:\n            text += "\\n\\n" + tutorial_hint("Назначь складмена на эту партию.")')
replace(handlers, '    elif batch["status"] == "warehouse":\n        text += "\\n\\nКому передать?"', '    elif batch["status"] == "warehouse":\n        text += "\\n\\nКому передать?"\n        if tutorial:\n            text += "\\n\\n" + tutorial_hint("Выбери закладчика, которому передашь стафф.")')
replace(handlers, '    rows.append(nav_row("team:batches", "← Склад"))', '    if tutorial and responsible and batch["status"] == "receiving":\n        text += "\\n\\n" + tutorial_hint("Складмен ещё получает партию. Вернись сюда, когда она будет готова.")\n    rows.append(nav_row("team:batches", "← Склад"))')

ux = TESTS / "test_ux_clarity.py"
text = ux.read_text(encoding="utf-8")
text = text.replace("import random\n", "import asyncio\nimport random\n")
text = text.replace("from app.ui_navigation import _home_snapshot, home_keyboard\n", "from app.ui_commerce import render_product_root\nfrom app.ui_navigation import _home_snapshot, home_keyboard\nfrom app.ui_staff import render_allocation, render_batches\nfrom app.ui_staff_handlers import render_batch\n")
text = text.replace('    assert "Передай товар закладчику" in text\n', '    assert "Передай товар закладчику" not in text\n    assert "<blockquote>Стафф уже на складе!\\nНажми на кнопку 📦 Товар</blockquote>" in text\n')
insert = '''\n\nclass Target:\n    def __init__(self):\n        self.text = None\n        self.reply_markup = None\n        self.photo = None\n\n    async def edit_text(self, text, **kwargs):\n        self.text = text\n        self.reply_markup = kwargs.get("reply_markup")\n\n    async def answer(self, text, **kwargs):\n        self.text = text\n        self.reply_markup = kwargs.get("reply_markup")\n\n    async def delete(self):\n        return None\n\n    async def answer_photo(self, photo, caption=None, **kwargs):\n        self.text = caption\n        self.reply_markup = kwargs.get("reply_markup")\n'''
text = text.replace("\ndef button_texts(markup):", insert + "\n\ndef button_texts(markup):")
text += '''\n\ndef test_first_handoff_tutorial_guides_product_warehouse_and_batch(tmp_path):\n    db, _, game, _ = make_system(tmp_path)\n    assert game.needs_first_handoff_tutorial(PLAYER_ID) is True\n    target = Target()\n    asyncio.run(render_product_root(target, db, game, PLAYER_ID))\n    assert "<blockquote>Нажми на кнопку 🚚 Склад</blockquote>" in target.text\n    assert any("🚚 Склад" in label for label in button_texts(target.reply_markup))\n    asyncio.run(render_batches(target, game, PLAYER_ID))\n    assert "<blockquote>Выбери партию стаффа, которую хочешь передать закладчику.</blockquote>" in target.text\n    with db.connect() as conn:\n        batch = conn.execute("SELECT id FROM batches WHERE player_id=? AND status='warehouse' AND remaining>0 ORDER BY id LIMIT 1", (PLAYER_ID,)).fetchone()\n    assert batch\n    batch_id = int(batch["id"])\n    asyncio.run(render_batch(target, game, PLAYER_ID, batch_id))\n    assert "<blockquote>Выбери закладчика, которому передашь стафф.</blockquote>" in target.text\n    _, staff = game.retail_staff_for_batch(PLAYER_ID, batch_id)\n    recipient = max(staff, key=lambda row: int(row["recommended_quantity"]))\n    quantity = int(recipient["recommended_quantity"])\n    assert quantity > 0\n    asyncio.run(render_allocation(target, game, PLAYER_ID, batch_id, int(recipient["id"]), quantity))\n    assert f"<blockquote>Проверь количество и нажми кнопку «Передать {quantity} ед.».</blockquote>" in target.text\n\n\ndef test_first_handoff_tutorial_disappears_after_transfer(tmp_path):\n    db, simulation, game, _ = make_system(tmp_path)\n    with db.connect() as conn:\n        batch = conn.execute("SELECT id FROM batches WHERE player_id=? AND status='warehouse' AND remaining>=5 ORDER BY id LIMIT 1", (PLAYER_ID,)).fetchone()\n        courier = conn.execute("SELECT id FROM employees WHERE player_id=? AND role='courier' AND active=1 ORDER BY deposit DESC LIMIT 1", (PLAYER_ID,)).fetchone()\n    assert batch and courier\n    result = game.allocate_to_retail(PLAYER_ID, int(batch["id"]), int(courier["id"]), 5)\n    assert "Назначено" in result\n    assert game.needs_first_handoff_tutorial(PLAYER_ID) is False\n    home, _, _ = _home_snapshot(db, game, simulation, PLAYER_ID)\n    assert "Стафф уже на складе!" not in home\n    target = Target()\n    asyncio.run(render_product_root(target, db, game, PLAYER_ID))\n    assert "Нажми на кнопку 🚚 Склад" not in target.text\n    asyncio.run(render_batches(target, game, PLAYER_ID))\n    assert "Выбери партию стаффа" not in target.text\n'''
ux.write_text(text, encoding="utf-8")

scenarios = TESTS / "test_ui_scenarios.py"
replace(
    scenarios,
    "    def __init__(self):\n        self.text = None\n        self.markup = None\n",
    "    def __init__(self):\n        self.text = None\n        self.markup = None\n        self.photo = None\n",
)
replace(
    scenarios,
    "    async def answer(self, text, reply_markup=None):\n        self.text = text\n        self.markup = reply_markup\n",
    "    async def answer(self, text, reply_markup=None):\n        self.text = text\n        self.markup = reply_markup\n\n    async def delete(self):\n        return None\n\n    async def answer_photo(self, photo, caption=None, reply_markup=None, **kwargs):\n        self.text = caption\n        self.markup = reply_markup\n",
)

print("first handoff tutorial applied")
