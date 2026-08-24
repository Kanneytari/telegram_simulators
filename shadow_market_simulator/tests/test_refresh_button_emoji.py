from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.ui_common import _normalize_menu_buttons


def test_refresh_button_always_gets_refresh_emoji():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Обновить", callback_data="anything:refresh")
        ]]
    )

    normalized = _normalize_menu_buttons(markup)

    assert normalized.inline_keyboard[0][0].text == "🔄 Обновить"


def test_existing_refresh_emoji_is_not_duplicated():
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🔄 Обновить", callback_data="anything:refresh")
        ]]
    )

    normalized = _normalize_menu_buttons(markup)

    assert normalized.inline_keyboard[0][0].text == "🔄 Обновить"
