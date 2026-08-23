from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from .runtime import STAFF_INBOX_KINDS

CLIENT_KINDS = {"dispute", "discount_request"}


def build_action_router(game) -> Router:
    router = Router(name="inbox-actions")

    @router.callback_query(F.data.startswith("inbox:action:"))
    async def inbox_action(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, item_id_raw, action = callback.data.split(":")
        item_id = int(item_id_raw)
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await callback.message.edit_text(
                "Сообщение уже неактуально.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="← Входящие", callback_data="menu:inbox")]]
                ),
            )
            return

        kind = item["kind"]
        if action == "close":
            game.close_inbox(callback.from_user.id, item_id)
            result = "Сообщение закрыто."
        else:
            result = game.handle_inbox_action(callback.from_user.id, item_id, action)

        if kind in STAFF_INBOX_KINDS:
            back_callback = "inbox:staff"
            back_text = "← Сотрудники"
        elif kind in CLIENT_KINDS:
            back_callback = "inbox:clients"
            back_text = "← Клиенты"
        else:
            back_callback = "menu:inbox"
            back_text = "← Входящие"

        await callback.message.edit_text(
            f"<b>Готово</b>\n\n{result}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=back_text, callback_data=back_callback)],
                    [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
                ]
            ),
        )

    return router
