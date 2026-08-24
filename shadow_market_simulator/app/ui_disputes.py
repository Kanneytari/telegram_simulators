from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .ui_common import clean, money, nav_row, notice, present, rating
from .ui_navigation import render_inbox


def _dispute_context(game, player_id: int, dispute_id: int):
    with game.db.connect() as conn:
        return conn.execute(
            """SELECT d.*, o.revenue, o.id order_id, p.title product_title,
                      e.alias employee_alias,
                      r.product_rating, r.courier_rating
               FROM disputes d
               JOIN orders o ON o.id=d.order_id
               JOIN products p ON p.id=o.product_id
               JOIN employees e ON e.id=o.employee_id
               LEFT JOIN order_ratings r ON r.order_id=o.id
               WHERE d.id=? AND d.player_id=?""",
            (dispute_id, player_id),
        ).fetchone()


def decision_keyboard(dispute_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Запросить пояснение", callback_data=f"dispute:ask:{dispute_id}")],
        [
            InlineKeyboardButton(text="Вернуть 100%", callback_data=f"dispute:amount:{dispute_id}:refund"),
            InlineKeyboardButton(text="Вернуть 50%", callback_data=f"dispute:amount:{dispute_id}:partial"),
        ],
        [InlineKeyboardButton(text="Отказать", callback_data=f"dispute:reject:{dispute_id}")],
        nav_row("menu:inbox", "← Входящие"),
    ])


async def render_dispute(target: Message, game, player_id: int, dispute_id: int) -> None:
    row = _dispute_context(game, player_id, dispute_id)
    if not row or row["status"] != "open":
        await render_inbox(target, game, game.simulation, player_id, flash="Диспут уже закрыт.")
        return
    product_rating = rating(float(row["product_rating"] or 0), 1 if row["product_rating"] else 0)
    courier_rating = rating(float(row["courier_rating"] or 0), 1 if row["courier_rating"] else 0)
    text = (
        f"<b>⚖️ Заказ #{row['order_id']} · {money(row['revenue'])}</b>\n\n"
        f"{clean(row['message'])}\n\n"
        f"Товар: {clean(row['product_title'])} · оценка {product_rating}\n"
        f"Курьер: {clean(row['employee_alias'])} · оценка {courier_rating}"
    )
    if row["courier_reply"]:
        text += f"\n\n<b>Пояснение курьера</b>\n{clean(row['courier_reply'])}"
    else:
        text += "\n\nПояснение курьера пока не запрошено."
    await present(target, text, decision_keyboard(dispute_id))


def source_keyboard(context, decision: str) -> InlineKeyboardMarkup:
    dispute_id = int(context["dispute_id"])
    amount = int(context["amount"])
    rows: list[list[InlineKeyboardButton]] = []
    if int(context["shop_balance"]) >= amount:
        rows.append([InlineKeyboardButton(text="Со счёта магазина", callback_data=f"dispute:pay:{dispute_id}:{decision}:shop")])
    if int(context["employee_deposit"]) >= amount:
        rows.append([InlineKeyboardButton(text=f"Из депозита {context['employee_alias']}", callback_data=f"dispute:pay:{dispute_id}:{decision}:employee")])
    rows.append(nav_row(f"dispute:view:{dispute_id}", "← Диспут"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_source(target: Message, game, player_id: int, dispute_id: int, decision: str, *, flash: str | None = None) -> None:
    context = game.dispute_payment_context(player_id, dispute_id, decision)
    if not context:
        await render_inbox(target, game, game.simulation, player_id, flash="Диспут уже закрыт.")
        return
    amount = int(context["amount"])
    text = (
        f"<b>Вернуть клиенту {money(amount)}</b>\n\n"
        f"Со счёта магазина\n{money(amount)} расхода · отношения с сотрудником не страдают\n\n"
        f"Из депозита {clean(context['employee_alias'])}\n"
        f"Депозит уменьшится на {money(amount)} · отношения ухудшатся"
    )
    if int(context["shop_balance"]) < amount:
        text += "\n\nСчёта магазина недостаточно для этой компенсации."
    if int(context["employee_deposit"]) < amount:
        text += "\nДепозита сотрудника недостаточно."
    await present(target, notice(flash, text), source_keyboard(context, decision))


def build_dispute_router(game) -> Router:
    router = Router(name="compact-disputes")

    @router.callback_query(F.data.startswith("inbox:dispute:"))
    async def open_from_inbox(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int(callback.data.split(":")[2])
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await render_inbox(callback.message, game, game.simulation, callback.from_user.id, flash="Сообщение уже закрыто.")
            return
        payload = json.loads(item["payload_json"] or "{}")
        dispute_id = int(payload.get("dispute_id", 0))
        await render_dispute(callback.message, game, callback.from_user.id, dispute_id)

    @router.callback_query(F.data.startswith("dispute:view:"))
    async def view(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_dispute(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("dispute:ask:"))
    async def ask(callback: CallbackQuery) -> None:
        dispute_id = int(callback.data.split(":")[2])
        result = game.ask_employee_about_dispute(callback.from_user.id, dispute_id)
        await callback.answer(result[:180])
        await render_dispute(callback.message, game, callback.from_user.id, dispute_id)

    @router.callback_query(F.data.startswith("dispute:amount:"))
    async def amount(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, dispute_raw, decision = callback.data.split(":")
        await render_source(callback.message, game, callback.from_user.id, int(dispute_raw), decision)

    @router.callback_query(F.data.startswith("dispute:pay:"))
    async def pay(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, dispute_raw, decision, source = callback.data.split(":")
        dispute_id = int(dispute_raw)
        result = game.resolve_dispute_with_source(callback.from_user.id, dispute_id, decision, source)
        remaining = game.dispute_payment_context(callback.from_user.id, dispute_id, decision)
        if remaining:
            await render_source(callback.message, game, callback.from_user.id, dispute_id, decision, flash=result)
            return
        await render_inbox(callback.message, game, game.simulation, callback.from_user.id, flash=result)

    @router.callback_query(F.data.startswith("dispute:reject:"))
    async def reject(callback: CallbackQuery) -> None:
        await callback.answer()
        dispute_id = int(callback.data.split(":")[2])
        result = game.resolve_dispute_with_source(callback.from_user.id, dispute_id, "reject", "none")
        await render_inbox(callback.message, game, game.simulation, callback.from_user.id, flash=result)

    return router
