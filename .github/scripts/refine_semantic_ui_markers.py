from pathlib import Path
import re

ROOT = Path('shadow_market_simulator')
APP = ROOT / 'app'
TESTS = ROOT / 'tests'


def patch(path: Path, replacements: list[tuple[str, str]]) -> None:
    text = path.read_text(encoding='utf-8')
    for old, new in replacements:
        text = text.replace(old, new)
    path.write_text(text, encoding='utf-8')


# Emoji are semantic markers, not decoration. Keep them for stable sections,
# navigation and gameplay entities; keep local numeric controls compact.
patch(APP / 'ui_commerce.py', [
    ('InlineKeyboardButton(text="➖ 5%",', 'InlineKeyboardButton(text="−5%",'),
    ('InlineKeyboardButton(text="➕ 5%",', 'InlineKeyboardButton(text="+5%",'),
    ('InlineKeyboardButton(text=f"➖ ×{size} · 10",', 'InlineKeyboardButton(text=f"×{size} −10",'),
    ('InlineKeyboardButton(text=f"➕ ×{size} · 10",', 'InlineKeyboardButton(text=f"×{size} +10",'),
])

patch(APP / 'ui_staff.py', [
    ('InlineKeyboardButton(text="➖ 5",', 'InlineKeyboardButton(text="−5",'),
    ('InlineKeyboardButton(text="➕ 5",', 'InlineKeyboardButton(text="+5",'),
    ('text=("✅ " if int(snapshot["deposit_pct"]) == value else "⚪ ") + f"{value}%"', 'text=("✓ " if int(snapshot["deposit_pct"]) == value else "") + f"{value}%"'),
    ('text=("✅ " if int(snapshot["deposit_target"]) == value else "⚪ ") + money(value)', 'text=("✓ " if int(snapshot["deposit_target"]) == value else "") + money(value)'),
    ('InlineKeyboardButton(text="✏️ Переименовать",', 'InlineKeyboardButton(text="Переименовать",'),
    ('InlineKeyboardButton(text="🔄 Сменить роль",', 'InlineKeyboardButton(text="Сменить роль",'),
    ('InlineKeyboardButton(text="🗑️ Уволить",', 'InlineKeyboardButton(text="Уволить",'),
    ('InlineKeyboardButton(text="➖ Фикс 50",', 'InlineKeyboardButton(text="Фикс −50",'),
    ('InlineKeyboardButton(text="➕ Фикс 50",', 'InlineKeyboardButton(text="Фикс +50",'),
    ('InlineKeyboardButton(text="➖ Продажа 0,5%",', 'InlineKeyboardButton(text="Продажа −0,5%",'),
    ('InlineKeyboardButton(text="➕ Продажа 0,5%",', 'InlineKeyboardButton(text="Продажа +0,5%",'),
    ('InlineKeyboardButton(text="➖ Передача 0,5%",', 'InlineKeyboardButton(text="Передача −0,5%",'),
    ('InlineKeyboardButton(text="➕ Передача 0,5%",', 'InlineKeyboardButton(text="Передача +0,5%",'),
    ('InlineKeyboardButton(text="➖ Риск 0,5%",', 'InlineKeyboardButton(text="Риск −0,5%",'),
    ('InlineKeyboardButton(text="➕ Риск 0,5%",', 'InlineKeyboardButton(text="Риск +0,5%",'),
    ('InlineKeyboardButton(text="➖ Депозит 5%",', 'InlineKeyboardButton(text="Депозит −5%",'),
    ('InlineKeyboardButton(text="➕ Депозит 5%",', 'InlineKeyboardButton(text="Депозит +5%",'),
    ('InlineKeyboardButton(text=f"➖ Депозит {money(deposit_step)}",', 'InlineKeyboardButton(text=f"Депозит −{money(deposit_step)}",'),
    ('InlineKeyboardButton(text=f"➕ Депозит {money(deposit_step)}",', 'InlineKeyboardButton(text=f"Депозит +{money(deposit_step)}",'),
    ('InlineKeyboardButton(text="🎓 Опыт: Обязателен" if draft["experience_required"] else "🎓 Опыт: Не важен",', 'InlineKeyboardButton(text="Опыт: Обязателен" if draft["experience_required"] else "Опыт: Не важен",'),
    ('InlineKeyboardButton(text=f"🚗 Транспорт: {transport_labels[int(draft[\'transport_required\'])]}",', 'InlineKeyboardButton(text=f"Транспорт: {transport_labels[int(draft[\'transport_required\'])]}",'),
    ('InlineKeyboardButton(text=f"📣 Охват: {coverage_labels[int(draft[\'traffic_multiplier\'])]}",', 'InlineKeyboardButton(text=f"Охват: {coverage_labels[int(draft[\'traffic_multiplier\'])]}",'),
    (' + f"⏱ {value} ч", callback_data=f"recruit:set:duration_hours:{value}")', ' + f"{value} ч", callback_data=f"recruit:set:duration_hours:{value}")'),
    ('InlineKeyboardButton(text=f"▶️ Запустить · {money(quote[\'cost\'])}",', 'InlineKeyboardButton(text=f"Запустить · {money(quote[\'cost\'])}",'),
])

patch(APP / 'ui_admin.py', [
    ('text="⏩ +6 игровых часов"', 'text="+6 игровых часов"'),
    ('text=("✅ " if abs(current - 1) < 0.001 else "⚪ ") + "×1"', 'text=("✓ " if abs(current - 1) < 0.001 else "") + "×1"'),
    ('text=("✅ " if abs(current - 15) < 0.001 else "⚪ ") + "×15"', 'text=("✓ " if abs(current - 15) < 0.001 else "") + "×15"'),
    ('text=("✅ " if abs(current - 30) < 0.001 else "⚪ ") + "×30"', 'text=("✓ " if abs(current - 30) < 0.001 else "") + "×30"'),
    ('text=("✅ " if abs(current - 60) < 0.001 else "⚪ ") + "×60"', 'text=("✓ " if abs(current - 60) < 0.001 else "") + "×60"'),
    ('text="🗑️ Сбросить игру"', 'text="Сбросить игру"'),
])

# Analytics view buttons are stable navigation destinations, so keep their
# semantic icons. Period selectors are local controls and stay compact.
patch(APP / 'analytics' / 'analytics_handlers.py', [
    ('text=("✅ " if view == key else "⚪ ") + label', 'text=("✓ " if view == key else "") + label'),
    ('text=("✅ " if period == "7" else "⚪ ") + "7 дней"', 'text=("✓ " if period == "7" else "") + "7 дней"'),
    ('text=("✅ " if period == "30" else "⚪ ") + "30 дней"', 'text=("✓ " if period == "30" else "") + "30 дней"'),
])

# Dispute itself is an entity/navigation destination. Its one-off actions do
# not need decorative markers beyond the already meaningful money/source icons.
patch(APP / 'ui_disputes.py', [
    ('text="💬 Запросить пояснение"', 'text="Запросить пояснение"'),
    ('text="❌ Отказать"', 'text="Отказать"'),
])

# Inbox uses one status/entity marker per row, not stacked markers.
path = APP / 'ui_navigation.py'
text = path.read_text(encoding='utf-8')
text = text.replace('marker = "🔴 " if item["priority"] == "urgent" else "🟡 " if item["priority"] == "important" else "⚪ "', 'marker = "🔴 " if item["priority"] == "urgent" else "🟡 " if item["priority"] == "important" else "📨 "')
text = text.replace('text=f"📨 {marker}{str(item[\'title\'])[:48]}"', 'text=f"{marker}{str(item[\'title\'])[:48]}"')
path.write_text(text, encoding='utf-8')

# Tutorial duplicates the listing controls: keep entity markers, remove
# decorative +/- emojis from the utility controls.
patch(APP / 'tutorial' / 'hooks.py', [
    ("InlineKeyboardButton(text='➖ 5%'", "InlineKeyboardButton(text='−5%'"),
    ("InlineKeyboardButton(text='➕ 5%'", "InlineKeyboardButton(text='+5%'"),
])

# Replace the over-broad "every button must have emoji" guardrail. The durable
# rule is: canonical navigation cannot be reinvented, and gameplay entities /
# role transitions must retain their semantic markers.
path = TESTS / 'test_ui_vocabulary.py'
text = path.read_text(encoding='utf-8')
marker = '\nVISUAL_MARKERS = ('
if marker in text:
    text = text.split(marker, 1)[0].rstrip() + '\n'
text += '''\n\ndef test_gameplay_entity_buttons_keep_semantic_markers() -> None:\n    commerce = (APP / "ui_commerce.py").read_text(encoding="utf-8")\n    staff = (APP / "ui_staff.py").read_text(encoding="utf-8")\n    staff_handlers = (APP / "ui_staff_handlers.py").read_text(encoding="utf-8")\n    disputes = (APP / "ui_disputes.py").read_text(encoding="utf-8")\n\n    assert 'text=f"📦 {text}"' in commerce\n    assert 'text=f"🚚 {employee[\\'alias\\']}{suffix}"' in commerce\n    assert 'text=f"📦 {batch[\\'product_title\\']} · {batch[\\'remaining\\']} ед. · 🚚 {batch[\\'employee_alias\\']} · {state}"' in staff\n    assert 'text=f"Сменить на {role_label(new_role)}"' in staff_handlers\n    assert 'nav_row(f"dispute:view:{dispute_id}:{page}", "⚖️ Диспут")' in disputes\n\n\ndef test_local_numeric_controls_do_not_require_decorative_emoji() -> None:\n    commerce = (APP / "ui_commerce.py").read_text(encoding="utf-8")\n    staff = (APP / "ui_staff.py").read_text(encoding="utf-8")\n    assert 'text="−5%"' in commerce\n    assert 'text="+5%"' in commerce\n    assert 'text="−5"' in staff\n    assert 'text="+5"' in staff\n'''
path.write_text(text, encoding='utf-8')

# Expectations follow the semantic-marker policy, not the earlier blanket rule.
patch(TESTS / 'test_analytics_navigation.py', [
    ('assert "✅ 📊 Обзор" in names', 'assert "✓ 📊 Обзор" in names'),
    ('assert "⚪ 📦 Товары" in names', 'assert "📦 Товары" in names'),
    ('assert "⚪ 💰 Деньги" in names', 'assert "💰 Деньги" in names'),
    ('assert "✅ 7 дней" in names', 'assert "✓ 7 дней" in names'),
    ('assert "⚪ 30 дней" in names', 'assert "30 дней" in names'),
])
patch(TESTS / 'test_compact_ui.py', [
    ('        "📨 🔴 Срочное событие",\n        "📨 ⚪ Обычное событие",', '        "🔴 Срочное событие",\n        "📨 Обычное событие",'),
    ('assert more[:3] == ["✏️ Переименовать", "🔄 Сменить роль", "🗑️ Уволить"]', 'assert more[:3] == ["Переименовать", "Сменить роль", "Уволить"]'),
    ('        "✅ 📊 Обзор",\n        "⚪ 📦 Товары",\n        "⚪ 💰 Деньги",\n        "✅ 7 дней",\n        "⚪ 30 дней",', '        "✓ 📊 Обзор",\n        "📦 Товары",\n        "💰 Деньги",\n        "✓ 7 дней",\n        "30 дней",'),
])
patch(TESTS / 'test_ux_clarity.py', [
    ('assert allocation_rows[0] == ["➖ 5", f"📦 {quantity} ед.", "➕ 5"]', 'assert allocation_rows[0] == ["−5", f"📦 {quantity} ед.", "+5"]'),
])

# Explicit screen contract requested by the product owner.
role_test = TESTS / 'test_role_change_presentation.py'
if role_test.exists():
    text = role_test.read_text(encoding='utf-8')
    if 'employee_html' not in text:
        text += '\n'
    role_test.write_text(text, encoding='utf-8')

print('semantic UI marker policy applied')
