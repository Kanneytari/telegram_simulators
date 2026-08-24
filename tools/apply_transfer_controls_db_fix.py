from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"
TESTS = ROOT / "shadow_market_simulator" / "tests"


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"{path}: missing fragment {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


# Make repeated startup safe without introducing migrations.
db = APP / "db.py"
replace(db, "import sqlite3\n", "import re\nimport sqlite3\n")
replace(
    db,
    '        schema = SCHEMA_PATH.read_text(encoding="utf-8")\n        with self.connect() as conn:\n            conn.executescript(schema)',
    '        schema = SCHEMA_PATH.read_text(encoding="utf-8")\n        schema = re.sub(\n            r"CREATE (TABLE|INDEX|TRIGGER) (?!IF NOT EXISTS)",\n            r"CREATE \\1 IF NOT EXISTS ",\n            schema,\n        )\n        with self.connect() as conn:\n            conn.executescript(schema)',
)

# Main menu refresh icon.
nav = APP / "ui_navigation.py"
replace(
    nav,
    'rows.append([InlineKeyboardButton(text="Обновить", callback_data="menu:home")])',
    'rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:home")])',
)

# Product root no longer needs its own refresh button.
commerce = APP / "ui_commerce.py"
replace(
    commerce,
    '    rows.append([\n        InlineKeyboardButton(text="Обновить", callback_data="menu:product"),\n        InlineKeyboardButton(text="Меню", callback_data="menu:home"),\n    ])',
    '    rows.append([InlineKeyboardButton(text="Меню", callback_data="menu:home")])',
)

# Compact allocation controls: minus / selected amount / plus, then one confirm button.
staff = APP / "ui_staff.py"
replace(
    staff,
    '''    presets = sorted({min(int(batch["remaining"]), value) for value in (10, 20, 30) if value <= int(batch["remaining"])})\n    rows: list[list[InlineKeyboardButton]] = []\n    if presets:\n        rows.append([InlineKeyboardButton(\n            text=("✓ " if value == quantity else "") + str(value),\n            callback_data=f"team:alloc:{batch_id}:{employee_id}:{value}",\n        ) for value in presets])\n    rows.append([\n        InlineKeyboardButton(text="−5", callback_data=f"team:alloc:{batch_id}:{employee_id}:{max(0, quantity-5)}"),\n        InlineKeyboardButton(text="+5", callback_data=f"team:alloc:{batch_id}:{employee_id}:{min(int(batch['remaining']), quantity+5)}"),\n    ])\n    if quantity != int(batch["remaining"]):\n        rows.append([InlineKeyboardButton(text=f"Всё · {batch['remaining']} ед.", callback_data=f"team:alloc:{batch_id}:{employee_id}:{batch['remaining']}")])\n    if quantity > 0:\n        rows.append([InlineKeyboardButton(text=f"Передать {quantity} ед.", callback_data=f"team:allocdo:{batch_id}:{employee_id}:{quantity}")])\n    rows.append(nav_row(f"team:batch:{batch_id}", "← Партия"))''',
    '''    rows: list[list[InlineKeyboardButton]] = [[\n        InlineKeyboardButton(text="−5", callback_data=f"team:alloc:{batch_id}:{employee_id}:{max(0, quantity-5)}"),\n        InlineKeyboardButton(text=f"📦 {quantity} ед.", callback_data=f"team:alloc:{batch_id}:{employee_id}:{quantity}"),\n        InlineKeyboardButton(text="+5", callback_data=f"team:alloc:{batch_id}:{employee_id}:{min(int(batch['remaining']), quantity+5)}"),\n    ]]\n    if quantity > 0:\n        rows.append([InlineKeyboardButton(text=f"✅ Отправить {quantity} ед.", callback_data=f"team:allocdo:{batch_id}:{employee_id}:{quantity}")])\n    rows.append(nav_row(f"team:batch:{batch_id}", "← Назад"))''',
)
replace(
    staff,
    'tutorial_hint(f"Проверь количество и нажми кнопку «Передать {quantity} ед.».")',
    'tutorial_hint(f"Проверь количество и нажми кнопку «✅ Отправить {quantity} ед.».")',
)

# UX regression coverage.
ux = TESTS / "test_ux_clarity.py"
text = ux.read_text(encoding="utf-8")
text = text.replace(
    '    assert "🏷 Витрина" in labels\n',
    '    assert "🏷 Витрина" in labels\n    assert "🔄 Обновить" in labels\n',
)
text = text.replace(
    '    assert any("🚚 Склад" in label for label in button_texts(target.reply_markup))\n',
    '    product_labels = button_texts(target.reply_markup)\n    assert any("🚚 Склад" in label for label in product_labels)\n    assert not any("Обновить" in label for label in product_labels)\n',
)
text = text.replace(
    '    assert f"<blockquote>Проверь количество и нажми кнопку «Передать {quantity} ед.».</blockquote>" in target.text\n',
    '    assert f"<blockquote>Проверь количество и нажми кнопку «✅ Отправить {quantity} ед.».</blockquote>" in target.text\n    allocation_rows = [[button.text for button in row] for row in target.reply_markup.inline_keyboard]\n    assert allocation_rows[0] == ["−5", f"📦 {quantity} ед.", "+5"]\n    assert allocation_rows[1] == [f"✅ Отправить {quantity} ед."]\n    assert allocation_rows[-1] == ["← Назад", "Меню"]\n    assert not any("Всё" in label for row in allocation_rows for label in row)\n',
)
ux.write_text(text, encoding="utf-8")

compact = TESTS / "test_compact_ui.py"
replace(compact, '        "Обновить",\n', '        "🔄 Обновить",\n')

(TESTS / "test_db_init.py").write_text(
    '''from app.db import Database\n\n\ndef test_database_init_can_run_twice_without_losing_data(tmp_path):\n    db = Database(str(tmp_path / "repeat.db"))\n    db.init()\n    with db.connect() as conn:\n        conn.execute("INSERT INTO shops(player_id, username) VALUES (?, ?)", (42, "repeat"))\n\n    db.init()\n\n    with db.connect() as conn:\n        shop = conn.execute("SELECT username FROM shops WHERE player_id=42").fetchone()\n        analytics_table = conn.execute(\n            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='analytics_events'"\n        ).fetchone()\n    assert shop["username"] == "repeat"\n    assert analytics_table is not None\n''',
    encoding="utf-8",
)

print("transfer controls and db init fix applied")
