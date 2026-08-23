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

    def staff_keyboard(offer_id: int, product_id: int, staff) -> InlineKeyboardMarkup:
        rows = []
        for employee in staff:
            unsecured = int(employee.get("unsecured_after", 0))
            marker = "🔴" if unsecured else "✅"
            risk = f" · не покрыто {unsecured:,} ₽" if unsecured else " · покрыто"
            rows.append([InlineKeyboardButton(
                text=f"{marker} {employee['alias']}{risk}",
                callback_data=f"proc:staff:{offer_id}:{employee['id']}",
            )])
        rows.extend([
            [InlineKeyboardButton(text="← Предложение", callback_data=f"proc:offer:{offer_id}")],
            [InlineKeyboardButton(text="← Предложения", callback_data=f"proc:product:{product_id}")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def show_staff(target: Message, player_id: int, offer_id: int) -> None:
        offer = game.procurement_offer(player_id, offer_id)
        if not offer:
            await show_products(target, player_id)
            return
        staff = game.warehouse_staff_for_offer(player_id, offer_id)
        total = int(offer["quantity"] * offer["unit_cost"])
        text = (
            f"<b>🚚 Ответственный за партию</b>\n\n"
            f"{offer['product_title']} · ×{offer['quantity']}\n"
            f"Стоимость: <b>{total:,} ₽</b>\n\n"
            "Депозит не ограничивает размер партии. Если стоимость товара превысит депозит сотрудника, "
            "непокрытая часть повысит риск потери."
        )
        if not staff:
            text += "\n\n🔴 В команде нет активных оптовых сотрудников."
        await present(target, text, staff_keyboard(offer_id, int(offer["product_id"]), staff))

    async def show_purchase_confirmation(target: Message, player_id: int, offer_id: int, employee_id: int) -> None:
        offer = game.procurement_offer(player_id, offer_id)
        staff = game.warehouse_staff_for_offer(player_id, offer_id)
        employee = next((row for row in staff if int(row["id"]) == employee_id), None)
        if not offer or not employee:
            await show_staff(target, player_id, offer_id)
            return
        total = int(offer["quantity"] * offer["unit_cost"])
        unsecured = int(employee.get("unsecured_after", 0))
        risk_line = (
            f"\n🔴 После закупки не покрыто депозитом: <b>{unsecured:,} ₽</b>"
            if unsecured
            else "\n✅ Стоимость партии полностью покрыта депозитом."
        )
        text = (
            "<b>Подтвердить закупку?</b>\n\n"
            f"Товар: {offer['product_title']}\n"
            f"Объём: ×{offer['quantity']}\n"
            f"Стоимость: <b>{total:,} ₽</b>\n\n"
            f"Ответственный: <b>{employee['alias']}</b>\n"
            f"Текущая ответственность: {employee['exposure']:,} ₽\n"
            f"Депозит: {employee['deposit']:,} ₽"
            f"{risk_line}"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Купить", callback_data=f"proc:purchase:{offer_id}:{employee_id}")],
            [InlineKeyboardButton(text="← Выбрать сотрудника", callback_data=f"offer:{offer_id}")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ])
        await present(target, text, keyboard)

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

    @router.callback_query(
        F.data.startswith("offer:")
        & ~F.data.startswith("offer:staff:")
        & ~F.data.startswith("offer:purchase:")
        & ~F.data.startswith("offer:confirm:")
        & ~F.data.startswith("offer:buy:")
        & ~F.data.startswith("offer:no_coverage")
    )
    async def choose_staff(callback: CallbackQuery) -> None:
        parts = callback.data.split(":")
        if len(parts) != 2 or not parts[1].isdigit():
            return
        await callback.answer()
        await show_staff(callback.message, callback.from_user.id, int(parts[1]))

    @router.callback_query(F.data.startswith("proc:staff:"))
    async def staff_selected(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, offer_id, employee_id = callback.data.split(":")
        await show_purchase_confirmation(
            callback.message,
            callback.from_user.id,
            int(offer_id),
            int(employee_id),
        )

    @router.callback_query(F.data.startswith("proc:purchase:"))
    async def purchase(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, offer_id, employee_id = callback.data.split(":")
        offer = game.procurement_offer(callback.from_user.id, int(offer_id))
        product_id = int(offer["product_id"]) if offer else None
        result = game.buy_offer_for_employee(callback.from_user.id, int(offer_id), int(employee_id))
        rows = []
        if product_id is not None:
            rows.append([InlineKeyboardButton(text="← Предложения", callback_data=f"proc:product:{product_id}")])
        rows.append([InlineKeyboardButton(text="← Закупки", callback_data="menu:offers")])
        rows.append([InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")])
        await present(
            callback.message,
            f"<b>📦 Закупка</b>\n\n{result}",
            InlineKeyboardMarkup(inline_keyboard=rows),
        )

    return router
