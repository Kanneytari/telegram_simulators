from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📨 Входящие"), KeyboardButton(text="👥 Команда")],
        [KeyboardButton(text="📦 Закупки"), KeyboardButton(text="🏷 Витрина")],
        [KeyboardButton(text="📊 Аналитика"), KeyboardButton(text="🏠 Сводка")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери раздел",
)


def back_to_inbox() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← Входящие", callback_data="inbox:list")]])


def inbox_list(items) -> InlineKeyboardMarkup:
    rows = []
    markers = {"urgent": "🔴", "important": "🟠", "normal": "⚪"}
    for item in items:
        rows.append([
            InlineKeyboardButton(
                text=f"{markers.get(item['priority'], '⚪')} {item['title'][:42]}",
                callback_data=f"inbox:item:{item['id']}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="Обновить", callback_data="inbox:list")]])


def inbox_actions(item) -> InlineKeyboardMarkup:
    kind = item["kind"]
    if kind == "dispute":
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть разбор", callback_data=f"inbox:dispute:{item['id']}")]])
    if kind in {"discount_request", "raise_request", "leave_request", "advance_request"}:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Согласиться", callback_data=f"inbox:action:{item['id']}:approve"),
                InlineKeyboardButton(text="Отказать", callback_data=f"inbox:action:{item['id']}:deny"),
            ],
            [InlineKeyboardButton(text="← Входящие", callback_data="inbox:list")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Закрыть", callback_data=f"inbox:action:{item['id']}:close")],
        [InlineKeyboardButton(text="← Входящие", callback_data="inbox:list")],
    ])


def dispute_actions(dispute_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Запросить сотрудника", callback_data=f"dispute:ask:{dispute_id}")],
        [
            InlineKeyboardButton(text="Вернуть 100%", callback_data=f"dispute:resolve:{dispute_id}:refund"),
            InlineKeyboardButton(text="Вернуть 50%", callback_data=f"dispute:resolve:{dispute_id}:partial"),
        ],
        [InlineKeyboardButton(text="Отказать", callback_data=f"dispute:resolve:{dispute_id}:reject")],
        [InlineKeyboardButton(text="← Входящие", callback_data="inbox:list")],
    ])


def employee_list(employees) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{e['alias']} · {e['jobs_done']} заказов", callback_data=f"employee:{e['id']}")]
        for e in employees
    ]
    rows.append([InlineKeyboardButton(text="Кандидаты", callback_data="candidates:list")])
    rows.append([InlineKeyboardButton(text="Запустить поиск", callback_data="recruit:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def recruitment_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Доска площадки · 2 500 ₽", callback_data="recruit:run:board")],
        [InlineKeyboardButton(text="Рефералы команды · 6 000 ₽", callback_data="recruit:run:referral")],
        [InlineKeyboardButton(text="Нишевая реклама · 11 000 ₽", callback_data="recruit:run:niche")],
        [InlineKeyboardButton(text="← Команда", callback_data="team:list")],
    ])


def candidate_list(candidates) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{c['alias']} · {c['desired_pay']} ₽", callback_data=f"candidate:{c['id']}")]
        for c in candidates
    ]
    rows.append([InlineKeyboardButton(text="← Команда", callback_data="team:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def candidate_actions(candidate_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Нанять", callback_data=f"candidate:hire:{candidate_id}"),
            InlineKeyboardButton(text="Отказать", callback_data=f"candidate:reject:{candidate_id}"),
        ],
        [InlineKeyboardButton(text="← Кандидаты", callback_data="candidates:list")],
    ])


def offer_list(offers) -> InlineKeyboardMarkup:
    rows = []
    for o in offers:
        total = o["quantity"] * o["unit_cost"]
        rows.append([InlineKeyboardButton(
            text=f"{o['product_title']} × {o['quantity']} · {total:,} ₽",
            callback_data=f"offer:{o['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="Обновить", callback_data="offers:list")]])


def offer_actions(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Купить партию", callback_data=f"offer:buy:{offer_id}")],
        [InlineKeyboardButton(text="← Закупки", callback_data="offers:list")],
    ])


def listing_list(listings) -> InlineKeyboardMarkup:
    rows = []
    for l in listings:
        rows.append([InlineKeyboardButton(
            text=f"{l['title']} ×{l['pack_size']} · {l['price']:,} ₽",
            callback_data=f"listing:{l['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def listing_actions(listing_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="-5%", callback_data=f"listing:price:{listing_id}:-5"),
            InlineKeyboardButton(text="+5%", callback_data=f"listing:price:{listing_id}:5"),
        ],
        [InlineKeyboardButton(text="← Витрина", callback_data="listings:list")],
    ])
