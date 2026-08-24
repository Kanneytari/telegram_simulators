from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .db import Database


def build_storefront_router(db: Database, game, simulation) -> Router:
    router = Router(name="storefront")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def product_rows(player_id: int):
        with db.connect() as conn:
            return conn.execute(
                """SELECT p.id, p.title,
                          COALESCE((SELECT SUM(rp.position_count*rp.pack_size)
                                    FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
                                    WHERE rp.player_id=? AND rp.product_id=p.id
                                      AND rp.position_count>0 AND e.active=1),0) stock,
                          COALESCE((SELECT COUNT(*) FROM order_ratings r
                                    WHERE r.player_id=? AND r.product_id=p.id),0) rating_count,
                          COALESCE((SELECT AVG(r.product_rating) FROM order_ratings r
                                    WHERE r.player_id=? AND r.product_id=p.id),0) quality_avg
                   FROM products p
                   WHERE p.active=1
                     AND EXISTS (SELECT 1 FROM listings l
                                 WHERE l.player_id=? AND l.product_id=p.id AND l.active=1)
                   ORDER BY p.id""",
                (player_id, player_id, player_id, player_id),
            ).fetchall()

    def product_listings(player_id: int, product_id: int):
        with db.connect() as conn:
            product = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (product_id,)).fetchone()
            if not product:
                return None, [], 0, 0.0, 0
            published_units = int(conn.execute(
                """SELECT COALESCE(SUM(rp.position_count*rp.pack_size),0)
                   FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
                   WHERE rp.player_id=? AND rp.product_id=? AND rp.position_count>0 AND e.active=1""",
                (player_id, product_id),
            ).fetchone()[0])
            quality_stats = conn.execute(
                """SELECT COUNT(*) count, COALESCE(AVG(product_rating),0) avg
                   FROM order_ratings WHERE player_id=? AND product_id=?""",
                (player_id, product_id),
            ).fetchone()
            listings = conn.execute(
                """SELECT l.*,
                          COALESCE((SELECT SUM(rp.position_count)
                                    FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
                                    WHERE rp.player_id=l.player_id
                                      AND rp.product_id=l.product_id
                                      AND rp.pack_size=l.pack_size
                                      AND rp.position_count>0 AND e.active=1),0) positions
                   FROM listings l
                   WHERE l.player_id=? AND l.product_id=? AND l.active=1
                   ORDER BY l.pack_size""",
                (player_id, product_id),
            ).fetchall()
        return product, listings, published_units, float(quality_stats["avg"]), int(quality_stats["count"])

    def listing_context(player_id: int, listing_id: int):
        with db.connect() as conn:
            row = conn.execute(
                """SELECT l.*, p.title, p.base_market_price,
                          COALESCE((SELECT SUM(rp.position_count)
                                    FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
                                    WHERE rp.player_id=l.player_id AND rp.product_id=l.product_id
                                      AND rp.pack_size=l.pack_size AND rp.position_count>0 AND e.active=1),0) positions,
                          COALESCE((SELECT SUM(rp.position_count*rp.pack_size)
                                    FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
                                    WHERE rp.player_id=l.player_id AND rp.product_id=l.product_id
                                      AND rp.position_count>0 AND e.active=1),0) published_units
                   FROM listings l JOIN products p ON p.id=l.product_id
                   WHERE l.id=? AND l.player_id=? AND l.active=1""",
                (listing_id, player_id),
            ).fetchone()
        return row

    def root_keyboard(rows) -> InlineKeyboardMarkup:
        buttons = []
        for row in rows:
            quality = f" · 🧪 {float(row['quality_avg']):.1f}" if int(row["rating_count"]) else ""
            buttons.append([InlineKeyboardButton(
                text=f"{row['title']} · {int(row['stock'])} ед.{quality}",
                callback_data=f"store:product:{row['id']}",
            )])
        buttons.append([InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def product_keyboard(product_id: int, listings) -> InlineKeyboardMarkup:
        rows = []
        for listing in listings:
            rows.append([InlineKeyboardButton(
                text=f"×{listing['pack_size']} · {listing['price']:,} ₽ · {int(listing['positions'])} поз.",
                callback_data=f"store:listing:{listing['id']}",
            )])
        rows.append([
            InlineKeyboardButton(text="← Товары", callback_data="menu:listings"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def listing_keyboard(listing_id: int, product_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="−5%", callback_data=f"store:price:{listing_id}:-5"),
                InlineKeyboardButton(text="+5%", callback_data=f"store:price:{listing_id}:5"),
            ],
            [
                InlineKeyboardButton(text="← Фасовки", callback_data=f"store:product:{product_id}"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ])

    async def render_root(target: Message, player_id: int) -> None:
        simulation.advance(player_id)
        rows = product_rows(player_id)
        trust = game.customer_metrics(player_id)
        text = (
            "<b>🏷 Витрина</b>\n\n"
            f"Доверие магазина: <b>{trust['trust_score']:.0f}/100</b>\n"
            f"Текущая допустимая премия к рынку: <b>~+{trust['premium_allowance'] * 100:.0f}%</b>\n\n"
            "Выбери товар. 🧪 на кнопке — отдельная покупательская оценка качества продукции. "
            "Она не зависит от работы курьера."
        )
        await present(target, text, root_keyboard(rows))

    async def render_product(target: Message, player_id: int, product_id: int) -> None:
        simulation.advance(player_id)
        product, listings, published_units, quality_avg, rating_count = product_listings(player_id, product_id)
        if not product:
            await render_root(target, player_id)
            return
        quality_line = (
            f"🧪 Качество: <b>{quality_avg:.2f}/5</b> · {rating_count} оценок"
            if rating_count else
            "🧪 Качество: пока нет оценок"
        )
        text = (
            f"<b>{product['title']}</b>\n\n"
            f"На витрине: <b>{published_units} ед.</b>\n"
            f"{quality_line}\n\n"
            "Оценка формируется только из качества проданных партий. Цена и работа курьера её не изменяют.\n\n"
            "Выбери фасовку. Число «поз.» — текущее количество готовых позиций, ожидающих продажи."
        )
        await present(target, text, product_keyboard(product_id, listings))

    async def render_listing(target: Message, player_id: int, listing_id: int) -> None:
        row = listing_context(player_id, listing_id)
        if not row:
            await render_root(target, player_id)
            return
        trust = game.customer_metrics(player_id)
        unit_price = row["price"] / max(1, row["pack_size"])
        market_delta = (unit_price / row["base_market_price"] - 1.0) * 100.0
        allowance = float(trust["premium_allowance"]) * 100.0
        if market_delta <= allowance + 0.01:
            price_hint = "✅ Цена находится в диапазоне, который текущая клиентская база переносит относительно спокойно."
        else:
            price_hint = "⚠️ Наценка выше текущего уровня доверия — спрос начнёт снижаться заметнее."
        text = (
            f"<b>{row['title']} · ×{row['pack_size']}</b>\n\n"
            "<b>Продажа</b>\n"
            f"Цена: <b>{row['price']:,} ₽</b>\n"
            f"За единицу: {unit_price:,.0f} ₽\n"
            f"К базовой цене: <b>{market_delta:+.1f}%</b>\n\n"
            "<b>Доверие и цена</b>\n"
            f"Доверие магазина: {trust['trust_score']:.0f}/100\n"
            f"Допустимая премия: ~+{allowance:.0f}%\n"
            f"{price_hint}\n\n"
            "<b>Витрина</b>\n"
            f"Всего опубликовано: {int(row['published_units'])} ед.\n"
            f"Ожидают продажи в этой фасовке: <b>{int(row['positions'])} поз.</b>"
        )
        await present(target, text, listing_keyboard(listing_id, int(row["product_id"])))

    @router.callback_query(F.data == "menu:listings")
    async def storefront_root(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_root(callback.message, callback.from_user.id)

    @router.callback_query(F.data.startswith("store:product:"))
    async def storefront_product(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_product(callback.message, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("store:listing:"))
    async def storefront_listing(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_listing(callback.message, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("store:price:"))
    async def storefront_price(callback: CallbackQuery) -> None:
        _, _, listing_id, percent = callback.data.split(":")
        result = game.change_listing_price(callback.from_user.id, int(listing_id), int(percent))
        await callback.answer(result)
        await render_listing(callback.message, callback.from_user.id, int(listing_id))

    return router
