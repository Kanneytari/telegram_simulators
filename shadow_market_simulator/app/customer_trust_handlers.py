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

    @router.callback_query(F.data.startswith("store:reviews:"))
    async def legacy_product_reviews(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        if len(parts) < 3 or not parts[2].isdigit():
            return
        product_id = int(parts[2])
        metrics = game.product_quality_metrics(callback.from_user.id, product_id)
        with game.db.connect() as conn:
            product = conn.execute("SELECT title FROM products WHERE id=?", (product_id,)).fetchone()
        title = product["title"] if product else "Товар"
        text = (
            f"<b>🧪 Качество · {title}</b>\n\n"
            + (
                f"Оценка покупателей: <b>{metrics['rating']:.2f}/5</b>\n"
                f"Оценок: {metrics['count']}"
                if metrics["count"]
                else "Покупательских оценок пока нет."
            )
            + "\n\nТекстовые отзывы больше не используются: качество товара оценивается отдельно от работы курьера."
        )
        await present(
            callback.message,
            text,
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← Товар", callback_data=f"store:product:{product_id}")],
                [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
            ]),
        )

    @router.callback_query(F.data.startswith("employee:reviews:"))
    async def legacy_employee_reviews(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        if len(parts) < 3 or not parts[2].isdigit():
            return
        employee_id = int(parts[2])
        metrics = game.employee_service_metrics(callback.from_user.id, employee_id)
        with game.db.connect() as conn:
            employee = conn.execute(
                "SELECT alias, role FROM employees WHERE id=? AND player_id=?",
                (employee_id, callback.from_user.id),
            ).fetchone()
        if not employee:
            return
        if employee["role"] != "courier":
            body = "Для оптовых сотрудников покупательская оценка курьера не рассчитывается."
        elif metrics["count"]:
            body = (
                f"Оценка покупателей: <b>{metrics['rating']:.2f}/5</b>\n"
                f"Оценок: {metrics['count']}\n\n"
                "Эта метрика учитывает только качество работы курьера и не зависит от качества партии."
            )
        else:
            body = "Покупательских оценок работы пока нет."
        await present(
            callback.message,
            f"<b>👤 Работа · {employee['alias']}</b>\n\n{body}",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")],
                [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
            ]),
        )

    return router
