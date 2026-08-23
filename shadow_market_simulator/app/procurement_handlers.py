from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .procurement_market import PROCUREMENT_BATCH_SIZES, ROTATION_MINUTES


def build_procurement_router(game) -> Router:
    router = Router(name="procurement-market")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def products_keyboard(products) -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton(
                text=f"{product['title']} · {product['total']} предлож.",
                callback_data=f"proc:product:{product['id']}",
            )]
            for product in products
        ]
        rows.extend([
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:offers")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def show_products(target: Message, player_id: int) -> None:
        products = game.procurement_products(player_id)
        lines = [
            "<b>📦 Закупки</b>",
            "",
            "Сначала выбери товар. Число доступных предложений меняется со временем.",
            "",
        ]
        for product in products:
            counts = " · ".join(f"×{size}: {product['counts'][size]}" for size in PROCUREMENT_BATCH_SIZES)
            lines.append(f"<b>{product['title']}</b>\n{counts}")
        lines.extend([
            "",
            f"Рынок частично обновляется каждые {ROTATION_MINUTES} минут реального времени.",
        ])
        await present(target, "\n\n".join(lines), products_keyboard(products))

    def offer_marker(profile: str) -> str:
        return {
            "bargain": "💎",
            "dubious": "⚠️",
            "premium": "⭐",
        }.get(profile, "▫️")

    def offers_keyboard(product_id: int, offers) -> InlineKeyboardMarkup:
        rows = []
        for offer in offers:
            total = int(offer["quantity"] * offer["unit_cost"])
            quality = float(offer["resolved_quality_mean"])
            reliability = float(offer["resolved_reliability"]) * 100
            rows.append([InlineKeyboardButton(
                text=(
                    f"{offer_marker(str(offer['market_profile']))} ×{offer['quantity']} · "
                    f"{total:,} ₽ · Q{quality:.0f} · {reliability:.0f}%"
                ),
                callback_data=f"proc:offer:{offer['id']}",
            )])
        rows.extend([
            [InlineKeyboardButton(text="← Товары", callback_data="menu:offers")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def show_product(target: Message, player_id: int, product_id: int) -> None:
        offers = game.offers(player_id, product_id)
        with game.db.connect() as conn:
            product = conn.execute("SELECT title FROM products WHERE id=? AND active=1", (product_id,)).fetchone()
        if not product:
            await show_products(target, player_id)
            return

        counts = {size: 0 for size in PROCUREMENT_BATCH_SIZES}
        for offer in offers:
            counts[int(offer["quantity"])] = counts.get(int(offer["quantity"]), 0) + 1
        breakdown = " · ".join(f"×{size}: {counts[size]}" for size in PROCUREMENT_BATCH_SIZES)
        text = (
            f"<b>📦 {product['title']}</b>\n\n"
            f"Доступно: <b>{len(offers)}</b> предложений\n"
            f"{breakdown}\n\n"
            "На кнопке: объём партии · общая цена · ожидаемое качество · надёжность.\n"
            "Большинство предложений близки к рынку, но иногда встречаются заметные выбросы."
        )
        await present(target, text, offers_keyboard(product_id, offers))

    def offer_keyboard(product_id: int, offer_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Выбрать ответственного", callback_data=f"offer:{offer_id}")],
            [InlineKeyboardButton(text="← Предложения", callback_data=f"proc:product:{product_id}")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ])

    async def show_offer(target: Message, player_id: int, offer_id: int) -> None:
        offer = game.procurement_offer(player_id, offer_id)
        if not offer:
            await present(
                target,
                "Предложение больше недоступно — рынок уже обновился.",
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="← Закупки", callback_data="menu:offers")],
                    [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
                ]),
            )
            return

        typical = game.offer_typical_unit_cost(offer)
        delta = (float(offer["unit_cost"]) / typical - 1.0) * 100.0 if typical else 0.0
        quality = float(offer["resolved_quality_mean"])
        sigma = float(offer["resolved_quality_sigma"])
        reliability = float(offer["resolved_reliability"]) * 100.0
        total = int(offer["quantity"] * offer["unit_cost"])
        marker = offer_marker(str(offer["market_profile"]))

        text = (
            f"<b>{marker} {offer['product_title']} · ×{offer['quantity']}</b>\n\n"
            f"Поставщик: <b>{offer['supplier_title']}</b>\n\n"
            f"Цена за единицу: {offer['unit_cost']:,} ₽\n"
            f"Общая стоимость: <b>{total:,} ₽</b>\n"
            f"К типичной цене этого объёма: <b>{delta:+.1f}%</b>\n\n"
            f"Ожидаемое качество: <b>~{quality:.0f}/100</b>\n"
            f"Неопределённость качества: ±{sigma:.0f}\n"
            f"Надёжность предложения: <b>~{reliability:.0f}%</b>\n\n"
            "Фактическое качество партии может отличаться от предварительной оценки."
        )
        await present(target, text, offer_keyboard(int(offer["product_id"]), offer_id))

    @router.callback_query(F.data == "menu:offers")
    @router.callback_query(F.data == "offers:list")
    async def procurement_root(callback: CallbackQuery) -> None:
        await callback.answer()
        await show_products(callback.message, callback.from_user.id)

    @router.callback_query(F.data.startswith("proc:product:"))
    async def product_offers(callback: CallbackQuery) -> None:
        await callback.answer()
        product_id = int(callback.data.split(":")[2])
        await show_product(callback.message, callback.from_user.id, product_id)

    @router.callback_query(F.data.startswith("proc:offer:"))
    async def offer_details(callback: CallbackQuery) -> None:
        await callback.answer()
        offer_id = int(callback.data.split(":")[2])
        await show_offer(callback.message, callback.from_user.id, offer_id)

    return router
