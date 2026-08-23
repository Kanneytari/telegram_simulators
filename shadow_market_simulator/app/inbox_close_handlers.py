from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from .keyboards import main_menu
from .runtime import STAFF_INBOX_KINDS


CLIENT_INBOX_KINDS = {"dispute", "discount_request"}


def _inbox_counts(db, player_id: int) -> tuple[int, int, int, int]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT kind, priority FROM inbox WHERE player_id=? AND status='open'",
            (player_id,),
        ).fetchall()
    total = len(rows)
    clients = sum(row["kind"] in CLIENT_INBOX_KINDS for row in rows)
    staff = sum(row["kind"] in STAFF_INBOX_KINDS for row in rows)
    urgent = sum(row["priority"] in {"important", "urgent"} for row in rows)
    return total, clients, staff, urgent


def close_destination(db, player_id: int) -> str:
    total, _, _, _ = _inbox_counts(db, player_id)
    return "inbox" if total else "home"


def _inbox_keyboard(total: int, clients: int, staff: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⚖️ Клиенты · {clients}", callback_data="inbox:clients")],
        [InlineKeyboardButton(text=f"👥 Сотрудники · {staff}", callback_data="inbox:staff")],
        [InlineKeyboardButton(text=f"📋 Все · {total}", callback_data="inbox:all")],
        [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
    ])


def _dashboard(db, game, simulation, player_id: int) -> tuple[str, int, int]:
    simulation.advance(player_id)
    game.process_payroll(player_id)
    with db.connect() as conn:
        shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
        deposits = int(conn.execute(
            "SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1",
            (player_id,),
        ).fetchone()[0])
        wages = int(conn.execute(
            "SELECT COALESCE(SUM(wages_accrued),0) FROM employees WHERE player_id=?",
            (player_id,),
        ).fetchone()[0])
        stock = conn.execute(
            """SELECT COALESCE(SUM(remaining),0) units,
                      COALESCE(SUM(remaining*unit_cost),0) cost
               FROM batches WHERE player_id=? AND status='warehouse'""",
            (player_id,),
        ).fetchone()
        employees = int(conn.execute(
            "SELECT COUNT(*) FROM employees WHERE player_id=? AND active=1",
            (player_id,),
        ).fetchone()[0])
        settings = conn.execute(
            "SELECT time_multiplier FROM settings WHERE player_id=?",
            (player_id,),
        ).fetchone()
    opened, _, _, urgent = _inbox_counts(db, player_id)
    free_cash = int(shop["balance"]) - deposits - wages - int(shop["reserve_target"])
    alert = f" · 🔴 {urgent}" if urgent else ""
    speed = float(settings["time_multiplier"] or 1.0) if settings else 1.0
    speed_line = f"\n⏩ Тестовая скорость: x{speed:g}" if speed != 1.0 else ""
    text = (
        f"<b>🌒 {shop['name']}</b>\n\n"
        f"<b>Финансы</b>\n"
        f"Баланс: <b>{shop['balance']:,} ₽</b>\n"
        f"Свободно: <b>{free_cash:,} ₽</b>\n"
        f"Начислено сотрудникам: {wages:,} ₽\n\n"
        f"<b>Операции</b>\n"
        f"⭐ Рейтинг: {shop['rating']:.2f}\n"
        f"Запас: {stock['units']} ед. · ~{stock['cost']:,} ₽\n"
        f"Команда: {employees}\n"
        f"Входящие: {opened}{alert}"
        f"{speed_line}"
    )
    return text, opened, urgent


def build_inbox_close_router(db, game, simulation, admin_ids: frozenset[int]) -> Router:
    router = Router(name="inbox-close-navigation")

    @router.callback_query(F.data.startswith("inbox:action:") & F.data.endswith(":close"))
    async def close_message(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, item_id_raw, _ = callback.data.split(":")
        item_id = int(item_id_raw)
        item = game.inbox_item(callback.from_user.id, item_id)
        if item and item["status"] == "open":
            game.close_inbox(callback.from_user.id, item_id)

        total, clients, staff, _ = _inbox_counts(db, callback.from_user.id)
        if total:
            await callback.message.edit_text(
                "<b>📨 Входящие</b>\n\n"
                f"Всего открыто: <b>{total}</b>\n"
                f"Клиенты: {clients}\n"
                f"Сотрудники: {staff}\n\n"
                "Выбери тип сообщений.",
                reply_markup=_inbox_keyboard(total, clients, staff),
            )
            return

        text, opened, urgent = _dashboard(db, game, simulation, callback.from_user.id)
        await callback.message.edit_text(
            text,
            reply_markup=main_menu(
                opened,
                urgent,
                is_admin=callback.from_user.id in admin_ids,
            ),
        )

    return router
