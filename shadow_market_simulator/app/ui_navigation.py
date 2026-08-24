from __future__ import annotations

import json

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from .business_analytics import _comparison_ready, _order_metrics, _product_metrics, _window
from .ui_common import clean, money, notice, present, signed_pct_change


INBOX_PAGE_SIZE = 8


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
                      SUM(CASE WHEN priority='urgent' THEN 1 ELSE 0 END) urgent,
                      SUM(CASE WHEN priority='important' THEN 1 ELSE 0 END) important
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
    important = int(inbox["important"] or 0)
    free_cash = int(shop["balance"]) - int(shop["reserve_target"]) - deposits - wages
    compare_ready = _comparison_ready(shop, window)
    earned_trend = signed_pct_change(current["earned"], previous["earned"]) if compare_ready else ""
    orders_trend = signed_pct_change(current["orders"], previous["orders"]) if compare_ready else ""

    alerts: list[str] = []
    if urgent:
        alerts.append(f"🔴 {urgent} событий требуют решения")
    elif important:
        alerts.append(f"🟡 {important} событий требуют внимания")
    if stressed:
        alerts.append(f"🟡 {clean(stressed['alias'])} перегружен")
    low_stock = [p for p in products if p.get("stock_days") is not None and float(p["stock_days"]) < 3.0]
    if low_stock:
        item = min(low_stock, key=lambda row: float(row["stock_days"]))
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


async def render_home(target: Message, db, game, simulation, admin_ids: frozenset[int], player_id: int, *, edit: bool = True) -> None:
    text, opened, urgent = _home_snapshot(db, game, simulation, player_id)
    await present(target, text, home_keyboard(opened, urgent, is_admin=player_id in admin_ids), edit=edit)


def _inbox_page(db, player_id: int, page: int) -> tuple[list, int, int, int]:
    page = max(0, int(page))
    with db.connect() as conn:
        counts = conn.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN priority IN ('important','urgent') THEN 1 ELSE 0 END) attention
               FROM inbox WHERE player_id=? AND status='open'""",
            (player_id,),
        ).fetchone()
        total = int(counts["total"] or 0)
        max_page = max(0, (total - 1) // INBOX_PAGE_SIZE) if total else 0
        page = min(page, max_page)
        items = conn.execute(
            """SELECT * FROM inbox
               WHERE player_id=? AND status='open'
               ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'important' THEN 1 ELSE 2 END,
                        created_at, id
               LIMIT ? OFFSET ?""",
            (player_id, INBOX_PAGE_SIZE, page * INBOX_PAGE_SIZE),
        ).fetchall()
    return list(items), total, int(counts["attention"] or 0), page


def inbox_keyboard(items, page: int = 0, total: int | None = None) -> InlineKeyboardMarkup:
    total = len(items) if total is None else int(total)
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        marker = "🔴 " if item["priority"] == "urgent" else "🟡 " if item["priority"] == "important" else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{marker}{str(item['title'])[:48]}",
                callback_data=f"inbox:item:{item['id']}:{page}",
            )
        ])
    paging: list[InlineKeyboardButton] = []
    if page > 0:
        paging.append(InlineKeyboardButton(text="← Предыдущие", callback_data=f"inbox:page:{page-1}"))
    if (page + 1) * INBOX_PAGE_SIZE < total:
        paging.append(InlineKeyboardButton(text="Следующие →", callback_data=f"inbox:page:{page+1}"))
    if paging:
        rows.append(paging)
    rows.append([
        InlineKeyboardButton(text="Обновить", callback_data=f"inbox:page:{page}"),
        InlineKeyboardButton(text="Меню", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_inbox(target: Message, game, simulation, player_id: int, *, flash: str | None = None, page: int = 0) -> None:
    simulation.advance(player_id)
    game.process_payroll(player_id)
    items, total, attention, page = _inbox_page(game.db, player_id, page)
    body = f"<b>📨 Входящие · {total}</b>"
    if attention:
        body += f"\n\n{attention} требуют внимания."
    elif not total:
        body += "\n\nНовых событий нет."
    if total > INBOX_PAGE_SIZE:
        start = page * INBOX_PAGE_SIZE + 1
        end = start + len(items) - 1
        body += f"\nПоказаны {start}–{end} из {total}."
    await present(target, notice(flash, body), inbox_keyboard(items, page, total))


async def render_after_inbox_action(
    target: Message,
    db,
    game,
    simulation,
    admin_ids: frozenset[int],
    player_id: int,
    *,
    flash: str | None = None,
    page: int = 0,
) -> None:
    with db.connect() as conn:
        left = int(conn.execute(
            "SELECT COUNT(*) FROM inbox WHERE player_id=? AND status='open'",
            (player_id,),
        ).fetchone()[0])
    if left:
        await render_inbox(target, game, simulation, player_id, flash=flash, page=page)
    else:
        await render_home(target, db, game, simulation, admin_ids, player_id)


def inbox_item_keyboard(item, page: int = 0) -> InlineKeyboardMarkup:
    item_id = int(item["id"])
    kind = str(item["kind"])
    rows: list[list[InlineKeyboardButton]] = []
    if kind == "dispute":
        rows.append([InlineKeyboardButton(text="Разобрать", callback_data=f"inbox:dispute:{item_id}:{page}")])
    elif kind == "recruitment_result":
        rows.append([InlineKeyboardButton(text="Кандидаты", callback_data="team:candidates")])
        rows.append([InlineKeyboardButton(text="Закрыть", callback_data=f"inbox:action:{item_id}:close:{page}")])
    elif kind == "raise_request":
        rows.append([
            InlineKeyboardButton(text="Согласиться", callback_data=f"staff:raiseaccept:{item_id}:{page}"),
            InlineKeyboardButton(text="Торговаться", callback_data=f"staff:raise:{item_id}:{page}"),
        ])
        rows.append([InlineKeyboardButton(text="Отказать", callback_data=f"staff:deny:{item_id}:{page}")])
    elif kind in {"leave_request", "advance_request", "discount_request"}:
        rows.append([
            InlineKeyboardButton(text="Согласиться", callback_data=f"inbox:action:{item_id}:approve:{page}"),
            InlineKeyboardButton(text="Отказать", callback_data=f"inbox:action:{item_id}:deny:{page}"),
        ])
    else:
        rows.append([InlineKeyboardButton(text="Закрыть", callback_data=f"inbox:action:{item_id}:close:{page}")])

    payload = json.loads(item["payload_json"] or "{}")
    employee_id = payload.get("employee_id")
    if employee_id:
        rows.append([InlineKeyboardButton(text="Профиль сотрудника", callback_data=f"team:employee:{employee_id}")])
    back = f"inbox:page:{page}" if page else "menu:inbox"
    rows.append([
        InlineKeyboardButton(text="← Входящие", callback_data=back),
        InlineKeyboardButton(text="Меню", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def negotiation_keyboard(item_id: int, page: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="−500", callback_data=f"staff:raiseadj:{item_id}:-500:{page}"),
            InlineKeyboardButton(text="−100", callback_data=f"staff:raiseadj:{item_id}:-100:{page}"),
        ],
        [
            InlineKeyboardButton(text="+100", callback_data=f"staff:raiseadj:{item_id}:100:{page}"),
            InlineKeyboardButton(text="+500", callback_data=f"staff:raiseadj:{item_id}:500:{page}"),
        ],
        [InlineKeyboardButton(text="Отправить предложение", callback_data=f"staff:raisesend:{item_id}:{page}")],
        [
            InlineKeyboardButton(text="← Сообщение", callback_data=f"inbox:item:{item_id}:{page}"),
            InlineKeyboardButton(text="Меню", callback_data="menu:home"),
        ],
    ])


def build_navigation_router(db, game, simulation, admin_ids: frozenset[int]) -> Router:
    router = Router(name="compact-navigation")

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        created = simulation.ensure_player(message.from_user.id, message.from_user.username)
        if created:
            await message.answer(
                "<b>🌒 NIGHTSHIFT</b>\n\n"
                "Магазин работает, даже когда ты офлайн. Следи за входящими, товаром и командой.",
                reply_markup=ReplyKeyboardRemove(),
            )
        await render_home(message, db, game, simulation, admin_ids, message.from_user.id, edit=False)

    @router.message(Command("menu"))
    async def menu(message: Message) -> None:
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        await render_home(message, db, game, simulation, admin_ids, message.from_user.id, edit=False)

    @router.callback_query(F.data == "menu:home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_home(callback.message, db, game, simulation, admin_ids, callback.from_user.id)

    @router.callback_query(F.data == "menu:inbox")
    async def inbox(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_inbox(callback.message, game, simulation, callback.from_user.id)

    @router.callback_query(F.data.startswith("inbox:page:"))
    async def inbox_page(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_inbox(callback.message, game, simulation, callback.from_user.id, page=int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("inbox:item:"))
    async def inbox_item(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        item_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await render_after_inbox_action(callback.message, db, game, simulation, admin_ids, callback.from_user.id, flash="Сообщение уже закрыто.", page=page)
            return
        marker = "🔴 " if item["priority"] == "urgent" else "🟡 " if item["priority"] == "important" else ""
        body = str(item["body"] or "").strip()
        text = f"<b>{marker}{clean(item['title'])}</b>"
        if body:
            text += f"\n\n{body}"
        await present(callback.message, text, inbox_item_keyboard(item, page))

    @router.callback_query(F.data.startswith("inbox:action:"))
    async def inbox_action(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        item_id = int(parts[2])
        action = parts[3]
        page = int(parts[4]) if len(parts) > 4 else 0
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await render_after_inbox_action(callback.message, db, game, simulation, admin_ids, callback.from_user.id, flash="Сообщение уже закрыто.", page=page)
            return
        if action == "close":
            game.close_inbox(callback.from_user.id, item_id)
            result = "Сообщение закрыто."
        else:
            result = game.handle_inbox_action(callback.from_user.id, item_id, action)
        await render_after_inbox_action(callback.message, db, game, simulation, admin_ids, callback.from_user.id, flash=result, page=page)

    async def show_negotiation(callback: CallbackQuery, item_id: int, page: int = 0, flash: str | None = None) -> None:
        state = game.start_raise_negotiation(callback.from_user.id, item_id)
        if not state:
            await render_after_inbox_action(callback.message, db, game, simulation, admin_ids, callback.from_user.id, flash="Запрос уже неактуален.", page=page)
            return
        employee = state["employee"]
        payload = state["payload"]
        text = (
            f"<b>Переговоры · {clean(employee['alias'])}</b>\n\n"
            f"Сейчас: {money(employee['pay_per_job'])}\n"
            f"Запрос: {money(payload['requested_pay'])}\n"
            f"Предложение: <b>{money(payload['offer_pay'])}</b>"
        )
        await present(callback.message, notice(flash, text), negotiation_keyboard(item_id, page))

    @router.callback_query(F.data.startswith("staff:raise:") & ~F.data.startswith("staff:raiseadj:"))
    async def negotiate(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        await show_negotiation(callback, int(parts[2]), int(parts[3]) if len(parts) > 3 else 0)

    @router.callback_query(F.data.startswith("staff:raiseadj:"))
    async def adjust_raise(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        item_id = int(parts[2])
        game.adjust_raise_offer(callback.from_user.id, item_id, int(parts[3]))
        await show_negotiation(callback, item_id, int(parts[4]) if len(parts) > 4 else 0)

    @router.callback_query(F.data.startswith("staff:raisesend:"))
    async def send_raise(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        item_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        result = game.submit_raise_offer(callback.from_user.id, item_id)
        item = game.inbox_item(callback.from_user.id, item_id)
        if item and item["status"] == "open":
            await show_negotiation(callback, item_id, page, result)
        else:
            await render_after_inbox_action(callback.message, db, game, simulation, admin_ids, callback.from_user.id, flash=result, page=page)

    @router.callback_query(F.data.startswith("staff:raiseaccept:"))
    async def accept_raise(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        item_id = int(parts[2])
        result = game.accept_raise_request(callback.from_user.id, item_id)
        await render_after_inbox_action(callback.message, db, game, simulation, admin_ids, callback.from_user.id, flash=result, page=int(parts[3]) if len(parts) > 3 else 0)

    @router.callback_query(F.data.startswith("staff:deny:"))
    async def deny_raise(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        item_id = int(parts[2])
        result = game.handle_inbox_action(callback.from_user.id, item_id, "deny")
        await render_after_inbox_action(callback.message, db, game, simulation, admin_ids, callback.from_user.id, flash=result, page=int(parts[3]) if len(parts) > 3 else 0)

    return router
