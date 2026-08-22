from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .content import INVESTMENTS


def main_menu(
    *,
    is_admin: bool = False,
    fast_mode: bool = False,
    actions_left: int | None = None,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="💼 Работать", callback_data="action:work"),
            InlineKeyboardButton(text="📚 Учиться", callback_data="action:learn"),
        ],
        [
            InlineKeyboardButton(text="🤝 Нетворк", callback_data="action:network"),
            InlineKeyboardButton(text="📣 Показать результат", callback_data="action:show"),
        ],
        [InlineKeyboardButton(text="☕ Выдохнуть", callback_data="action:rest")],
        [
            InlineKeyboardButton(text="🎲 Событие дня", callback_data="menu:event"),
            InlineKeyboardButton(text="💸 Вложения", callback_data="menu:invest"),
        ],
        [
            InlineKeyboardButton(text="📒 Карьера", callback_data="menu:career"),
            InlineKeyboardButton(text="🗂 История", callback_data="menu:history"),
        ],
    ]

    if is_admin:
        admin_row = [
            InlineKeyboardButton(
                text=f"🧪 Быстрый: {'ВКЛ' if fast_mode else 'ВЫКЛ'}",
                callback_data="admin:fast",
            )
        ]
        if fast_mode and actions_left == 0:
            admin_row.insert(
                0,
                InlineKeyboardButton(
                    text="⏭ Следующий день",
                    callback_data="admin:next_day",
                ),
            )
        rows.append(admin_row)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← В меню", callback_data="menu:main")]
        ]
    )


def reset_confirm_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Да, сбросить",
                    callback_data="admin:reset:confirm",
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="admin:reset:cancel",
                ),
            ]
        ]
    )


def event_menu(event: dict) -> InlineKeyboardMarkup:
    rows = []
    if event.get("choice_index") is None:
        for index, (title, _, _) in enumerate(event["choices"]):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=title,
                        callback_data=f"event:{event['id']}:{index}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(text="← В меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def investments_menu() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{item['title']} · {item['price']:,} ₽".replace(",", " "),
                callback_data=f"buy:{item_id}",
            )
        ]
        for item_id, item in INVESTMENTS.items()
    ]
    rows.append([InlineKeyboardButton(text="← В меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def career_menu(player: dict) -> InlineKeyboardMarkup:
    rows = []
    if player["promotion_ready"]:
        if player["rank"] == 2 and player["track"] == "general":
            rows.extend(
                [
                    [InlineKeyboardButton(text="🧠 Экспертный трек", callback_data="promotion:expert")],
                    [InlineKeyboardButton(text="🧑‍💼 Управленческий трек", callback_data="promotion:manager")],
                ]
            )
        else:
            rows.append([InlineKeyboardButton(text="🚀 Принять повышение", callback_data="promotion:claim")])
    rows.append([InlineKeyboardButton(text="← В меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
