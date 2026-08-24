from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .customer_trust import trust_band


def _stars(value: float) -> str:
    return f"{value:.2f}/5" if value > 0 else "пока нет данных"


def build_customer_trust_router(game, simulation) -> Router:
    router = Router(name="customer-trust")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def root_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:customers")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ])

    async def show_root(target: Message, player_id: int) -> None:
        simulation.advance(player_id)
        metrics = game.customer_metrics(player_id)
        trust = float(metrics["trust_score"])
        premium = float(metrics["premium_allowance"]) * 100.0
        product = float(metrics["product_rating"])
        courier = float(metrics["courier_rating"])
        availability = float(metrics["availability"]) * 100.0
        fairness = float(metrics["fairness"]) * 100.0
        repeat_share = float(metrics["repeat_order_share"]) * 100.0
        text = (
            "<b>🤝 Клиенты и доверие</b>\n\n"
            f"Доверие магазина: <b>{trust:.0f}/100</b> · {trust_band(trust)}\n"
            f"Качество товара: <b>{_stars(product)}</b>\n"
            f"Работа курьеров: <b>{_stars(courier)}</b>\n"
            f"Стабильность наличия: <b>{availability:.0f}%</b>\n"
            f"Работа с клиентскими кейсами: <b>{fairness:.0f}%</b>\n\n"
            "<b>Клиентская база</b>\n"
            f"Покупателей: {metrics['buyers']}\n"
            f"Покупали повторно: <b>{metrics['repeat_clients']}</b>\n"
            f"Постоянных клиентов: <b>{metrics['regulars']}</b>\n"
            f"Повторных заказов: {metrics['repeat_orders']} ({repeat_share:.1f}%)\n"
            f"Средний LTV покупателя: {metrics['avg_ltv']:,.0f} ₽\n\n"
            "<b>Что это даёт</b>\n"
            "Высокое доверие и постоянные клиенты увеличивают органический спрос и снижают "
            "чувствительность к цене. Сейчас магазин способен удерживать примерно "
            f"<b>+{premium:.0f}%</b> к базовой рыночной цене без обычного штрафа за наценку.\n\n"
            "Ключевой цикл: хорошее качество + аккуратные курьеры + постоянное наличие + "
            "разумные решения по честным клиентам → повторные покупки → доверие → больше продаж и выше допустимая наценка."
        )
        await present(target, text, root_keyboard())

    @router.callback_query(F.data == "menu:customers")
    async def customers(callback: CallbackQuery) -> None:
        await callback.answer()
        await show_root(callback.message, callback.from_user.id)

    return router
