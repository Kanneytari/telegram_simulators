from pathlib import Path
import re

ROOT = Path('shadow_market_simulator')
APP = ROOT / 'app'
TESTS = ROOT / 'tests'

entities = APP / 'presentation' / 'entities.py'
entities.write_text('''from __future__ import annotations

from dataclasses import dataclass
from html import escape


@dataclass(frozen=True, slots=True)
class RoleStyle:
    icon: str
    singular: str
    plural: str


ROLE_STYLES = {
    "courier": RoleStyle("👤", "закладчик", "закладчики"),
    "warehouse": RoleStyle("🚚", "складмен", "складмены"),
}


def role_icon(role: str) -> str:
    return ROLE_STYLES[role].icon


def role_label(role: str, *, plural: bool = False, form: str | None = None, capitalize: bool = False) -> str:
    style = ROLE_STYLES[role]
    name = form if form is not None else (style.plural if plural else style.singular)
    if capitalize:
        name = name[:1].upper() + name[1:]
    return f"{style.icon} {name}"


def role_html(role: str, *, plural: bool = False, form: str | None = None, capitalize: bool = False) -> str:
    style = ROLE_STYLES[role]
    name = form if form is not None else (style.plural if plural else style.singular)
    if capitalize:
        name = name[:1].upper() + name[1:]
    return f"{style.icon} <b>{escape(name)}</b>"


def employee_html(alias: object, role: str) -> str:
    return f"{role_icon(role)} <b>{escape(str(alias or ''))}</b>"


def product_html(title: object) -> str:
    return f"📦 <b>{escape(str(title or ''))}</b>"


def batch_html(batch_id: int) -> str:
    return f"📦 <b>Партия #{int(batch_id)}</b>"
''', encoding='utf-8')

# --- ui_staff.py ----------------------------------------------------------
path = APP / 'ui_staff.py'
text = path.read_text(encoding='utf-8')
import_anchor = 'from app.presentation.vocabulary import HOME, PAYMENT, PRODUCT, RECRUIT, TEAM, button, nav_row\n'
if import_anchor in text and 'from app.presentation.entities import' not in text:
    text = text.replace(import_anchor, import_anchor + 'from app.presentation.entities import employee_html, role_html, role_label\n', 1)

text = text.replace('warnings.append(f"🟡 Перегружено закладчиков: {stressed}")', 'warnings.append(f"🟡 Перегружено {role_html(\'courier\', form=\'закладчиков\')}: {stressed}")')
text = text.replace('f"<b>👤 {clean(employee[\'alias\'])} · закладчик</b>\\n\\n"', 'f"{employee_html(employee[\'alias\'], \'courier\')} · {role_html(\'courier\')}\\n\\n"')
text = text.replace('f"<b>🚚 {clean(employee[\'alias\'])} · складмен</b>\\n\\n"', 'f"{employee_html(employee[\'alias\'], \'warehouse\')} · {role_html(\'warehouse\')}\\n\\n"')
text = text.replace('InlineKeyboardButton(text=f"Премия · {money(BONUS_COST)}",', 'InlineKeyboardButton(text=f"💰 Премия · {money(BONUS_COST)}",')
text = text.replace('InlineKeyboardButton(text="Отдых",', 'InlineKeyboardButton(text="🛌 Отдых",')
text = text.replace('InlineKeyboardButton(text="Развитие",', 'InlineKeyboardButton(text="📈 Развитие",')
text = text.replace('InlineKeyboardButton(text="Ещё",', 'InlineKeyboardButton(text="⚙️ Ещё",')
text = text.replace('InlineKeyboardButton(text=f"12 ч · {money(REST_OPTIONS[12][\'cost\'])}",', 'InlineKeyboardButton(text=f"🛌 12 ч · {money(REST_OPTIONS[12][\'cost\'])}",')
text = text.replace('InlineKeyboardButton(text=f"24 ч · {money(REST_OPTIONS[24][\'cost\'])}",', 'InlineKeyboardButton(text=f"🛌 24 ч · {money(REST_OPTIONS[24][\'cost\'])}",')
text = text.replace('nav_row(f"team:employee:{employee_id}", "Профиль", menu=False)', 'nav_row(f"team:employee:{employee_id}", "👤 Профиль", menu=False)')
text = text.replace('InlineKeyboardButton(text="Изменить депозит",', 'InlineKeyboardButton(text="💰 Изменить депозит",')
text = text.replace('InlineKeyboardButton(text=f"{title.capitalize()} · {money(cost)}",', 'InlineKeyboardButton(text=f"🚲 {title.capitalize()} · {money(cost)}",')
text = text.replace('InlineKeyboardButton(text=f"Телефон: {title} · {money(cost)}",', 'InlineKeyboardButton(text=f"📱 Телефон: {title} · {money(cost)}",')
text = text.replace('rows.append(nav_row(f"team:employee:{employee_id}", "Профиль"))', 'rows.append(nav_row(f"team:employee:{employee_id}", "👤 Профиль"))')
text = text.replace('nav_row(f"team:development:{employee_id}", "Развитие", menu=False)', 'nav_row(f"team:development:{employee_id}", "📈 Развитие", menu=False)')
text = text.replace('"Велосипед ускоряет работу закладчика."', 'f"Велосипед ускоряет работу {role_html(\'courier\', form=\'закладчика\')}."')
text = text.replace('"Автомобиль ещё сильнее ускоряет работу закладчика."', 'f"Автомобиль ещё сильнее ускоряет работу {role_html(\'courier\', form=\'закладчика\')}."')
text = text.replace('body = f"<b>🚚 Склад · {len(rows)}</b>"', 'body = f"<b>📦 Склад · {len(rows)}</b>"')
text = text.replace('tutorial_hint("Выбери партию стаффа, которую хочешь передать закладчику.")', 'tutorial_hint(f"Выбери партию стаффа, которую хочешь передать {role_html(\'courier\', form=\'закладчику\')}.")')
text = text.replace('InlineKeyboardButton(text="−5",', 'InlineKeyboardButton(text="➖ 5",')
text = text.replace('InlineKeyboardButton(text="+5",', 'InlineKeyboardButton(text="➕ 5",')
text = text.replace('rows.append(nav_row(f"team:batch:{batch_id}", "Назад"))', 'rows.append(nav_row(f"team:batch:{batch_id}", "⬅️ Назад"))')
text = text.replace('f"<b>Передать {clean(employee[\'alias\'])}</b>\\n\\n"', 'f"<b>Передать</b> · {employee_html(employee[\'alias\'], \'courier\')}\\n\\n"')
text = text.replace('tutorial_hint("Выбери количество от 5 ед. или вернись и выбери другого закладчика.")', 'tutorial_hint(f"Выбери количество от 5 ед. или вернись и выбери другого {role_html(\'courier\', form=\'закладчика\')}.")')
text = text.replace('rows.append([InlineKeyboardButton(text=f"{employee[\'alias\']}{suffix}",', 'rows.append([InlineKeyboardButton(text=f"🚚 {employee[\'alias\']}{suffix}",')
text = text.replace('rows.append(nav_row(f"team:batch:{batch_id}", "Партия"))', 'rows.append(nav_row(f"team:batch:{batch_id}", "📦 Партия"))')
text = text.replace('f"Закладчики\\n{_policy_line(\'courier\', retail)}\\n\\n"', 'f"{role_html(\'courier\', plural=True, capitalize=True)}\\n{_policy_line(\'courier\', retail)}\\n\\n"')
text = text.replace('f"Складмены\\n{_policy_line(\'warehouse\', wholesale)}"', 'f"{role_html(\'warehouse\', plural=True, capitalize=True)}\\n{_policy_line(\'warehouse\', wholesale)}"')
text = text.replace('InlineKeyboardButton(text="Закладчики", callback_data="team:terms:courier")', 'InlineKeyboardButton(text=role_label("courier", plural=True, capitalize=True), callback_data="team:terms:courier")')
text = text.replace('InlineKeyboardButton(text="Складмены", callback_data="team:terms:warehouse")', 'InlineKeyboardButton(text=role_label("warehouse", plural=True, capitalize=True), callback_data="team:terms:warehouse")')
text = text.replace('InlineKeyboardButton(text="Фикс −50",', 'InlineKeyboardButton(text="➖ Фикс 50",')
text = text.replace('InlineKeyboardButton(text="Фикс +50",', 'InlineKeyboardButton(text="➕ Фикс 50",')
text = text.replace('InlineKeyboardButton(text="Продажа −0,5%",', 'InlineKeyboardButton(text="➖ Продажа 0,5%",')
text = text.replace('InlineKeyboardButton(text="Продажа +0,5%",', 'InlineKeyboardButton(text="➕ Продажа 0,5%",')
text = text.replace('InlineKeyboardButton(text="Передача −0,5%",', 'InlineKeyboardButton(text="➖ Передача 0,5%",')
text = text.replace('InlineKeyboardButton(text="Передача +0,5%",', 'InlineKeyboardButton(text="➕ Передача 0,5%",')
text = text.replace('InlineKeyboardButton(text="Риск −0,5%",', 'InlineKeyboardButton(text="➖ Риск 0,5%",')
text = text.replace('InlineKeyboardButton(text="Риск +0,5%",', 'InlineKeyboardButton(text="➕ Риск 0,5%",')
text = text.replace('InlineKeyboardButton(text="Депозит −5%",', 'InlineKeyboardButton(text="➖ Депозит 5%",')
text = text.replace('InlineKeyboardButton(text="Депозит +5%",', 'InlineKeyboardButton(text="➕ Депозит 5%",')
text = text.replace('InlineKeyboardButton(text="Применить",', 'InlineKeyboardButton(text="✅ Применить",')
text = text.replace('InlineKeyboardButton(text="Отмена",', 'InlineKeyboardButton(text="↩️ Отмена",')
text = text.replace('InlineKeyboardButton(text=f"Кандидаты · {candidate_count}",', 'InlineKeyboardButton(text=f"👥 Кандидаты · {candidate_count}",')
text = text.replace('InlineKeyboardButton(text="Новый поиск",', 'InlineKeyboardButton(text="🔎 Новый поиск",')
text = text.replace('rows.append(nav_row("team:recruit", "Найм"))', 'rows.append(nav_row("team:recruit", "🔎 Найм"))')
text = text.replace('rows.append(nav_row("team:recruit:new", "Каналы"))', 'rows.append(nav_row("team:recruit:new", "📣 Каналы"))')
text = text.replace('role_label = "Закладчик" if role == "courier" else "Складмен"', 'role_label_text = role_label(role, capitalize=True)')
text = text.replace('text=f"Роль: {role_label}"', 'text=f"🔄 Роль: {role_label_text}"')
text = text.replace('InlineKeyboardButton(text=f"Депозит −{money(deposit_step)}",', 'InlineKeyboardButton(text=f"➖ Депозит {money(deposit_step)}",')
text = text.replace('InlineKeyboardButton(text=f"Депозит +{money(deposit_step)}",', 'InlineKeyboardButton(text=f"➕ Депозит {money(deposit_step)}",')
text = text.replace('InlineKeyboardButton(text="Опыт: Обязателен" if draft["experience_required"] else "Опыт: Не важен",', 'InlineKeyboardButton(text="🎓 Опыт: Обязателен" if draft["experience_required"] else "🎓 Опыт: Не важен",')
text = text.replace('InlineKeyboardButton(text=f"Транспорт: {transport_labels[int(draft[\'transport_required\'])]}",', 'InlineKeyboardButton(text=f"🚗 Транспорт: {transport_labels[int(draft[\'transport_required\'])]}",')
text = text.replace('InlineKeyboardButton(text=f"Охват: {coverage_labels[int(draft[\'traffic_multiplier\'])]}",', 'InlineKeyboardButton(text=f"📣 Охват: {coverage_labels[int(draft[\'traffic_multiplier\'])]}",')
text = text.replace(' + f"{value} ч", callback_data=f"recruit:set:duration_hours:{value}")', ' + f"⏱ {value} ч", callback_data=f"recruit:set:duration_hours:{value}")')
text = text.replace('InlineKeyboardButton(text=f"Запустить · {money(quote[\'cost\'])}",', 'InlineKeyboardButton(text=f"▶️ Запустить · {money(quote[\'cost\'])}",')
text = text.replace('role = "закладчик" if draft["role"] == "courier" else "складмен"', 'role = role_html(str(draft["role"]))')
path.write_text(text, encoding='utf-8')

# --- ui_staff_handlers.py -------------------------------------------------
path = APP / 'ui_staff_handlers.py'
text = path.read_text(encoding='utf-8')
if 'from app.presentation.entities import' not in text:
    text = text.replace('from app.presentation.vocabulary import HIRE, WAREHOUSE, button, nav_row\n', 'from app.presentation.vocabulary import HIRE, WAREHOUSE, button, nav_row\nfrom app.presentation.entities import employee_html, product_html, role_html, role_label\n', 1)
text = text.replace("f\"Складмен: 🚚 {clean(responsible['alias'])}\"", "f\"{role_html('warehouse', capitalize=True)}: {employee_html(responsible['alias'], 'warehouse')}\"")
text = text.replace('else "Складмен: не назначен"', 'else f"{role_html(\'warehouse\', capitalize=True)}: не назначен"')
text = text.replace('text += "\\n\\n🔴 Сначала назначь складмена."', 'text += f"\\n\\n🔴 Сначала назначь {role_html(\'warehouse\', form=\'складмена\')}."')
text = text.replace('tutorial_hint("Назначь складмена на эту партию.")', 'tutorial_hint(f"Назначь {role_html(\'warehouse\', form=\'складмена\')} на эту партию.")')
text = text.replace('text="Назначить складмена"', 'text="🚚 Назначить складмена"')
text = text.replace('text="Нанять сотрудника"', 'text="🔎 Нанять сотрудника"')
text = text.replace('tutorial_hint(\n                "Выбери закладчика, которому передашь стафф."\n            )', 'tutorial_hint(\n                f"Выбери {role_html(\'courier\', form=\'закладчика\')}, которому передашь стафф."\n            )')
text = text.replace('text="Сменить складмена"', 'text="🚚 Сменить складмена"')
text = text.replace('"Складмен ещё получает партию. Вернись сюда, когда она будет готова."', 'f"{role_html(\'warehouse\', capitalize=True)} ещё получает партию. Вернись сюда, когда она будет готова."')
text = text.replace("role = str(row[\"role\"]); role_text = \"закладчик\" if role == \"courier\" else \"складмен\"", "role = str(row[\"role\"]); role_text = role_html(role)")
text = text.replace("lines = [f\"<b>{'👤' if role == 'courier' else '🚚'} {clean(row['alias'])} · {role_text}</b>\",", "lines = [f\"{employee_html(row['alias'], role)} · {role_text}\",")
text = text.replace('InlineKeyboardButton(text="Отказать",', 'InlineKeyboardButton(text="❌ Отказать",')
text = text.replace('nav_row("team:candidates", "Кандидаты")', 'nav_row("team:candidates", "👥 Кандидаты")')
text = text.replace('InlineKeyboardButton(text="Новый поиск",', 'InlineKeyboardButton(text="🔎 Новый поиск",')
text = text.replace('nav_row("team:recruit", "Найм")', 'nav_row("team:recruit", "🔎 Найм")')
text = text.replace('InlineKeyboardButton(text=f"Купить · {money(cost)}",', 'InlineKeyboardButton(text=f"🛒 Купить · {money(cost)}",')
text = text.replace('InlineKeyboardButton(text="Отмена",', 'InlineKeyboardButton(text="↩️ Отмена",')
text = text.replace('f"{clean(snapshot[\'alias\'])} · {title}\\n"', 'f"{employee_html(snapshot[\'alias\'], \'courier\')} · <b>{clean(title)}</b>\\n"')
text = text.replace('f"<b>Переименовать {clean(employee[\'alias\'])}</b>\\n\\nОтправь новое имя. Максимум 24 символа."', 'f"<b>Переименовать</b> · 👤 <b>{clean(employee[\'alias\'])}</b>\\n\\nОтправь новое имя. Максимум 24 символа."')
text = text.replace('InlineKeyboardButton(text="Профиль",', 'InlineKeyboardButton(text="👤 Профиль",')
old_role = '''        current = "складмен" if employee["role"] == "warehouse" else "закладчик"
        new = "закладчик" if employee["role"] == "warehouse" else "складмен"
        await present(
            callback.message,
            f"<b>Сменить роль · {clean(employee['alias'])}</b>\\n\\nСейчас: {current}\\nНовая роль: <b>{new}</b>\\n\\nСмена возможна только без товара и активных задач.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"Сменить на {new}", callback_data=f"team:roleconfirm:{employee_id}")],
                [InlineKeyboardButton(text="↩️ Отмена", callback_data=f"team:more:{employee_id}")],
            ]),
        )'''
new_role = '''        current_role = str(employee["role"])
        new_role = "courier" if current_role == "warehouse" else "warehouse"
        await present(
            callback.message,
            f"<b>Сменить роль</b> · {employee_html(employee['alias'], current_role)}\\n\\n"
            f"Сейчас: {role_html(current_role)}\\n"
            f"Новая роль: {role_html(new_role)}\\n\\n"
            "Смена возможна только без товара и активных задач.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"Сменить на {role_label(new_role)}", callback_data=f"team:roleconfirm:{employee_id}")],
                [InlineKeyboardButton(text="↩️ Отмена", callback_data=f"team:more:{employee_id}")],
            ]),
        )'''
if old_role not in text:
    raise SystemExit('role prompt anchor not found')
text = text.replace(old_role, new_role, 1)
text = text.replace('f"<b>Уволить {clean(employee[\'alias\'])}?</b>\\n\\nВернуть сотруднику:', 'f"<b>Уволить</b> · {employee_html(employee[\'alias\'], str(employee[\'role\']))}?\\n\\nВернуть сотруднику:')
text = text.replace('InlineKeyboardButton(text="Уволить",', 'InlineKeyboardButton(text="🗑️ Уволить",')
text = text.replace('f"<b>{clean(product[\'title\'])} · партия #{batch_id}</b>\\n\\n"', 'f"{product_html(product[\'title\'])} · 📦 <b>партия #{batch_id}</b>\\n\\n"')
path.write_text(text, encoding='utf-8')

# --- ui_commerce.py: product entities and missing button markers -----------
path = APP / 'ui_commerce.py'
text = path.read_text(encoding='utf-8')
if 'from app.presentation.entities import' not in text:
    anchor = 'from app.presentation.vocabulary import '
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(anchor):
            lines.insert(i + 1, 'from app.presentation.entities import product_html')
            break
    text = '\n'.join(lines) + ('\n' if text.endswith('\n') else '')
text = text.replace('text=f"{row[\'title\']} · {int(row[\'stock\'])} ед. ·', 'text=f"📦 {row[\'title\']} · {int(row[\'stock\'])} ед. ·')
text = text.replace('f"<b>{clean(product[\'title\'])}</b>\\n\\n{published} ед. готовы', 'f"{product_html(product[\'title\'])}\\n\\n{published} ед. готовы')
text = text.replace('f"<b>{clean(row[\'title\'])} · ×{row[\'pack_size\']}</b>\\n\\n"', 'f"📦 <b>{clean(row[\'title\'])} · ×{row[\'pack_size\']}</b>\\n\\n"')
text = text.replace('f"{str(row[\'title\'])[:18]}"', 'f"📦 {str(row[\'title\'])[:18]}"')
text = text.replace('text=f"{_offer_marker(str(offer[\'market_profile\']))}×{offer[\'quantity\']}', 'text=f"🛒 {_offer_marker(str(offer[\'market_profile\']))}×{offer[\'quantity\']}')
path.write_text(text, encoding='utf-8')

# --- common literal action buttons across UI modules ----------------------
replacements = {
    'InlineKeyboardButton(text="Отмена",': 'InlineKeyboardButton(text="↩️ Отмена",',
    "InlineKeyboardButton(text='Отмена',": "InlineKeyboardButton(text='↩️ Отмена',",
    'InlineKeyboardButton(text="Назад",': 'InlineKeyboardButton(text="⬅️ Назад",',
    "InlineKeyboardButton(text='Назад',": "InlineKeyboardButton(text='⬅️ Назад',",
    'InlineKeyboardButton(text="Обновить",': 'InlineKeyboardButton(text="🔄 Обновить",',
    'InlineKeyboardButton(text="Профиль",': 'InlineKeyboardButton(text="👤 Профиль",',
    'InlineKeyboardButton(text="Подробнее",': 'InlineKeyboardButton(text="ℹ️ Подробнее",',
    'InlineKeyboardButton(text="Открыть",': 'InlineKeyboardButton(text="📂 Открыть",',
    'InlineKeyboardButton(text="Закрыть",': 'InlineKeyboardButton(text="❌ Закрыть",',
    'InlineKeyboardButton(text="Принять",': 'InlineKeyboardButton(text="✅ Принять",',
    'InlineKeyboardButton(text="Отклонить",': 'InlineKeyboardButton(text="❌ Отклонить",',
}
for ui_path in APP.rglob('ui*.py'):
    value = ui_path.read_text(encoding='utf-8')
    before = value
    for old, new in replacements.items():
        value = value.replace(old, new)
    # Contextual raw nav labels also need visual markers.
    nav_labels = {
        '"Профиль"': '"👤 Профиль"',
        '"Назад"': '"⬅️ Назад"',
        '"Кандидаты"': '"👥 Кандидаты"',
        '"Найм"': '"🔎 Найм"',
        '"Каналы"': '"📣 Каналы"',
        '"Предложение"': '"🛒 Предложение"',
        '"Партия"': '"📦 Партия"',
        '"Развитие"': '"📈 Развитие"',
    }
    for raw, marked in nav_labels.items():
        value = re.sub(rf'(nav_row\([^\n]*,\s*){re.escape(raw)}', rf'\1{marked}', value)
    if value != before:
        ui_path.write_text(value, encoding='utf-8')

# tutorial_hint is internal presentation copy. Preserve trusted <b> tags emitted
# by entity helpers while still escaping every other HTML character.
path = APP / 'ui_common.py'
text = path.read_text(encoding='utf-8')
old = '    return f"<blockquote>{clean(_format_tutorial_blocks(normalized))}</blockquote>"'
new = '''    safe = clean(_format_tutorial_blocks(normalized))
    safe = safe.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    return f"<blockquote>{safe}</blockquote>"'''
if old not in text:
    raise SystemExit('tutorial_hint anchor not found')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')

# --- tests / permanent guardrails -----------------------------------------
(TESTS / 'test_entity_presentation.py').write_text('''from app.presentation.entities import employee_html, product_html, role_html, role_label


def test_role_entity_styles_are_canonical() -> None:
    assert role_label("courier") == "👤 закладчик"
    assert role_label("warehouse") == "🚚 складмен"
    assert role_html("courier") == "👤 <b>закладчик</b>"
    assert role_html("warehouse") == "🚚 <b>складмен</b>"
    assert role_html("warehouse", form="складмена") == "🚚 <b>складмена</b>"


def test_named_entities_have_icon_and_bold_text() -> None:
    assert employee_html("Сова", "courier") == "👤 <b>Сова</b>"
    assert employee_html("Маяк", "warehouse") == "🚚 <b>Маяк</b>"
    assert product_html("Кокаин") == "📦 <b>Кокаин</b>"
''', encoding='utf-8')

# Add AST checks to the existing vocabulary test rather than another unrelated scanner.
path = TESTS / 'test_ui_vocabulary.py'
text = path.read_text(encoding='utf-8')
if 'def test_inline_buttons_have_visual_markers' not in text:
    text += r'''

VISUAL_MARKERS = (
    "🏠", "📦", "🤝", "🏷", "👥", "📊", "📨", "🛠", "🔎", "✅", "⚙️",
    "🔄", "👤", "🚚", "💰", "🛌", "📈", "📱", "🚗", "🚲", "🛒", "❌",
    "↩️", "⬅️", "➖", "➕", "🎓", "📣", "⏱", "▶️", "ℹ️", "📂", "🟨", "🧱",
    "🕸", "⚠️", "💎", "⭐", "🔴", "🟢", "⚪", "⏩", "✏️", "🗑️", "🎯",
)


def _expr_has_visual_marker(node: ast.AST) -> bool:
    source = ast.unparse(node)
    if ".label" in source or ".icon" in source or "role_label(" in source:
        return True
    return any(marker in source for marker in VISUAL_MARKERS)


def test_inline_buttons_have_visual_markers() -> None:
    offenders: list[str] = []
    for source_path in APP.rglob("*.py"):
        if source_path.name == "vocabulary.py":
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name == "InlineKeyboardButton":
                text_kw = next((kw.value for kw in node.keywords if kw.arg == "text"), None)
                if text_kw is not None and not _expr_has_visual_marker(text_kw):
                    offenders.append(
                        f"{source_path.relative_to(APP)}:{getattr(node, 'lineno', '?')} text={ast.unparse(text_kw)}"
                    )
            elif name == "nav_row" and len(node.args) >= 2:
                parent_text = node.args[1]
                if isinstance(parent_text, ast.Constant) and isinstance(parent_text.value, str):
                    if not any(parent_text.value.startswith(marker) for marker in VISUAL_MARKERS):
                        offenders.append(
                            f"{source_path.relative_to(APP)}:{getattr(node, 'lineno', '?')} nav={parent_text.value!r}"
                        )
    assert not offenders, "buttons without visual markers: " + "; ".join(offenders)
'''
path.write_text(text, encoding='utf-8')

# Focused contract for the user-visible role-change screen source.
(TESTS / 'test_role_change_presentation.py').write_text('''from pathlib import Path


def test_role_change_screen_uses_entity_helpers() -> None:
    source = Path("app/ui_staff_handlers.py").read_text(encoding="utf-8")
    assert 'Сейчас: {role_html(current_role)}' in source
    assert 'Новая роль: {role_html(new_role)}' in source
    assert 'Сменить на {role_label(new_role)}' in source
    assert 'Сменить на {new}' not in source
''', encoding='utf-8')

print('entity presentation pass applied')
