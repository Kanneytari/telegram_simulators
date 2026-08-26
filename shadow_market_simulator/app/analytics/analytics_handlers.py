from __future__ import annotations

from app.presentation.vocabulary import HOME, button
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .business_analytics import finance_text, normalize_period, overview_text, products_text
from .db import Database
from .ui_common import present


VIEWS = {"overview", "products", "finance"}


def analytics_view_keyboard(view: str, period: str) -> InlineKeyboardMarkup:
    period = normalize_period(period)
    view = view if view in VIEWS else "overview"
    labels = (("overview", "📊 Обзор"), ("products", "📦 Товары"), ("finance", "💰 Деньги"))
    rows = [
        [
            InlineKeyboardButton(
                text=("✓ " if view == key else "") + label,
                callback_data=f"analytics:view:{key}:{period}",
            )
            for key, label in labels
        ],
        [
            InlineKeyboardButton(
                text=("✓ " if period == "7" else "") + "7 дней",
                callback_data=f"analytics:view:{view}:7",
            ),
            InlineKeyboardButton(
                text=("✓ " if period == "30" else "") + "30 дней",
                callback_data=f"analytics:view:{view}:30",
            ),
        ],
    ]
    if view == "finance":
        rows.append([InlineKeyboardButton(text="💸 Выплаты", callback_data=f"analytics:payroll:{period}")])
    rows.append([button(HOME)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def analytics_payroll_keyboard(period: str) -> InlineKeyboardMarkup:
    period = normalize_period(period)
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💰 Деньги", callback_data=f"analytics:view:finance:{period}"),
        button(HOME),
    ]])


def build_analytics_router(db: Database, game, simulation) -> Router:
    router = Router(name="analytics")

    def render(player_id: int, view: str, period: str) -> str:
        if view == "products":
            return products_text(db, player_id, period)
        if view == "finance":
            return finance_text(db, player_id, period)
        return overview_text(db, player_id, period)

    async def show(target: Message, player_id: int, view: str, period: str) -> None:
        period = normalize_period(period)
        view = view if view in VIEWS else "overview"
        simulation.advance(player_id)
        game.process_payroll(player_id)
        text = render(player_id, view, period).replace(" · сравнение появится позже", "")
        await present(target, text, analytics_view_keyboard(view, period))

    @router.callback_query(F.data == "menu:analytics")
    async def analytics(callback: CallbackQuery) -> None:
        await callback.answer()
        await show(callback.message, callback.from_user.id, "overview", "7")

    @router.callback_query(F.data.startswith("analytics:payroll:"))
    async def payroll(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        period = normalize_period(parts[2] if len(parts) > 2 else "7")
        game.process_payroll(callback.from_user.id)
        await present(
            callback.message,
            game.payroll_summary(callback.from_user.id),
            analytics_payroll_keyboard(period),
        )

    @router.callback_query(F.data.startswith("analytics:view:"))
    async def analytics_view(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        view = parts[2] if len(parts) > 2 else "overview"
        period = parts[3] if len(parts) > 3 else "7"
        await show(callback.message, callback.from_user.id, view, period)

    return router
