from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from .business_analytics import _comparison_ready, _order_metrics, _product_metrics, _window
from .runtime import STAFF_INBOX_KINDS
from .ui_common import clean, money, notice, present, signed_pct_change


def home_keyboard(opened: int, urgent: int, *, is_admin: bool = False) -> InlineKeyboardMarkup:
    inbox = f"📨 Входящие · {opened}"
    if urgent:
        inbox += f" · 🔴 {urgent}"
    rows = [
        [InlineKeyboardButton(text=inbox, callback_data="menu:inbox")],
        [
            InlineKeyboardButton(text="📦 Закупки", callback_data="menu:procurement"),
            InlineKeyboardButton(text="🏷 Продажа", callback_data="menu:sales"),
        ],
        [
            InlineKeyboardButton(text="👥 Команда", callback_data="menu:team"),
            InlineKeyboardButton(text="📊 Аналитика", callback_data="menu:analytics"),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Админ", callback_data="admin:panel")])
    rows.append([InlineKeyboardButton(text="Обновить", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _home_snapshot(db, game, simulation, player_id: int) -> tuple[str, int, int]:
    simulation.advance(player_id)
    game.process_payroll(player_id)
    window = _window("7")
    with db.connect() as conn:
        shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
        deposits = int(conn.execute(
            "SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1",
            (player_id,),
        ).fetchone()[0])
        wages = int(conn.execute(
            "SELECT COALESCE(SUM(wages_accrued),0) FROM employees WHERE player_id=? AND active=1",
            (player_id,),
        ).fetchone()[0])
        inbox = conn.execute(
            """SELECT COUNT(*) opened,
                      SUM(CASE WHEN priority IN ('important','urgent') THEN 1 ELSE 0 END) urgent
               FROM inbox WHERE player_id=? AND status='open'""",
            (player_id,),
        ).fetchone()
        current = _order_metrics(conn, player_id, window["current_start"], window["current_end"])
        previous = _order_metrics(conn, player_id, window["previous_start"], window["previous_end"])
        products = _product_metrics(conn, player_id, window["current_start"], window["current_end"], 7)
        stressed = conn.execute(
            """SELECT alias, stress FROM employees
               WHERE player_id=? AND active=1 AND role='courier' AND stress>=62
               ORDER BY stress DESC LIMIT 1""",
            (player_id,),
        ).fetchone()

    opened = int(inbox["opened"] or 0)
    urgent = int(inbox["urgent"] or 0)
    free_cash = int(shop["balance"]) - int(shop["reserve_target"]) - deposits - wages
    compare_ready = _comparison_ready(shop, window)
    earned_trend = signed_pct_change(current["earned"], previous["earned"]) if compare_ready else ""
    orders_trend = signed_pct_change(current["orders"], previous["orders"]) if compare_ready else ""

    alerts: list[str] = []
    if urgent:
        alerts.append(f"🔴 {urgent} событий требуют решения")
    if stressed:
        alerts.append(f"🟡 {clean(stressed['alias'])} перегружен")
    low_stock = [p for p in products if p.get("stock_days") is not None and float(p["stock_days"]) < 3.0]
    if low_stock:
        item = sorted(low_stock, key=lambda row: float(row["stock_days"]))[0]
        alerts.append(f"🟡 {clean(item['title'])}: запаса примерно на {max(1, round(float(item['stock_days'])))} дн.")
    if not alerts:
        alerts.append("Срочных проблем нет.")

    text = (
        f"<b>🌒 {clean(shop['name'])}</b>\n\n"
        f"На счёте <b>{money(shop['balance'])}</b> · можно потратить {money(free_cash)}\n"
        f"За 7 дней: <b>{money(current['earned'])}</b>{earned_trend} · "
        f"{current['orders']} заказов{orders_trend}\n\n"
        + "\n".join(alerts[:3])
    )
    return text, opened, urgent


def _inbox_items(game, player_id: int):
    return list(game.inbox(player_id, limit=8))


def inbox_keyboard(items) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        marker = "🔴 " if item["priority"] == "urgent" else "🟡 " if item["priority"] == "important" else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{marker}{str(item['title'])[:48]}",
                callback_data=f"inbox:item:{item['id']}",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="Обновить", callback_data="menu:inbox"),
        InlineKeyboardButton(text="Меню", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_inbox(target: Message, game, simulation, player_id: int, *, flash: str | None = None) -> None:
    simulation.advance(player_id)
    game.process_payroll(player_id)
    items = _inbox_items(game, player_id)
    important = sum(item["priority"] in {"urgent", "important"} for item in items)
    body = f"<b>📨 Входящие · {len(items)}</b>"
    if important:
        body += f"\n\n{important} требуют внимания."
    elif not items:
        body += "\n\nНовых событий нет."
    await present(target, notice(flash, body), inbox_keyboard(items))


def inbox_item_keyboard(item) -> InlineKeyboardMarkup:
    item_id = int(item["id"])
    kind = str(item["kind"])
    rows: list[list[InlineKeyboardButton]] = []
    if kind == "dispute":
        rows.append([InlineKeyboardButton(text="Разобрать", callback_data=f"inbox:dispute:{item_id}")])
    elif kind == "recruitment_result":
        rows.append([InlineKeyboardButton(text="Кандидаты", callback_data="team:candidates")])
        rows.append([InlineKeyboardButton(text="Закрыть", callback_data=f"inbox:action:{item_id}:close")])
    elif kind == "raise_request":
        rows.append([
            InlineKeyboardButton(text="Согласиться", callback_data=f"staff:raiseaccept:{item_id}"),
            InlineKeyboardButton(text="Торговаться", callback_data=f"staff:raise:{item_id}"),
        ])
        rows.append([InlineKeyboardButton(text="Отказать", callback_data=f"staff:deny:{item_id}")])
    elif kind in {"leave_request", "advance_request", "discount_request"}:
        rows.append([
            InlineKeyboardButton(text="Согласиться", callback_data=f"inbox:action:{item_id}:approve"),
            InlineKeyboardButton(text="Отказать", callback_data=f"inbox:action:{item_id}:deny"),
        ])
    else:
        rows.append([InlineKeyboardButton(text="Закрыть", callback_data=f"inbox:action:{item_id}:close")])

    payload = json.loads(item["payload_json"] or "{}")
    employee_id = payload.get("employee_id")
    if employee_id:
        rows.append([InlineKeyboardButton(text="Профиль сотрудника", callback_data=f"team:employee:{employee_id}")])
    rows.append([
        InlineKeyboardButton(text="← Входящие", callback_data="menu:inbox"),
        InlineKeyboardButton(text="Меню", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def negotiation_keyboard(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="−500", callback_data=f"staff:raiseadj:{item_id}:-500"),
            InlineKeyboardButton(text="−100", callback_data=f"staff:raiseadj:{item_id}:-100"),
        ],
        [
            InlineKeyboardButton(text="+100", callback_data=f"staff:raiseadj:{item_id}:100"),
            InlineKeyboardButton(text="+500", callback_data=f"staff:raiseadj:{item_id}:500"),
        ],
        [InlineKeyboardButton(text="Отправить предложение", callback_data=f"staff:raisesend:{item_id}")],
        [
            InlineKeyboardButton(text="← Сообщение", callback_data=f"inbox:item:{item_id}"),
            InlineKeyboardButton(text="Меню", callback_data="menu:home"),
        ],
    ])


def build_navigation_router(db, game, simulation, admin_ids: frozenset[int]) -> Router:
    router = Router(name="compact-navigation")

    async def show_home(target: Message, player_id: int, *, edit: bool) -> None:
        text, opened, urgent = _home_snapshot(db, game, simulation, player_id)
        await present(
            target,
            text,
            home_keyboard(opened, urgent, is_admin=player_id in admin_ids),
            edit=edit,
        )

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        created = simulation.ensure_player(message.from_user.id, message.from_user.username)
        if created:
            await message.answer(
                "<b>🌒 NIGHTSHIFT</b>\n\n"
                "Магазин работает, даже когда ты офлайн. Следи за входящими, товаром и командой.",
                reply_markup=ReplyKeyboardRemove(),
            )
        await show_home(message, message.from_user.id, edit=False)

    @router.message(Command("menu"))
    async def menu(message: Message) -> None:
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        await show_home(message, message.from_user.id, edit=False)

    @router.callback_query(F.data == "menu:home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        await show_home(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data == "menu:inbox")
    async def inbox(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_inbox(callback.message, game, simulation, callback.from_user.id)

    @router.callback_query(F.data.startswith("inbox:item:"))
    async def inbox_item(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int((callback.data or "").split(":")[2])
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await render_inbox(callback.message, game, simulation, callback.from_user.id, flash="Сообщение уже закрыто.")
            return
        marker = "🔴 " if item["priority"] == "urgent" else "🟡 " if item["priority"] == "important" else ""
        body = str(item["body"] or "").strip()
        text = f"<b>{marker}{clean(item['title'])}</b>"
        if body:
            text += f"\n\n{body}"
        await present(callback.message, text, inbox_item_keyboard(item))

    @router.callback_query(F.data.startswith("inbox:action:"))
    async def inbox_action(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, item_raw, action = (callback.data or "").split(":")
        item_id = int(item_raw)
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await render_inbox(callback.message, game, simulation, callback.from_user.id, flash="Сообщение уже закрыто.")
            return
        if action == "close":
            game.close_inbox(callback.from_user.id, item_id)
            result = "Сообщение закрыто."
        else:
            result = game.handle_inbox_action(callback.from_user.id, item_id, action)
        await render_inbox(callback.message, game, simulation, callback.from_user.id, flash=result)

    async def show_negotiation(callback: CallbackQuery, item_id: int, flash: str | None = None) -> None:
        state = game.start_raise_negotiation(callback.from_user.id, item_id)
        if not state:
            await render_inbox(callback.message, game, simulation, callback.from_user.id, flash="Запрос уже неактуален.")
            return
        employee = state["employee"]
        payload = state["payload"]
        text = (
            f"<b>Переговоры · {clean(employee['alias'])}</b>\n\n"
            f"Сейчас: {money(employee['pay_per_job'])}\n"
            f"Запрос: {money(payload['requested_pay'])}\n"
            f"Предложение: <b>{money(payload['offer_pay'])}</b>"
        )
        await present(callback.message, notice(flash, text), negotiation_keyboard(item_id))

    @router.callback_query(F.data.startswith("staff:raise:") & ~F.data.startswith("staff:raiseadj:"))
    async def negotiate(callback: CallbackQuery) -> None:
        await callback.answer()
        await show_negotiation(callback, int((callback.data or "").split(":")[2]))

    @router.callback_query(F.data.startswith("staff:raiseadj:"))
    async def adjust_raise(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, item_raw, delta_raw = (callback.data or "").split(":")
        game.adjust_raise_offer(callback.from_user.id, int(item_raw), int(delta_raw))
        await show_negotiation(callback, int(item_raw))

    @router.callback_query(F.data.startswith("staff:raisesend:"))
    async def send_raise(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int((callback.data or "").split(":")[2])
        result = game.submit_raise_offer(callback.from_user.id, item_id)
        item = game.inbox_item(callback.from_user.id, item_id)
        if item and item["status"] == "open":
            await show_negotiation(callback, item_id, result)
        else:
            await render_inbox(callback.message, game, simulation, callback.from_user.id, flash=result)

    @router.callback_query(F.data.startswith("staff:raiseaccept:"))
    async def accept_raise(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int((callback.data or "").split(":")[2])
        result = game.accept_raise_request(callback.from_user.id, item_id)
        await render_inbox(callback.message, game, simulation, callback.from_user.id, flash=result)

    @router.callback_query(F.data.startswith("staff:deny:"))
    async def deny_raise(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int((callback.data or "").split(":")[2])
        result = game.handle_inbox_action(callback.from_user.id, item_id, "deny")
        await render_inbox(callback.message, game, simulation, callback.from_user.id, flash=result)

    return router
