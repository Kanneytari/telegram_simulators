from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(open_count: int = 0, urgent_count: int = 0) -> InlineKeyboardMarkup:
    inbox = f"📨 Входящие · {open_count}"
    if urgent_count:
        inbox += f"  🔴 {urgent_count}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
        ]
    )


def navigation(back_callback: str, back_text: str = "← Назад") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=back_text, callback_data=back_callback),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ]
        ]
    )


def inbox_list(items) -> InlineKeyboardMarkup:
    rows = []
    markers = {"urgent": "🔴", "important": "🟠", "normal": "⚪"}
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{markers.get(item['priority'], '⚪')} {item['title'][:42]}",
                    callback_data=f"inbox:item:{item['id']}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:inbox"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inbox_actions(item) -> InlineKeyboardMarkup:
    kind = item["kind"]
    rows = []
    if kind == "dispute":
        rows.append(
            [InlineKeyboardButton(text="⚖️ Открыть разбор", callback_data=f"inbox:dispute:{item['id']}")]
        )
    elif kind in {"discount_request", "raise_request", "leave_request", "advance_request"}:
        rows.append(
            [
                InlineKeyboardButton(text="✅ Согласиться", callback_data=f"inbox:action:{item['id']}:approve"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"inbox:action:{item['id']}:deny"),
            ]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="✓ Закрыть", callback_data=f"inbox:action:{item['id']}:close")]
        )
    rows.append(
        [
            InlineKeyboardButton(text="← Входящие", callback_data="menu:inbox"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dispute_actions(dispute_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
        ]
    )


def employee_list(employees) -> InlineKeyboardMarkup:
    rows = []
    for employee in employees:
        rate = (employee["disputes"] / employee["jobs_done"] * 100.0) if employee["jobs_done"] else 0.0
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{employee['alias']} · {employee['jobs_done']} заказов · {rate:.1f}% споров",
                    callback_data=f"employee:{employee['id']}",
                )
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(text="👤 Кандидаты", callback_data="candidates:list"),
                InlineKeyboardButton(text="🔎 Поиск", callback_data="recruit:menu"),
            ],
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:team"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def employee_actions() -> InlineKeyboardMarkup:
    return navigation("menu:team", "← Команда")


def recruitment_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Доска площадки · 2 500 ₽", callback_data="recruit:confirm:board")],
            [InlineKeyboardButton(text="Рефералы команды · 6 000 ₽", callback_data="recruit:confirm:referral")],
            [InlineKeyboardButton(text="Нишевая реклама · 11 000 ₽", callback_data="recruit:confirm:niche")],
            [
                InlineKeyboardButton(text="← Команда", callback_data="menu:team"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ]
    )


def recruitment_confirm(channel: str, cost: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Запустить · {cost:,} ₽", callback_data=f"recruit:run:{channel}")],
            [
                InlineKeyboardButton(text="← Назад", callback_data="recruit:menu"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ]
    )


def candidate_list(candidates) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{candidate['alias']} · {candidate['desired_pay']:,} ₽/заказ",
                callback_data=f"candidate:{candidate['id']}",
            )
        ]
        for candidate in candidates
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text="🔎 Запустить поиск", callback_data="recruit:menu")],
            [
                InlineKeyboardButton(text="← Команда", callback_data="menu:team"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def candidate_actions(candidate_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Нанять", callback_data=f"candidate:hire:{candidate_id}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"candidate:reject:{candidate_id}"),
            ],
            [
                InlineKeyboardButton(text="← Кандидаты", callback_data="candidates:list"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ]
    )


def offer_list(offers) -> InlineKeyboardMarkup:
    rows = []
    for offer in offers:
        total = offer["quantity"] * offer["unit_cost"]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{offer['product_title']} × {offer['quantity']} · {total:,} ₽",
                    callback_data=f"offer:{offer['id']}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:offers"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def offer_actions(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Купить партию", callback_data=f"offer:confirm:{offer_id}")],
            [
                InlineKeyboardButton(text="← Закупки", callback_data="menu:offers"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ]
    )


def offer_confirm(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить покупку", callback_data=f"offer:buy:{offer_id}")],
            [
                InlineKeyboardButton(text="← Назад", callback_data=f"offer:{offer_id}"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ]
    )


def listing_list(listings) -> InlineKeyboardMarkup:
    rows = []
    for listing in listings:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{listing['title']} ×{listing['pack_size']} · {listing['price']:,} ₽",
                    callback_data=f"listing:{listing['id']}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:listings"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def listing_actions(listing_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="−5%", callback_data=f"listing:price:{listing_id}:-5"),
                InlineKeyboardButton(text="+5%", callback_data=f"listing:price:{listing_id}:5"),
            ],
            [
                InlineKeyboardButton(text="← Витрина", callback_data="menu:listings"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ]
    )


def analytics_actions() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:analytics"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ]
        ]
    )


def result_actions(back_callback: str, back_text: str) -> InlineKeyboardMarkup:
    return navigation(back_callback, back_text)


def reset_confirmation() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, начать заново", callback_data="reset:confirm")],
            [InlineKeyboardButton(text="Отмена", callback_data="reset:cancel")],
        ]
    )


def notification_actions(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть сообщение", callback_data=f"inbox:item:{item_id}")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ]
    )
