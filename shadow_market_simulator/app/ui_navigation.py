from __future__ import annotations

from app.presentation.vocabulary import ADMIN, ANALYTICS, HOME, INBOX, PRODUCT, REFRESH, STOREFRONT, TEAM, button, label
from .tutorial import hooks as tutorial_hooks

import json

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from app.analytics.business_analytics import _comparison_ready, _order_metrics, _product_metrics, _window
from .ui_common import clean, money, notice, present, signed_pct_change


INBOX_PAGE_SIZE = 8


def home_keyboard(opened: int, urgent: int, *, is_admin: bool = False) -> InlineKeyboardMarkup:
    inbox = label(INBOX, opened)
    if urgent:
        inbox += f" · 🔴 {urgent}"
    rows = [
        [InlineKeyboardButton(text=inbox, callback_data=INBOX.callback_data)],
        [button(PRODUCT), button(STOREFRONT)],
        [button(TEAM), button(ANALYTICS)],
    ]
    if is_admin:
        rows.append([button(ADMIN)])
    rows.append([button(REFRESH)])
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

    next_step = ""
    if urgent:
        next_step = "🔴 Разбери срочное сообщение во Входящих."

    text = (
        f"<b>🌒 {clean(shop['name'])}</b>\n\n"
        f"Баланс: <b>{money(shop['balance'])}</b>\n"
        f"Свободно: <b>{money(free_cash)}</b>\n"
        f"За 7 дней: <b>{money(current['earned'])}</b>{earned_trend} · "
        f"{current['orders']} заказов{orders_trend}\n\n"
        + "\n".join(alerts[:2])
    )
    if next_step:
        text += f"\n\n{next_step}"
    return text, opened, urgent

@tutorial_hooks.soft_home
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
        paging.append(InlineKeyboardButton(text="Предыдущие", callback_data=f"inbox:page:{page-1}"))
    if (page + 1) * INBOX_PAGE_SIZE < total:
        paging.append(InlineKeyboardButton(text="Следующие", callback_data=f"inbox:page:{page+1}"))
    if paging:
        rows.append(paging)
    rows.append([
        button(REFRESH, callback_data=f"inbox:page:{page}"),
        button(HOME),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@tutorial_hooks.handoff_inbox
async def render_inbox(target: Message, game, simulation, player_id: int, *, flash: str | None = None, page: int = 0) -> None:
    simulation.advance(player_id)
    game.process_payroll(player_id)
    items, total, attention, page = _inbox_page(game.db, player_id, page)
    body = f"<b>{label(INBOX, total)}</b>"
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
    elif kind == "discount_request":
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
        button(INBOX, callback_data=back),
        button(HOME),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)




def build_navigation_router(db, game, simulation, admin_ids: frozenset[int]) -> Router:
    router = Router(name="compact-navigation")

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        created = simulation.ensure_player(message.from_user.id, message.from_user.username)
        if created:
            await message.answer(
                "<b>🌒 NIGHTSHIFT</b>\n\n"
                "Ты управляешь магазином, который работает даже когда ты офлайн.\n\n"
                "Закупай товар, распределяй его между сотрудниками, управляй витриной и разбирай проблемы.\n\n"
                "<b>Товар. Склад. Закладчики. Витрина. Продажи.</b>",
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


    return router
