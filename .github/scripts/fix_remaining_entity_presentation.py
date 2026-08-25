from pathlib import Path

ROOT = Path('shadow_market_simulator')
APP = ROOT / 'app'
TESTS = ROOT / 'tests'


def patch(path: Path, replacements: list[tuple[str, str]]) -> None:
    text = path.read_text(encoding='utf-8')
    for old, new in replacements:
        text = text.replace(old, new)
    path.write_text(text, encoding='utf-8')


# Commerce: every product/offer/listing/quantity action gets a visual marker.
patch(APP / 'ui_commerce.py', [
    ('text = str(product["title"])', 'text = f"📦 {product[\'title\']}"'),
    ('text=f"Купить · {money(int(selected[\'required\']))}"', 'text=f"🛒 Купить · {money(int(selected[\'required\']))}"'),
    ('text="Сменить складмена"', 'text="🚚 Сменить складмена"'),
    ('text="Нанять сотрудника"', 'text="🔎 Нанять сотрудника"'),
    ('nav_row(f"proc:product:{product_id}", "Предложения")', 'nav_row(f"proc:product:{product_id}", "🛒 Предложения")'),
    ('text=f"{employee[\'alias\']}{suffix}"', 'text=f"🚚 {employee[\'alias\']}{suffix}"'),
    ('nav_row(f"proc:offer:{offer_id}", "Предложение")', 'nav_row(f"proc:offer:{offer_id}", "🛒 Предложение")'),
    ('text=f"×{listing[\'pack_size\']} · {money(listing[\'price\'])} · доступно {int(listing[\'positions\'])}"', 'text=f"🏷 ×{listing[\'pack_size\']} · {money(listing[\'price\'])} · доступно {int(listing[\'positions\'])}"'),
    ('InlineKeyboardButton(text="−5%",', 'InlineKeyboardButton(text="➖ 5%",'),
    ('InlineKeyboardButton(text="+5%",', 'InlineKeyboardButton(text="➕ 5%",'),
    ('nav_row(f"sales:product:{row[\'product_id\']}", f"{str(row[\'title\'])[:18]}")', 'nav_row(f"sales:product:{row[\'product_id\']}", f"📦 {str(row[\'title\'])[:18]}")'),
    ('InlineKeyboardButton(text=f"×{size} −10",', 'InlineKeyboardButton(text=f"➖ ×{size} · 10",'),
    ('InlineKeyboardButton(text=f"×{size} +10",', 'InlineKeyboardButton(text=f"➕ ×{size} · 10",'),
    ('text += f"\\n\\nСкладмен: <b>{clean(selected[\'alias\'])}</b>"', 'text += f"\\n\\n{role_html(\'warehouse\', capitalize=True)}: {employee_html(selected[\'alias\'], \'warehouse\')}"'),
    ('text += "\\n\\n🔴 Нет активного складмена."', 'text += f"\\n\\n🔴 Нет активного {role_html(\'warehouse\', form=\'складмена\')}."'),
    ('f"<b>Складмен для закупки</b>\\n\\n{clean(offer[\'product_title\'])} · {money(int(offer[\'quantity\'] * offer[\'unit_cost\']))}"', 'f"<b>Выбор сотрудника</b> · {role_html(\'warehouse\', capitalize=True)}\\n\\n{product_html(offer[\'product_title\'])} · {money(int(offer[\'quantity\'] * offer[\'unit_cost\']))}"'),
    ('f"<b>{clean(offer[\'product_title\'])} · {offer[\'quantity\']} ед.</b>\\n\\n"', 'f"📦 <b>{clean(offer[\'product_title\'])} · {offer[\'quantity\']} ед.</b>\\n\\n"'),
])
# Ensure commerce has entity helpers used by the new strings.
path = APP / 'ui_commerce.py'
text = path.read_text(encoding='utf-8')
if 'from app.presentation.entities import employee_html, product_html, role_html' not in text:
    if 'from app.presentation.entities import product_html' in text:
        text = text.replace('from app.presentation.entities import product_html', 'from app.presentation.entities import employee_html, product_html, role_html')
    else:
        lines = text.splitlines()
        lines.insert(2, 'from app.presentation.entities import employee_html, product_html, role_html')
        text = '\n'.join(lines) + ('\n' if text.endswith('\n') else '')
path.write_text(text, encoding='utf-8')

# Staff: selectors, secondary actions and batch entities.
patch(APP / 'ui_staff.py', [
    ('text=("✓ " if int(snapshot["deposit_pct"]) == value else "") + f"{value}%"', 'text=("✅ " if int(snapshot["deposit_pct"]) == value else "⚪ ") + f"{value}%"'),
    ('text=("✓ " if int(snapshot["deposit_target"]) == value else "") + money(value)', 'text=("✅ " if int(snapshot["deposit_target"]) == value else "⚪ ") + money(value)'),
    ('nav_row(f"team:development:{employee_id}", "Развитие", menu=False)', 'nav_row(f"team:development:{employee_id}", "📈 Развитие", menu=False)'),
    ('text="Переименовать"', 'text="✏️ Переименовать"'),
    ('text="Сменить роль"', 'text="🔄 Сменить роль"'),
    ('text="Уволить"', 'text="🗑️ Уволить"'),
    ('nav_row(f"team:employee:{employee_id}", "Профиль")', 'nav_row(f"team:employee:{employee_id}", "👤 Профиль")'),
    ('text=f"{batch[\'product_title\']} · {batch[\'remaining\']} ед. · {batch[\'employee_alias\']} · {state}"', 'text=f"📦 {batch[\'product_title\']} · {batch[\'remaining\']} ед. · 🚚 {batch[\'employee_alias\']} · {state}"'),
    ('back_text: str = "Товар"', 'back_text: str = "📦 Товар"'),
    ('f"<b>{clean(s[\'alias\'])} · ещё</b>"', 'f"{employee_html(s[\'alias\'], \'courier\')} · <b>Ещё</b>"'),
])

# Admin buttons.
patch(APP / 'ui_admin.py', [
    ('text="+6 игровых часов"', 'text="⏩ +6 игровых часов"'),
    ('text=("✓ " if abs(current - 1) < 0.001 else "") + "×1"', 'text=("✅ " if abs(current - 1) < 0.001 else "⚪ ") + "×1"'),
    ('text=("✓ " if abs(current - 15) < 0.001 else "") + "×15"', 'text=("✅ " if abs(current - 15) < 0.001 else "⚪ ") + "×15"'),
    ('text=("✓ " if abs(current - 30) < 0.001 else "") + "×30"', 'text=("✅ " if abs(current - 30) < 0.001 else "⚪ ") + "×30"'),
    ('text=("✓ " if abs(current - 60) < 0.001 else "") + "×60"', 'text=("✅ " if abs(current - 60) < 0.001 else "⚪ ") + "×60"'),
    ('text="Сбросить игру"', 'text="🗑️ Сбросить игру"'),
    ('text="Отмена"', 'text="↩️ Отмена"'),
])

# Disputes: actions and entity styling.
patch(APP / 'ui_disputes.py', [
    ('text="Запросить пояснение"', 'text="💬 Запросить пояснение"'),
    ('text="🚫 Отказать"', 'text="❌ Отказать"'),
    ('text="Со счёта магазина"', 'text="🏪 Со счёта магазина"'),
    ('text=f"Из депозита {context[\'employee_alias\']}"', 'text=f"💰 Из депозита {context[\'employee_alias\']}"'),
    ('nav_row(f"dispute:view:{dispute_id}:{page}", "Диспут")', 'nav_row(f"dispute:view:{dispute_id}:{page}", "⚖️ Диспут")'),
    ('f"Товар: {clean(row[\'product_title\'])} · оценка {product_rating}\\n"', 'f"Товар: {product_html(row[\'product_title\'])} · оценка {product_rating}\\n"'),
    ('f"Закладчик: {clean(row[\'employee_alias\'])} · оценка {courier_rating}"', 'f"{role_html(\'courier\', capitalize=True)}: {employee_html(row[\'employee_alias\'], \'courier\')} · оценка {courier_rating}"'),
    ('"<b>Пояснение закладчика</b>"', 'f"<b>Пояснение</b> · {role_html(\'courier\')}"'),
    ('"Пояснение закладчика не запрошено."', 'f"Пояснение {role_html(\'courier\', form=\'закладчика\')} не запрошено."'),
])
path = APP / 'ui_disputes.py'
text = path.read_text(encoding='utf-8')
if 'from app.presentation.entities import' not in text:
    text = text.replace('from app.presentation.vocabulary import INBOX, nav_row\n', 'from app.presentation.vocabulary import INBOX, nav_row\nfrom app.presentation.entities import employee_html, product_html, role_html\n')
path.write_text(text, encoding='utf-8')

# Inbox / navigation. Normal-priority rows now also carry a marker.
patch(APP / 'ui_navigation.py', [
    ('else ""\n        rows.append([', 'else "⚪ "\n        rows.append(['),
    ('text="Предыдущие"', 'text="⬅️ Предыдущие"'),
    ('text="Следующие"', 'text="➡️ Следующие"'),
    ('text="Разобрать"', 'text="⚖️ Разобрать"'),
    ('text="Кандидаты"', 'text="👥 Кандидаты"'),
    ('text="Согласиться"', 'text="✅ Согласиться"'),
    ('text="Отказать"', 'text="❌ Отказать"'),
    ('text="Профиль сотрудника"', 'text="👤 Профиль сотрудника"'),
    ('text="Закрыть"', 'text="❌ Закрыть"'),
    ('alerts.append(f"🟡 {clean(stressed[\'alias\'])} перегружен")', 'alerts.append(f"🟡 {employee_html(stressed[\'alias\'], \'courier\')} перегружен")'),
    ('alerts.append(f"🟡 {clean(item[\'title\'])}: запаса примерно', 'alerts.append(f"🟡 {product_html(item[\'title\'])}: запаса примерно'),
    ('"Закупай товар, распределяй его между сотрудниками, управляй витриной и разбирай проблемы.\\n\\n"', '"Закупай товар, распределяй его между сотрудниками, управляй витриной и разбирай проблемы.\\n\\n"'),
    ('"<b>Товар. Склад. Закладчики. Витрина. Продажи.</b>"', 'f"📦 <b>Товар</b> · 📦 <b>Склад</b> · {role_html(\'courier\', plural=True, capitalize=True)} · 🏷 <b>Витрина</b> · 💰 <b>Продажи</b>"'),
])
path = APP / 'ui_navigation.py'
text = path.read_text(encoding='utf-8')
if 'from app.presentation.entities import' not in text:
    text = text.replace('from app.presentation.vocabulary import ', 'from app.presentation.entities import employee_html, product_html, role_html\nfrom app.presentation.vocabulary import ', 1)
path.write_text(text, encoding='utf-8')

# Notifications: dynamic button variable is explicitly wrapped with an inbox marker.
patch(APP / 'bot' / 'notifications.py', [
    ('text = "Разобрать"', 'text = "⚖️ Разобрать"'),
    ('text = "Кандидаты"', 'text = "👥 Кандидаты"'),
    ('text = "Открыть"', 'text = "📂 Открыть"'),
    ('InlineKeyboardButton(text=text, callback_data=callback)', 'InlineKeyboardButton(text=f"📨 {text}", callback_data=callback)'),
])

# Analytics selectors/actions.
patch(APP / 'analytics' / 'analytics_handlers.py', [
    ('labels = (("overview", "Обзор"), ("products", "Товары"), ("finance", "Деньги"))', 'labels = (("overview", "📊 Обзор"), ("products", "📦 Товары"), ("finance", "💰 Деньги"))'),
    ('text=("✓ " if view == key else "") + label', 'text=("✅ " if view == key else "⚪ ") + label'),
    ('text=("✓ " if period == "7" else "") + "7 дней"', 'text=("✅ " if period == "7" else "⚪ ") + "7 дней"'),
    ('text=("✓ " if period == "30" else "") + "30 дней"', 'text=("✅ " if period == "30" else "⚪ ") + "30 дней"'),
    ('text="Выплаты"', 'text="💸 Выплаты"'),
    ('text="Деньги"', 'text="💰 Деньги"'),
])

# Tutorial-specific renderers duplicate a few runtime buttons intentionally; style them too.
patch(APP / 'tutorial' / 'hooks.py', [
    ('text=f"×{listing[\'pack_size\']} · {money(listing[\'price\'])} · доступно {int(listing[\'positions\'])}"', 'text=f"🏷 ×{listing[\'pack_size\']} · {money(listing[\'price\'])} · доступно {int(listing[\'positions\'])}"'),
    ("InlineKeyboardButton(text='−5%'", "InlineKeyboardButton(text='➖ 5%'"),
    ("InlineKeyboardButton(text='+5%'", "InlineKeyboardButton(text='➕ 5%'"),
    ('text=f"{str(row[\'title\'])[:18]}"', 'text=f"📦 {str(row[\'title\'])[:18]}"'),
])

# Guardrail recognizes variables that are themselves canonical label/icon outputs,
# and includes the remaining visual markers used by deliberate action semantics.
path = TESTS / 'test_ui_vocabulary.py'
text = path.read_text(encoding='utf-8')
text = text.replace('"🏠", "📦", "🤝", "🏷",', '"🏠", "📦", "🤝", "🏷", "➡️", "💵", "💬", "🏪", "💸",')
text = text.replace('if ".label" in source or ".icon" in source or "role_label(" in source:', 'if ".label" in source or ".icon" in source or "role_label(" in source or "role_icon" in source or source == "inbox":')
path.write_text(text, encoding='utf-8')

# Update old tests that intentionally pinned pre-emoji labels/copy.
patch(TESTS / 'test_compact_ui.py', [
    ('assert "Премия · 5 000 ₽" in profile', 'assert "💰 Премия · 5 000 ₽" in profile'),
    ('assert "Отдых" in profile', 'assert "🛌 Отдых" in profile'),
    ('assert "Развитие" in profile', 'assert "📈 Развитие" in profile'),
    ('assert "Ещё" in profile', 'assert "⚙️ Ещё" in profile'),
])
patch(TESTS / 'test_ui_scenarios.py', [
    ('assert "Развитие" in [button.text for row in target.markup.inline_keyboard for button in row]', 'assert "📈 Развитие" in [button.text for row in target.markup.inline_keyboard for button in row]'),
])
patch(TESTS / 'test_ux_clarity.py', [
    ('<blockquote>Выбери партию стаффа, которую хочешь передать закладчику.</blockquote>', '<blockquote>Выбери партию стаффа, которую хочешь передать 👤 <b>закладчику</b>.</blockquote>'),
])
patch(TESTS / 'test_zz_gameplay_updates.py', [
    ('assert f"Складмен: 🚚 {warehouse[\'alias\']}" in target.text', 'assert f"🚚 <b>Складмен</b>: 🚚 <b>{warehouse[\'alias\']}</b>" in target.text'),
])

print('remaining entity presentation cleanup applied')
