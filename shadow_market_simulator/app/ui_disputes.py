from __future__ import annotations

from app.presentation.vocabulary import INBOX, nav_row
from app.presentation.entities import employee_html, product_html, role_html
import json

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .ui_common import clean, money, notice, present, rating
from .ui_navigation import render_after_inbox_action


def _dispute_context(game, player_id: int, dispute_id: int):
    with game.db.connect() as conn:
        return conn.execute(
            """SELECT d.*, o.revenue, o.id order_id, p.title product_title,
                      e.alias employee_alias, r.product_rating, r.courier_rating
               FROM disputes d
               JOIN orders o ON o.id=d.order_id
               JOIN products p ON p.id=o.product_id
               JOIN employees e ON e.id=o.employee_id
               LEFT JOIN order_ratings r ON r.order_id=o.id
               WHERE d.id=? AND d.player_id=?""",
            (dispute_id, player_id),
        ).fetchone()


def decision_keyboard(dispute_id: int, page: int = 0, *, has_reply: bool = False) -> InlineKeyboardMarkup:
    back = f"inbox:page:{page}" if page else "menu:inbox"
    rows: list[list[InlineKeyboardButton]] = []
    if not has_reply:
        rows.append([InlineKeyboardButton(text="Запросить пояснение", callback_data=f"dispute:ask:{dispute_id}:{page}")])
    rows.extend([
        [
            InlineKeyboardButton(text="💵 Вернуть 100%", callback_data=f"dispute:amount:{dispute_id}:refund:{page}"),
            InlineKeyboardButton(text="💵 Вернуть 50%", callback_data=f"dispute:amount:{dispute_id}:partial:{page}"),
        ],
        [InlineKeyboardButton(text="Отказать", callback_data=f"dispute:reject:{dispute_id}:{page}")],
        nav_row(INBOX, callback_data=back),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def render_dispute(target: Message, game, player_id: int, dispute_id: int, *, page: int = 0) -> bool:
    row = _dispute_context(game, player_id, dispute_id)
    if not row or row["status"] != "open":
        return False
    product_rating = rating(float(row["product_rating"] or 0), 1 if row["product_rating"] else 0)
    courier_rating = rating(float(row["courier_rating"] or 0), 1 if row["courier_rating"] else 0)
    text = (
        f"<b>⚖️ Заказ #{row['order_id']} · {money(row['revenue'])}</b>\n\n"
        f"{clean(row['message'])}\n\n"
        f"Товар: {product_html(row['product_title'])} · оценка {product_rating}\n"
        f"{role_html('courier', capitalize=True)}: {employee_html(row['employee_alias'], 'courier')} · оценка {courier_rating}"
    )
    if row["courier_reply"]:
        text += f"\n\n<b>Пояснение закладчика</b>\n{clean(row['courier_reply'])}"
    else:
        text += "\n\nПояснение закладчика не запрошено."
    await present(target, text, decision_keyboard(dispute_id, page, has_reply=bool(row["courier_reply"])))
    return True

def source_keyboard(context, decision: str, page: int = 0) -> InlineKeyboardMarkup:
    dispute_id = int(context["dispute_id"])
    amount = int(context["amount"])
    rows: list[list[InlineKeyboardButton]] = []
    if int(context["shop_balance"]) >= amount:
        rows.append([InlineKeyboardButton(text="🏪 Со счёта магазина", callback_data=f"dispute:pay:{dispute_id}:{decision}:shop:{page}")])
    if int(context["employee_deposit"]) >= amount:
        rows.append([InlineKeyboardButton(text=f"💰 Из депозита {context['employee_alias']}", callback_data=f"dispute:pay:{dispute_id}:{decision}:employee:{page}")])
    rows.append(nav_row(f"dispute:view:{dispute_id}:{page}", "⚖️ Диспут"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_source(target: Message, game, player_id: int, dispute_id: int, decision: str, *, page: int = 0, flash: str | None = None) -> bool:
    context = game.dispute_payment_context(player_id, dispute_id, decision)
    if not context:
        return False
    amount = int(context["amount"])
    text = (
        f"<b>Вернуть клиенту {money(amount)}</b>\n\n"
        f"Со счёта магазина\n{money(amount)} расхода · отношения с сотрудником не страдают\n\n"
        f"Из депозита {clean(context['employee_alias'])}\n"
        f"Депозит уменьшится на {money(amount)} · отношения ухудшатся"
    )
    if int(context["shop_balance"]) < amount:
        text += "\n\nСчёта магазина недостаточно."
    if int(context["employee_deposit"]) < amount:
        text += "\nДепозита сотрудника недостаточно."
    await present(target, notice(flash, text), source_keyboard(context, decision, page))
    return True


def build_dispute_router(db, game, simulation, admin_ids: frozenset[int]) -> Router:
    router = Router(name="compact-disputes")

    async def after(target: Message, player_id: int, message: str, page: int) -> None:
        await render_after_inbox_action(
            target,
            db,
            game,
            simulation,
            admin_ids,
            player_id,
            flash=message,
            page=page,
        )

    @router.callback_query(F.data.startswith("inbox:dispute:"))
    async def open_from_inbox(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = callback.data.split(":")
        item_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await after(callback.message, callback.from_user.id, "Сообщение уже закрыто.", page)
            return
        payload = json.loads(item["payload_json"] or "{}")
        dispute_id = int(payload.get("dispute_id", 0))
        if not await render_dispute(callback.message, game, callback.from_user.id, dispute_id, page=page):
            await after(callback.message, callback.from_user.id, "Диспут уже закрыт.", page)

    @router.callback_query(F.data.startswith("dispute:view:"))
    async def view(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = callback.data.split(":")
        dispute_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        if not await render_dispute(callback.message, game, callback.from_user.id, dispute_id, page=page):
            await after(callback.message, callback.from_user.id, "Диспут уже закрыт.", page)

    @router.callback_query(F.data.startswith("dispute:ask:"))
    async def ask(callback: CallbackQuery) -> None:
        parts = callback.data.split(":")
        dispute_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        result = game.ask_employee_about_dispute(callback.from_user.id, dispute_id)
        await callback.answer(result[:180])
        if not await render_dispute(callback.message, game, callback.from_user.id, dispute_id, page=page):
            await after(callback.message, callback.from_user.id, result, page)

    @router.callback_query(F.data.startswith("dispute:amount:"))
    async def amount(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = callback.data.split(":")
        dispute_id = int(parts[2])
        decision = parts[3]
        page = int(parts[4]) if len(parts) > 4 else 0
        if not await render_source(callback.message, game, callback.from_user.id, dispute_id, decision, page=page):
            await after(callback.message, callback.from_user.id, "Диспут уже закрыт.", page)

    @router.callback_query(F.data.startswith("dispute:pay:"))
    async def pay(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = callback.data.split(":")
        dispute_id = int(parts[2])
        decision = parts[3]
        source = parts[4]
        page = int(parts[5]) if len(parts) > 5 else 0
        result = game.resolve_dispute_with_source(callback.from_user.id, dispute_id, decision, source)
        remaining = game.dispute_payment_context(callback.from_user.id, dispute_id, decision)
        if remaining:
            await render_source(callback.message, game, callback.from_user.id, dispute_id, decision, page=page, flash=result)
            return
        await after(callback.message, callback.from_user.id, result, page)

    @router.callback_query(F.data.startswith("dispute:reject:"))
    async def reject(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = callback.data.split(":")
        dispute_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        result = game.resolve_dispute_with_source(callback.from_user.id, dispute_id, "reject", "none")
        await after(callback.message, callback.from_user.id, result, page)

    return router
