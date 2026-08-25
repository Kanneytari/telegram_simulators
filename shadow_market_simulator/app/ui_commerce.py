from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .ui_common import claim_tip, clean, money, nav_row, notice, present, rating, tutorial_hint


def _quality_label(value: float) -> str:
    if value >= 88:
        return "отличное"
    if value >= 76:
        return "хорошее"
    if value >= 62:
        return "среднее"
    return "низкое"


def _offer_marker(profile: str) -> str:
    return {"bargain": "💎 ", "dubious": "⚠️ ", "premium": "⭐ "}.get(profile, "")


def _stock_status(db, player_id: int, product_id: int) -> str:
    with db.connect() as conn:
        sold = int(conn.execute(
            """SELECT COALESCE(SUM(quantity),0) FROM orders
               WHERE player_id=? AND product_id=? AND created_at>=datetime('now','-7 day')""",
            (player_id, product_id),
        ).fetchone()[0])
        warehouse = int(conn.execute(
            """SELECT COALESCE(SUM(remaining),0) FROM batches
               WHERE player_id=? AND product_id=? AND status IN ('receiving','warehouse')""",
            (player_id, product_id),
        ).fetchone()[0])
        transit = int(conn.execute(
            """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
               WHERE player_id=? AND product_id=? AND status IN ('waiting','preparing')""",
            (player_id, product_id),
        ).fetchone()[0])
        ready = int(conn.execute(
            """SELECT COALESCE(SUM(rp.position_count*rp.pack_size),0)
               FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
               WHERE rp.player_id=? AND rp.product_id=? AND rp.position_count>0 AND e.active=1""",
            (player_id, product_id),
        ).fetchone()[0])
    stock = warehouse + transit + ready
    if stock <= 0:
        return "нет запаса"
    if sold <= 0:
        return f"{stock} ед."
    days = stock / (sold / 7.0)
    return f"~{max(1, round(days))} дн."


def _procurement_products_keyboard(db, player_id: int, products) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for product in products:
        status = _stock_status(db, player_id, int(product["id"]))
        text = str(product["title"])
        if status != "нет запаса":
            text += f" · 🚚 {status}"
        rows.append([
            InlineKeyboardButton(
                text=text,
                callback_data=f"proc:product:{product['id']}",
            )
        ])

    with db.connect() as conn:
        batch_count = int(conn.execute(
            """SELECT COUNT(*) FROM batches
               WHERE player_id=? AND status IN ('receiving','warehouse') AND remaining>0""",
            (player_id,),
        ).fetchone()[0])
    rows.append([InlineKeyboardButton(text=f"📦 Склад · {batch_count}", callback_data="team:batches")])
    rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_product_root(target: Message, db, game, player_id: int, *, flash: str | None = None) -> None:
    products = game.procurement_products(player_id)
    with db.connect() as conn:
        free_cash = game._free_cash_conn(conn, player_id) if hasattr(game, "_free_cash_conn") else int(
            conn.execute("SELECT balance FROM shops WHERE player_id=?", (player_id,)).fetchone()[0]
        )
    body = f"<b>📦 Товар</b>\n\nСвободно: <b>{money(free_cash)}</b>"
    if game.needs_first_handoff_tutorial(player_id):
        body += "\n\n" + tutorial_hint("Нажми на кнопку 🚚 Склад")
    await present(target, notice(flash, body), _procurement_products_keyboard(db, player_id, products))


def _offers_keyboard(product_id: int, offers) -> InlineKeyboardMarkup:
    rows = []
    for offer in offers:
        total = int(offer["quantity"] * offer["unit_cost"])
        quality = _quality_label(float(offer["resolved_quality_mean"]))
        rows.append([InlineKeyboardButton(
            text=f"{_offer_marker(str(offer['market_profile']))}×{offer['quantity']} · {money(total)} · {quality}",
            callback_data=f"proc:offer:{offer['id']}",
        )])
    rows.append(nav_row("menu:product", "← Товар"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_procurement_product(target: Message, game, player_id: int, product_id: int, *, flash: str | None = None) -> None:
    offers = game.offers(player_id, product_id)
    with game.db.connect() as conn:
        product = conn.execute("SELECT title FROM products WHERE id=? AND active=1", (product_id,)).fetchone()
    if not product:
        await render_product_root(target, game.db, game, player_id, flash=flash)
        return
    body = f"<b>📦 {clean(product['title'])}</b>\n\nДоступно: {len(offers)} предложений."
    await present(target, notice(flash, body), _offers_keyboard(product_id, offers))


def _best_warehouse(staff):
    if not staff:
        return None
    return min(
        staff,
        key=lambda row: (
            int(row.get("unsecured_after", 0)) > 0,
            int(row.get("unsecured_after", 0)),
            int(row.get("exposure", 0)),
            -int(row.get("deposit", 0)),
        ),
    )


def _offer_keyboard(offer_id: int, product_id: int, selected, staff) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if selected:
        rows.append([InlineKeyboardButton(
            text=f"Купить · {money(int(selected['required']))}",
            callback_data=f"proc:buy:{offer_id}:{selected['id']}",
        )])
        if len(staff) > 1:
            rows.append([InlineKeyboardButton(text="Сменить складмена", callback_data=f"proc:staff:{offer_id}")])
    else:
        rows.append([InlineKeyboardButton(text="Нанять сотрудника", callback_data="team:recruit")])
    rows.append(nav_row(f"proc:product:{product_id}", "← Предложения"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_offer(target: Message, game, player_id: int, offer_id: int, employee_id: int | None = None) -> None:
    offer = game.procurement_offer(player_id, offer_id)
    if not offer:
        await render_product_root(target, game.db, game, player_id, flash="Предложение уже исчезло с рынка.")
        return
    typical = game.offer_typical_unit_cost(offer)
    delta = (float(offer["unit_cost"]) / typical - 1.0) * 100.0 if typical else 0.0
    quality = float(offer["resolved_quality_mean"])
    reliability = float(offer["resolved_reliability"]) * 100.0
    total = int(offer["quantity"] * offer["unit_cost"])
    staff = game.warehouse_staff_for_offer(player_id, offer_id)
    selected = next((row for row in staff if int(row["id"]) == int(employee_id or -1)), None) or _best_warehouse(staff)

    if delta < -0.5:
        price_relation = f"на {abs(delta):.0f}% дешевле обычного"
    elif delta > 0.5:
        price_relation = f"на {delta:.0f}% дороже обычного"
    else:
        price_relation = "около обычной цены"
    text = (
        f"<b>{clean(offer['product_title'])} · {offer['quantity']} ед.</b>\n\n"
        f"{money(total)} · {price_relation}\n"
        f"Качество: <b>{_quality_label(quality)}</b> · {quality:.0f}/100\n"
        f"Надёжность поставки: {reliability:.0f}%"
    )
    if selected:
        unsecured = int(selected.get("unsecured_after", 0))
        text += f"\n\nСкладмен: <b>{clean(selected['alias'])}</b>"
        if unsecured:
            text += f"\n🔴 Не покрыто депозитом: {money(unsecured)}"
            if claim_tip(game.db, player_id, "uncovered_stock"):
                text += "\n\n💡 Депозит сотрудника покрывает возможную потерю товара. Всё сверх депозита - риск магазина."
        else:
            text += "\n🟢 Товар полностью покрыт его депозитом."
    else:
        text += "\n\n🔴 Нет активного складмена."
    await present(target, text, _offer_keyboard(offer_id, int(offer["product_id"]), selected, staff))


async def render_offer_staff(target: Message, game, player_id: int, offer_id: int) -> None:
    offer = game.procurement_offer(player_id, offer_id)
    if not offer:
        await render_product_root(target, game.db, game, player_id, flash="Предложение уже недоступно.")
        return
    staff = game.warehouse_staff_for_offer(player_id, offer_id)
    rows = []
    for employee in staff:
        unsecured = int(employee.get("unsecured_after", 0))
        suffix = f" · 🔴 {money(unsecured)}" if unsecured else " · покрыто"
        rows.append([InlineKeyboardButton(
            text=f"{employee['alias']}{suffix}",
            callback_data=f"proc:offer:{offer_id}:{employee['id']}",
        )])
    rows.append(nav_row(f"proc:offer:{offer_id}", "← Предложение"))
    await present(
        target,
        f"<b>Складмен для закупки</b>\n\n{clean(offer['product_title'])} · {money(int(offer['quantity'] * offer['unit_cost']))}",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


def _sales_products(db, player_id: int):
    with db.connect() as conn:
        return conn.execute(
            """SELECT p.id, p.title,
                      COALESCE((SELECT SUM(rp.position_count*rp.pack_size)
                                FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
                                WHERE rp.player_id=? AND rp.product_id=p.id
                                  AND rp.position_count>0 AND e.active=1),0) stock,
                      COALESCE((SELECT COUNT(*) FROM order_ratings r
                                WHERE r.player_id=? AND r.product_id=p.id),0) rating_count,
                      COALESCE((SELECT AVG(product_rating) FROM order_ratings r
                                WHERE r.player_id=? AND r.product_id=p.id),0) quality_avg
               FROM products p
               WHERE p.active=1
                 AND EXISTS (SELECT 1 FROM listings l WHERE l.player_id=? AND l.product_id=p.id AND l.active=1)
               ORDER BY p.id""",
            (player_id, player_id, player_id, player_id),
        ).fetchall()


def _sales_root_keyboard(rows) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(
        text=f"{row['title']} · {int(row['stock'])} ед. · {rating(float(row['quality_avg']), int(row['rating_count']))}",
        callback_data=f"sales:product:{row['id']}",
    )] for row in rows]
    buttons.append([
        InlineKeyboardButton(text="⚙️ Фасовки", callback_data="sales:packaging"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def render_storefront_root(target: Message, db, game, simulation, player_id: int) -> None:
    simulation.advance(player_id)
    rows = _sales_products(db, player_id)
    trust = game.customer_metrics(player_id)
    text = (
        "<b>🏷 Витрина</b>\n\n"
        f"Доверие: {trust['trust_score']:.0f}/100\n"
        f"Наценка до ~+{trust['premium_allowance'] * 100:.0f}% обычно не снижает спрос."
    )
    await present(target, text, _sales_root_keyboard(rows))


def _product_listings(db, player_id: int, product_id: int):
    with db.connect() as conn:
        product = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (product_id,)).fetchone()
        if not product:
            return None, [], 0, 0.0, 0
        published = int(conn.execute(
            """SELECT COALESCE(SUM(rp.position_count*rp.pack_size),0)
               FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
               WHERE rp.player_id=? AND rp.product_id=? AND rp.position_count>0 AND e.active=1""",
            (player_id, product_id),
        ).fetchone()[0])
        stats = conn.execute(
            "SELECT COUNT(*) n, COALESCE(AVG(product_rating),0) avg FROM order_ratings WHERE player_id=? AND product_id=?",
            (player_id, product_id),
        ).fetchone()
        listings = conn.execute(
            """SELECT l.*,
                      COALESCE((SELECT SUM(rp.position_count)
                                FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
                                WHERE rp.player_id=l.player_id AND rp.product_id=l.product_id
                                  AND rp.pack_size=l.pack_size AND rp.position_count>0 AND e.active=1),0) positions
               FROM listings l WHERE l.player_id=? AND l.product_id=? AND l.active=1 ORDER BY l.pack_size""",
            (player_id, product_id),
        ).fetchall()
    return product, listings, published, float(stats["avg"]), int(stats["n"])


async def render_sales_product(target: Message, db, player_id: int, product_id: int) -> None:
    product, listings, published, avg, n = _product_listings(db, player_id, product_id)
    if not product:
        return
    rows = [[InlineKeyboardButton(
        text=f"×{listing['pack_size']} · {money(listing['price'])} · доступно {int(listing['positions'])}",
        callback_data=f"sales:listing:{listing['id']}",
    )] for listing in listings]
    rows.append(nav_row("menu:storefront", "← Витрина"))
    await present(
        target,
        f"<b>{clean(product['title'])}</b>\n\n{published} ед. готовы к продаже · оценка {rating(avg, n)}",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


def _listing_context(db, player_id: int, listing_id: int):
    with db.connect() as conn:
        return conn.execute(
            """SELECT l.*, p.title, p.base_market_price,
                      COALESCE((SELECT SUM(rp.position_count)
                                FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
                                WHERE rp.player_id=l.player_id AND rp.product_id=l.product_id
                                  AND rp.pack_size=l.pack_size AND rp.position_count>0 AND e.active=1),0) positions
               FROM listings l JOIN products p ON p.id=l.product_id
               WHERE l.id=? AND l.player_id=? AND l.active=1""",
            (listing_id, player_id),
        ).fetchone()


async def render_listing(target: Message, db, game, player_id: int, listing_id: int) -> None:
    row = _listing_context(db, player_id, listing_id)
    if not row:
        return
    trust = game.customer_metrics(player_id)
    unit_price = float(row["price"]) / max(1, int(row["pack_size"]))
    delta = (unit_price / float(row["base_market_price"]) - 1.0) * 100.0
    allowance = float(trust["premium_allowance"]) * 100.0
    status = "нормально" if delta <= allowance + 0.01 else "спрос будет снижаться"
    text = (
        f"<b>{clean(row['title'])} · ×{row['pack_size']}</b>\n\n"
        f"Цена: <b>{money(row['price'])}</b> · рынок ~{money(row['base_market_price'] * row['pack_size'])}\n"
        f"Наценка: {delta:+.0f}%\n\n"
        f"При текущем доверии до ~+{allowance:.0f}% переносится нормально · <b>{status}</b>.\n\n"
        f"Доступно: {int(row['positions'])}"
    )
    await present(target, text, InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="−5%", callback_data=f"sales:price:{listing_id}:-5"),
            InlineKeyboardButton(text="+5%", callback_data=f"sales:price:{listing_id}:5"),
        ],
        nav_row(f"sales:product:{row['product_id']}", f"← {str(row['title'])[:18]}"),
    ]))


def packaging_keyboard(rule) -> InlineKeyboardMarkup:
    rows = []
    for size in (1, 2, 5):
        rows.append([
            InlineKeyboardButton(text=f"×{size} −10", callback_data=f"sales:packadj:{size}:-10"),
            InlineKeyboardButton(text=f"×{size} +10", callback_data=f"sales:packadj:{size}:10"),
        ])
    rows.append(nav_row("menu:storefront", "← Витрина"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_packaging(target: Message, game, player_id: int) -> None:
    rule = game.global_packaging_rule(player_id)
    text = (
        "<b>⚙️ Фасовки</b>\n\n"
        "Новые партии распределяются так:\n\n"
        f"×1 · <b>{rule['pct_1']}%</b>\n"
        f"×2 · <b>{rule['pct_2']}%</b>\n"
        f"×5 · <b>{rule['pct_5']}%</b>"
    )
    if claim_tip(game.db, player_id, "packaging"):
        text += "\n\n💡 Эти доли применяются к товару, который закладчики будут готовить к витрине после следующих передач."
    await present(target, text, packaging_keyboard(rule))


def build_commerce_router(db, game, simulation) -> Router:
    router = Router(name="compact-commerce")

    @router.callback_query(F.data == "menu:product")
    async def procurement(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_product_root(callback.message, db, game, callback.from_user.id)

    @router.callback_query(F.data.startswith("proc:product:"))
    async def product(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_procurement_product(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("proc:offer:"))
    async def offer(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = callback.data.split(":")
        await render_offer(callback.message, game, callback.from_user.id, int(parts[2]), int(parts[3]) if len(parts) > 3 else None)

    @router.callback_query(F.data.startswith("proc:staff:"))
    async def staff(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_offer_staff(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("proc:buy:"))
    async def buy(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, offer_raw, employee_raw = callback.data.split(":")
        offer = game.procurement_offer(callback.from_user.id, int(offer_raw))
        product_id = int(offer["product_id"]) if offer else None
        result = game.buy_offer_for_employee(callback.from_user.id, int(offer_raw), int(employee_raw))
        flash = result
        if product_id is None:
            await render_product_root(callback.message, db, game, callback.from_user.id, flash=flash)
        else:
            await render_procurement_product(callback.message, game, callback.from_user.id, product_id, flash=flash)

    @router.callback_query(F.data == "menu:storefront")
    async def sales(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_storefront_root(callback.message, db, game, simulation, callback.from_user.id)

    @router.callback_query(F.data.startswith("sales:product:"))
    async def sales_product(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_sales_product(callback.message, db, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("sales:listing:"))
    async def listing(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_listing(callback.message, db, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("sales:price:"))
    async def price(callback: CallbackQuery) -> None:
        _, _, listing_raw, delta_raw = callback.data.split(":")
        result = game.change_listing_price(callback.from_user.id, int(listing_raw), int(delta_raw))
        await callback.answer(result[:180])
        await render_listing(callback.message, db, game, callback.from_user.id, int(listing_raw))

    @router.callback_query(F.data == "sales:packaging")
    async def packaging(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_packaging(callback.message, game, callback.from_user.id)

    @router.callback_query(F.data.startswith("sales:packadj:"))
    async def pack_adjust(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, size_raw, delta_raw = callback.data.split(":")
        game.adjust_global_packaging_rule(callback.from_user.id, int(size_raw), int(delta_raw))
        await render_packaging(callback.message, game, callback.from_user.id)

    return router
