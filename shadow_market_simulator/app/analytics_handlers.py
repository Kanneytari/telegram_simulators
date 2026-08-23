from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .db import Database
from .detailed_analytics import normalize_period, section_text


DETAIL_SECTIONS = {
    "overview": "📈 Сводка",
    "daily": "📅 По дням",
    "products": "📦 По товарам",
    "finance": "💰 Финансы",
    "staff": "👥 Сотрудники",
    "quality": "⭐ Качество",
}


def build_analytics_router(db: Database, game, simulation) -> Router:
    router = Router(name="analytics")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📈 Детальная статистика", callback_data="analytics:detail:overview:30")],
            [InlineKeyboardButton(text="💸 Выплаты", callback_data="analytics:payroll")],
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:analytics"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ])

    def payroll_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Аналитика", callback_data="menu:analytics")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ])

    def detail_keyboard(section: str, period: str) -> InlineKeyboardMarkup:
        period = normalize_period(period)
        rows = [
            [
                InlineKeyboardButton(
                    text=("• " if section == "overview" else "") + DETAIL_SECTIONS["overview"],
                    callback_data=f"analytics:detail:overview:{period}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=("• " if section == "daily" else "") + DETAIL_SECTIONS["daily"],
                    callback_data=f"analytics:detail:daily:{period}",
                ),
                InlineKeyboardButton(
                    text=("• " if section == "products" else "") + DETAIL_SECTIONS["products"],
                    callback_data=f"analytics:detail:products:{period}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=("• " if section == "finance" else "") + DETAIL_SECTIONS["finance"],
                    callback_data=f"analytics:detail:finance:{period}",
                ),
                InlineKeyboardButton(
                    text=("• " if section == "staff" else "") + DETAIL_SECTIONS["staff"],
                    callback_data=f"analytics:detail:staff:{period}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=("• " if section == "quality" else "") + DETAIL_SECTIONS["quality"],
                    callback_data=f"analytics:detail:quality:{period}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=("✓ " if period == "7" else "") + "7 дней",
                    callback_data=f"analytics:detail:{section}:7",
                ),
                InlineKeyboardButton(
                    text=("✓ " if period == "30" else "") + "30 дней",
                    callback_data=f"analytics:detail:{section}:30",
                ),
                InlineKeyboardButton(
                    text=("✓ " if period == "all" else "") + "Всё время",
                    callback_data=f"analytics:detail:{section}:all",
                ),
            ],
            [
                InlineKeyboardButton(text="← Аналитика", callback_data="menu:analytics"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def text(player_id: int) -> str:
        simulation.advance(player_id)
        game.process_payroll(player_id)
        with db.connect() as conn:
            shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
            stats = conn.execute(
                """SELECT COUNT(*) orders,
                          COALESCE(SUM(revenue),0) revenue,
                          COALESCE(SUM(revenue-cost-employee_cost),0) profit,
                          COALESCE(SUM(employee_cost),0) wages
                   FROM orders
                   WHERE player_id=? AND created_at>=datetime('now','-7 day')""",
                (player_id,),
            ).fetchone()
            wholesale_wages = int(conn.execute(
                """SELECT COALESCE(SUM(amount),0)
                   FROM wholesale_delivery_payments
                   WHERE player_id=? AND created_at>=datetime('now','-7 day')""",
                (player_id,),
            ).fetchone()[0])
            disputes = int(conn.execute(
                "SELECT COUNT(*) FROM disputes WHERE player_id=? AND created_at>=datetime('now','-7 day')",
                (player_id,),
            ).fetchone()[0])
            compensation = conn.execute(
                """SELECT COALESCE(SUM(refund_amount),0) total,
                          COALESCE(SUM(CASE WHEN refund_source='shop' THEN refund_amount ELSE 0 END),0) shop_paid,
                          COALESCE(SUM(CASE WHEN refund_source='employee' THEN refund_amount ELSE 0 END),0) employee_paid
                   FROM disputes
                   WHERE player_id=? AND resolved_at IS NOT NULL
                     AND resolved_at>=datetime('now','-7 day')""",
                (player_id,),
            ).fetchone()
            reviews = conn.execute(
                """SELECT COUNT(*) count,
                          COALESCE(AVG(rating),0) avg,
                          COALESCE(SUM(CASE WHEN quality_sentiment='bad' THEN 1 ELSE 0 END),0) quality_bad,
                          COALESCE(SUM(CASE WHEN delivery_sentiment='bad' THEN 1 ELSE 0 END),0) delivery_bad
                   FROM reviews
                   WHERE player_id=? AND created_at>=datetime('now','-7 day')""",
                (player_id,),
            ).fetchone()
            weak_product = conn.execute(
                """SELECT p.title, COUNT(*) count, AVG(r.rating) avg
                   FROM reviews r JOIN products p ON p.id=r.product_id
                   WHERE r.player_id=? AND r.created_at>=datetime('now','-7 day')
                   GROUP BY p.id, p.title
                   ORDER BY AVG(r.rating), COUNT(*) DESC LIMIT 1""",
                (player_id,),
            ).fetchone()
            accrued = int(conn.execute(
                "SELECT COALESCE(SUM(wages_accrued),0) FROM employees WHERE player_id=?",
                (player_id,),
            ).fetchone()[0])
            payroll = conn.execute(
                """SELECT COALESCE(SUM(cash_paid),0) cash,
                          COALESCE(SUM(deposit_added),0) deposit
                   FROM payroll_runs
                   WHERE player_id=? AND created_at>=datetime('now','-7 day')""",
                (player_id,),
            ).fetchone()

        adjusted_profit = int(stats["profit"]) - wholesale_wages
        total_wages = int(stats["wages"]) + wholesale_wages
        margin = adjusted_profit / stats["revenue"] * 100 if stats["revenue"] else 0.0
        dispute_rate = disputes / stats["orders"] * 100 if stats["orders"] else 0.0
        review_block = (
            f"Отзывов: {reviews['count']} · ⭐ {float(reviews['avg']):.2f}\n"
            f"Негатив по качеству: {reviews['quality_bad']}\n"
            f"Негатив по доставке: {reviews['delivery_bad']}"
        )
        if weak_product:
            review_block += f"\nСлабее всего: {weak_product['title']} · ⭐ {float(weak_product['avg']):.2f}"

        return (
            "<b>📊 Аналитика · 7 дней</b>\n\n"
            "<b>Продажи</b>\n"
            f"Заказов: {stats['orders']}\n"
            f"Выручка: <b>{stats['revenue']:,} ₽</b>\n"
            f"Расчётная прибыль: {adjusted_profit:,} ₽ ({margin:.1f}%)\n\n"
            "<b>Отзывы</b>\n"
            f"{review_block}\n\n"
            "<b>Диспуты</b>\n"
            f"Открыто за период: {disputes} ({dispute_rate:.1f}% заказов)\n"
            f"Компенсации: <b>{compensation['total']:,} ₽</b>\n"
            f"За счёт магазина: {compensation['shop_paid']:,} ₽\n"
            f"Из депозитов сотрудников: {compensation['employee_paid']:,} ₽\n\n"
            "<b>Персонал</b>\n"
            f"Начислено зарплаты: {total_wages:,} ₽\n"
            f"Выплачено деньгами: {payroll['cash']:,} ₽\n"
            f"В депозиты: {payroll['deposit']:,} ₽\n"
            f"К ближайшей выплате: <b>{accrued:,} ₽</b>\n\n"
            f"⭐ Рейтинг магазина: {shop['rating']:.2f}"
        )

    @router.callback_query(F.data == "menu:analytics")
    async def analytics(callback: CallbackQuery) -> None:
        await callback.answer()
        await present(callback.message, text(callback.from_user.id), keyboard())

    @router.callback_query(F.data == "analytics:payroll")
    async def payroll(callback: CallbackQuery) -> None:
        await callback.answer()
        game.process_payroll(callback.from_user.id)
        await present(callback.message, game.payroll_summary(callback.from_user.id), payroll_keyboard())

    @router.callback_query(F.data.startswith("analytics:detail:"))
    async def detailed(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        section = parts[2] if len(parts) > 2 and parts[2] in DETAIL_SECTIONS else "overview"
        period = normalize_period(parts[3] if len(parts) > 3 else "30")
        simulation.advance(callback.from_user.id)
        game.process_payroll(callback.from_user.id)
        await present(
            callback.message,
            section_text(db, callback.from_user.id, section, period),
            detail_keyboard(section, period),
        )

    return router
