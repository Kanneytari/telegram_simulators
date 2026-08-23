from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


def build_dispute_router(game) -> Router:
    router = Router(name="dispute-flow")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def decision_keyboard(dispute_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💬 Запросить пояснение", callback_data=f"dispute:ask:{dispute_id}")],
                [
                    InlineKeyboardButton(text="Вернуть 100%", callback_data=f"dispute:amount:{dispute_id}:refund"),
                    InlineKeyboardButton(text="Вернуть 50%", callback_data=f"dispute:amount:{dispute_id}:partial"),
                ],
                [InlineKeyboardButton(text="Отказать", callback_data=f"dispute:reject:{dispute_id}")],
                [
                    InlineKeyboardButton(text="← Клиенты", callback_data="inbox:clients"),
                    InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
                ],
            ]
        )

    def source_keyboard(context: dict, decision: str) -> InlineKeyboardMarkup:
        dispute_id = int(context["dispute_id"])
        amount = int(context["amount"])
        employee_deposit = int(context["employee_deposit"])
        shop_balance = int(context["shop_balance"])
        employee_alias = context["employee_alias"]
        rows = []
        if shop_balance >= amount:
            rows.append(
                [InlineKeyboardButton(text="💳 Со счёта магазина", callback_data=f"dispute:pay:{dispute_id}:{decision}:shop")]
            )
        else:
            rows.append(
                [InlineKeyboardButton(text="Счёт магазина · недостаточно", callback_data="dispute:nofunds:shop")]
            )
        if employee_deposit >= amount:
            rows.append(
                [InlineKeyboardButton(text=f"👤 Из депозита {employee_alias}", callback_data=f"dispute:pay:{dispute_id}:{decision}:employee")]
            )
        else:
            rows.append(
                [InlineKeyboardButton(text=f"Депозит {employee_alias} · недостаточно", callback_data="dispute:nofunds:employee")]
            )
        rows.append(
            [
                InlineKeyboardButton(text="← Назад", callback_data=f"dispute:view:{dispute_id}"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def render_dispute(target: Message, player_id: int, dispute_id: int) -> None:
        text = game.dispute_details(player_id, dispute_id)
        if not text:
            await present(
                target,
                "Диспут больше недоступен.",
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="← Клиенты", callback_data="inbox:clients")],
                        [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
                    ]
                ),
            )
            return
        await present(target, text, decision_keyboard(dispute_id))

    @router.callback_query(F.data.startswith("inbox:dispute:"))
    async def open_from_inbox(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int(callback.data.split(":")[2])
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await present(callback.message, "Диспут уже закрыт.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← Клиенты", callback_data="inbox:clients")]]))
            return
        dispute_id = int(json.loads(item["payload_json"] or "{}")["dispute_id"])
        await render_dispute(callback.message, callback.from_user.id, dispute_id)

    @router.callback_query(F.data.startswith("dispute:view:"))
    async def view_dispute(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_dispute(callback.message, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("dispute:ask:"))
    async def ask_employee(callback: CallbackQuery) -> None:
        dispute_id = int(callback.data.split(":")[2])
        status = game.ask_employee_about_dispute(callback.from_user.id, dispute_id)
        await callback.answer(status[:200])
        await render_dispute(callback.message, callback.from_user.id, dispute_id)

    @router.callback_query(F.data.startswith("dispute:amount:"))
    async def choose_source(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, dispute_id, decision = callback.data.split(":")
        context = game.dispute_payment_context(callback.from_user.id, int(dispute_id), decision)
        if not context:
            await present(callback.message, "Диспут уже закрыт.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← Клиенты", callback_data="inbox:clients")]]))
            return
        text = (
            f"<b>Компенсация · {int(context['amount']):,} ₽</b>\n\n"
            "<b>Источник средств</b>\n"
            f"Счёт магазина: {context['shop_balance']:,} ₽\n"
            f"Депозит {context['employee_alias']}: {context['employee_deposit']:,} ₽\n\n"
            "Выбери, откуда списать компенсацию."
        )
        await present(callback.message, text, source_keyboard(context, decision))

    @router.callback_query(F.data.startswith("dispute:pay:"))
    async def pay_compensation(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, dispute_id, decision, source = callback.data.split(":")
        dispute_id_int = int(dispute_id)
        result = game.resolve_dispute_with_source(callback.from_user.id, dispute_id_int, decision, source)
        remaining = game.dispute_payment_context(callback.from_user.id, dispute_id_int, decision)
        if remaining:
            await present(
                callback.message,
                f"<b>Компенсация не проведена</b>\n\n{result}\n\nВыбери другой источник.",
                source_keyboard(remaining, decision),
            )
            return
        await present(
            callback.message,
            f"<b>⚖️ Диспут закрыт</b>\n\n{result}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="← Клиенты", callback_data="inbox:clients")],
                    [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
                ]
            ),
        )

    @router.callback_query(F.data.startswith("dispute:reject:"))
    async def reject(callback: CallbackQuery) -> None:
        await callback.answer()
        dispute_id = int(callback.data.split(":")[2])
        result = game.resolve_dispute_with_source(callback.from_user.id, dispute_id, "reject", "none")
        await present(
            callback.message,
            f"<b>⚖️ Диспут закрыт</b>\n\n{result}",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="← Клиенты", callback_data="inbox:clients")],
                    [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
                ]
            ),
        )

    @router.callback_query(F.data.startswith("dispute:nofunds:"))
    async def no_funds(callback: CallbackQuery) -> None:
        source = callback.data.split(":")[2]
        text = "На счёте магазина недостаточно средств" if source == "shop" else "В депозите сотрудника недостаточно средств"
        await callback.answer(text, show_alert=True)

    return router
