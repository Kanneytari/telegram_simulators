from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(open_count: int = 0, urgent_count: int = 0) -> InlineKeyboardMarkup:
    inbox = f"📨 Входящие · {open_count}"
    if urgent_count:
        inbox += f"  🔴 {urgent_count}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=inbox, callback_data="menu:inbox")],
        [
            InlineKeyboardButton(text="👥 Команда", callback_data="menu:team"),
            InlineKeyboardButton(text="📦 Закупки", callback_data="menu:offers"),
        ],
        [
            InlineKeyboardButton(text="🏷 Витрина", callback_data="menu:listings"),
            InlineKeyboardButton(text="📊 Аналитика", callback_data="menu:analytics"),
        ],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:home")],
    ])


def navigation(back_callback: str, back_text: str = "← Назад") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=back_text, callback_data=back_callback),
        InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
    ]])


def inbox_list(items) -> InlineKeyboardMarkup:
    rows = []
    markers = {"urgent": "🔴", "important": "🟠", "normal": "⚪"}
    for item in items:
        rows.append([InlineKeyboardButton(
            text=f"{markers.get(item['priority'], '⚪')} {item['title'][:42]}",
            callback_data=f"inbox:item:{item['id']}",
        )])
    rows.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:inbox"),
        InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inbox_actions(item) -> InlineKeyboardMarkup:
    kind = item["kind"]
    rows = []
    if kind == "dispute":
        rows.append([InlineKeyboardButton(text="⚖️ Открыть разбор", callback_data=f"inbox:dispute:{item['id']}")])
    elif kind in {"discount_request", "raise_request", "leave_request", "advance_request"}:
        rows.append([
            InlineKeyboardButton(text="✅ Согласиться", callback_data=f"inbox:action:{item['id']}:approve"),
            InlineKeyboardButton(text="❌ Отказать", callback_data=f"inbox:action:{item['id']}:deny"),
        ])
    elif kind == "recruitment_result":
        rows.append([InlineKeyboardButton(text="👤 Смотреть кандидатов", callback_data="candidates:list")])
        rows.append([InlineKeyboardButton(text="✓ Закрыть", callback_data=f"inbox:action:{item['id']}:close")])
    else:
        rows.append([InlineKeyboardButton(text="✓ Закрыть", callback_data=f"inbox:action:{item['id']}:close")])
    rows.append([
        InlineKeyboardButton(text="← Входящие", callback_data="menu:inbox"),
        InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dispute_actions(dispute_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Запросить пояснение", callback_data=f"dispute:ask:{dispute_id}")],
        [
            InlineKeyboardButton(text="↩️ Вернуть 100%", callback_data=f"dispute:resolve:{dispute_id}:refund"),
            InlineKeyboardButton(text="↩️ Вернуть 50%", callback_data=f"dispute:resolve:{dispute_id}:partial"),
        ],
        [InlineKeyboardButton(text="🚫 Отказать", callback_data=f"dispute:resolve:{dispute_id}:reject")],
        [
            InlineKeyboardButton(text="← Входящие", callback_data="menu:inbox"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ],
    ])


def employee_list(employees) -> InlineKeyboardMarkup:
    rows = []
    for employee in employees:
        role_icon = "🚚" if employee["role"] == "warehouse" else "👤"
        status = employee.get("status_text", "свободен") if isinstance(employee, dict) else "свободен"
        exposure = int(employee.get("exposure", 0)) if isinstance(employee, dict) else 0
        risk = " 🔴" if exposure > int(employee["deposit"]) else ""
        rows.append([InlineKeyboardButton(
            text=f"{role_icon} {employee['alias']} · {status}{risk}",
            callback_data=f"employee:{employee['id']}",
        )])
    rows.extend([
        [
            InlineKeyboardButton(text="👤 Кандидаты", callback_data="candidates:list"),
            InlineKeyboardButton(text="🔎 Набор", callback_data="recruit:menu"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Фасовки", callback_data="team:packrules"),
            InlineKeyboardButton(text="📦 Без ответственного", callback_data="team:unassigned"),
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:team"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def employee_actions() -> InlineKeyboardMarkup:
    return navigation("menu:team", "← Команда")


def recruitment_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟨 Расклейщики стикеров · 3 500 ₽", callback_data="recruit:confirm:stickers")],
        [InlineKeyboardButton(text="🧱 Граффити-команда · 7 500 ₽", callback_data="recruit:confirm:graffiti")],
        [InlineKeyboardButton(text="🕸 Реклама на форумах · 12 000 ₽", callback_data="recruit:confirm:forums")],
        [
            InlineKeyboardButton(text="← Команда", callback_data="menu:team"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ],
    ])


def recruitment_confirm(channel: str, cost: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Запустить · {cost:,} ₽", callback_data=f"recruit:run:{channel}")],
        [
            InlineKeyboardButton(text="← Набор", callback_data="recruit:menu"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ],
    ])


def candidate_list(candidates) -> InlineKeyboardMarkup:
    rows = []
    for candidate in candidates:
        role = "опт" if candidate["role"] == "warehouse" else "розница"
        rows.append([InlineKeyboardButton(
            text=f"{candidate['alias']} · {role} · {candidate['desired_pay']:,} ₽",
            callback_data=f"candidate:{candidate['id']}",
        )])
    rows.extend([
        [InlineKeyboardButton(text="🔎 Запустить набор", callback_data="recruit:menu")],
        [
            InlineKeyboardButton(text="← Команда", callback_data="menu:team"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def candidate_actions(candidate_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Нанять", callback_data=f"candidate:hire:{candidate_id}"),
            InlineKeyboardButton(text="❌ Отказать", callback_data=f"candidate:reject:{candidate_id}"),
        ],
        [
            InlineKeyboardButton(text="← Кандидаты", callback_data="candidates:list"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ],
    ])


def offer_list(offers) -> InlineKeyboardMarkup:
    rows = []
    for offer in offers:
        total = offer["quantity"] * offer["unit_cost"]
        rows.append([InlineKeyboardButton(
            text=f"{offer['product_title']} × {offer['quantity']} · {total:,} ₽",
            callback_data=f"offer:{offer['id']}",
        )])
    rows.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:offers"),
        InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
