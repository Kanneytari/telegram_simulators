from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from . import ui_commerce


_EMPTY_STOCK_SUFFIX = " · 🚚 нет запаса"


def apply_product_ui_update() -> None:
    original = ui_commerce._procurement_products_keyboard
    if getattr(original, "_product_ui_updated", False):
        return

    def _procurement_products_keyboard(db, player_id: int, products) -> InlineKeyboardMarkup:
        markup = original(db, player_id, products)
        changed = False
        rows = []
        for row in markup.inline_keyboard:
            new_row = []
            for button in row:
                text = button.text or ""
                new_text = text
                if (
                    button.callback_data
                    and button.callback_data.startswith("proc:product:")
                    and new_text.endswith(_EMPTY_STOCK_SUFFIX)
                ):
                    new_text = new_text.removesuffix(_EMPTY_STOCK_SUFFIX)
                if button.callback_data == "team:batches" and new_text.startswith("🚚 Склад"):
                    new_text = new_text.replace("🚚 Склад", "📦 Склад", 1)
                if new_text != text:
                    button = button.model_copy(update={"text": new_text})
                    changed = True
                new_row.append(button)
            rows.append(new_row)
        return InlineKeyboardMarkup(inline_keyboard=rows) if changed else markup

    _procurement_products_keyboard._product_ui_updated = True
    ui_commerce._procurement_products_keyboard = _procurement_products_keyboard
