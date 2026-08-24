from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .business_analytics import finance_text, normalize_period, overview_text, products_text
from .db import Database


VIEWS = {"overview", "products", "finance"}


def build_analytics_router(db: Database, game, simulation) -> Router:
    router = Router(name="analytics")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def period_row(view: str, period: str) -> list[InlineKeyboardButton]:
        return [
            InlineKeyboardButton(
                text=("✓ " if period == "7" else "") + "7 дней",
                callback_data=f"analytics:view:{view}:7",
            ),
            InlineKeyboardButton(
                text=("✓ " if period == "30" else "") + "30 дней",
                callback_data=f"analytics:view:{view}:30",
            ),
        ]

    def view_keyboard(view: str, period: str) -> InlineKeyboardMarkup:
        period = normalize_period(period)
        if view == "products":
            rows = [
                [
                    InlineKeyboardButton(text="📊 Обзор", callback_data=f"analytics:view:overview:{period}"),
                    InlineKeyboardButton(text="💰 Деньги", callback_data=f"analytics:view:finance:{period}"),
                ],
                period_row(view, period),
                [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
            ]
        elif view == "finance":
            rows = [
                [InlineKeyboardButton(text="💸 Выплаты", callback_data="analytics:payroll")],
                [
                    InlineKeyboardButton(text="📊 Обзор", callback_data=f"analytics:view:overview:{period}"),
                    InlineKeyboardButton(text="📦 Товары", callback_data=f"analytics:view:products:{period}"),
                ],
                period_row(view, period),
                [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
            ]
        else:
            rows = [
                [
                    InlineKeyboardButton(text="📦 Товары", callback_data=f"analytics:view:products:{period}"),
                    InlineKeyboardButton(text="💰 Деньги", callback_data=f"analytics:view:finance:{period}"),
                ],
                [InlineKeyboardButton(text="👥 Команда", callback_data="menu:team")],
                period_row("overview", period),
                [
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"analytics:view:overview:{period}"),
                    InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
                ],
            ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def payroll_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Деньги", callback_data="analytics:view:finance:7")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ])

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
        await present(target, render(player_id, view, period), view_keyboard(view, period))

    @router.callback_query(F.data == "menu:analytics")
    async def analytics(callback: CallbackQuery) -> None:
        await callback.answer()
        await show(callback.message, callback.from_user.id, "overview", "7")

    @router.callback_query(F.data == "analytics:payroll")
    async def payroll(callback: CallbackQuery) -> None:
        await callback.answer()
        game.process_payroll(callback.from_user.id)
        await present(callback.message, game.payroll_summary(callback.from_user.id), payroll_keyboard())

    @router.callback_query(F.data.startswith("analytics:view:"))
    async def analytics_view(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        view = parts[2] if len(parts) > 2 else "overview"
        period = parts[3] if len(parts) > 3 else "7"
        await show(callback.message, callback.from_user.id, view, period)

    return router
