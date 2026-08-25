from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


MAIN_ROWS = [
    [("🏠 Поселение", "menu:settlement"), ("👥 Жители", "menu:residents")],
    [("🧭 Вылазки", "menu:expeditions"), ("🏗 Развитие", "menu:buildings")],
    [("📋 События", "menu:events")],
]


def keyboard(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def main_menu() -> InlineKeyboardMarkup:
    return keyboard(MAIN_ROWS)


def back_menu() -> InlineKeyboardMarkup:
    return keyboard([[('🏠 Меню', 'menu:home')]])
