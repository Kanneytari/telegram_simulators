from __future__ import annotations

import json
from datetime import timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from .db import Database
from .keyboards import inbox_actions, main_menu, result_actions
from .recruitment import RecruitmentService
from .runtime import STAFF_INBOX_KINDS
from .simulation import iso, utcnow


CLIENT_INBOX_KINDS = {"dispute", "discount_request"}


def build_extended_router(db: Database, game, simulation, recruitment: RecruitmentService, admin_ids: frozenset[int]) -> Router:
    router = Router(name="extended")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup | None = None, *, edit: bool = True) -> None:
        if not edit:
            await target.answer(text, reply_markup=markup)
            return
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def dashboard_snapshot(player_id: int) -> tuple[str, int, int]:
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
            inbox = conn.execute(
                """SELECT COUNT(*) opened,
                          SUM(CASE WHEN priority IN ('important','urgent') THEN 1 ELSE 0 END) urgent
                   FROM inbox WHERE player_id=? AND status='open'""",
                (player_id,),
            ).fetchone()
            employees = conn.execute(
                "SELECT COUNT(*) FROM employees WHERE player_id=? AND active=1",
                (player_id,),
            ).fetchone()[0]
            settings = conn.execute(
                "SELECT time_multiplier FROM settings WHERE player_id=?",
                (player_id,),
            ).fetchone()

        opened = int(inbox["opened"] or 0)
        urgent = int(inbox["urgent"] or 0)
        free_cash = int(shop["balance"]) - deposits - wages - int(shop["reserve_target"])
        alert = f" · 🔴 {urgent}" if urgent else ""
        speed = float(settings["time_multiplier"] or 1.0)
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

    async def show_dashboard(target: Message, player_id: int, *, edit: bool) -> None:
        text, opened, urgent = dashboard_snapshot(player_id)
        await present(target, text, main_menu(opened, urgent), edit=edit)

    def inbox_counts(player_id: int) -> tuple[int, int, int]:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT kind FROM inbox WHERE player_id=? AND status='open'",
                (player_id,),
            ).fetchall()
        total = len(rows)
        clients = sum(row["kind"] in CLIENT_INBOX_KINDS for row in rows)
        staff = sum(row["kind"] in STAFF_INBOX_KINDS for row in rows)
        return total, clients, staff

    def inbox_root_keyboard(total: int, clients: int, staff: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"⚖️ Клиенты · {clients}", callback_data="inbox:clients")],
                [InlineKeyboardButton(text=f"👥 Сотрудники · {staff}", callback_data="inbox:staff")],
                [InlineKeyboardButton(text=f"📋 Все · {total}", callback_data="inbox:all")],
                [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
            ]
        )

    def filtered_items(player_id: int, section: str):
        with db.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM inbox WHERE player_id=? AND status='open'
                   ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'important' THEN 1 ELSE 2 END, created_at""",
                (player_id,),
            ).fetchall()
        if section == "staff":
            return [row for row in rows if row["kind"] in STAFF_INBOX_KINDS]
        if section == "clients":
            return [row for row in rows if row["kind"] in CLIENT_INBOX_KINDS]
        return rows

    def filtered_keyboard(items, section: str) -> InlineKeyboardMarkup:
        marker = {"urgent": "🔴", "important": "🟠", "normal": "▫️"}
        rows = [
            [
                InlineKeyboardButton(
                    text=f"{marker.get(item['priority'], '▫️')} {item['title'][:40]}",
                    callback_data=f"inbox:item:{item['id']}",
                )
            ]
            for item in items
        ]
        rows.append(
            [
                InlineKeyboardButton(text="← Входящие", callback_data="menu:inbox"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def staff_item_keyboard(item) -> InlineKeyboardMarkup:
        payload = json.loads(item["payload_json"] or "{}")
        employee_id = payload.get("employee_id")
        rows = []
        if item["kind"] == "raise_request":
            rows.append(
                [
                    InlineKeyboardButton(text="✅ Принять условия", callback_data=f"staff:raiseaccept:{item['id']}"),
                    InlineKeyboardButton(text="🤝 Торговаться", callback_data=f"staff:raise:{item['id']}"),
                ]
            )
            rows.append([InlineKeyboardButton(text="❌ Отказать", callback_data=f"staff:deny:{item['id']}")])
        elif item["kind"] in {"leave_request", "advance_request"}:
            rows.append(
                [
                    InlineKeyboardButton(text="✅ Согласиться", callback_data=f"inbox:action:{item['id']}:approve"),
                    InlineKeyboardButton(text="❌ Отказать", callback_data=f"inbox:action:{item['id']}:deny"),
                ]
            )
        elif item["kind"] in {"payroll_report", "employee_exit"}:
            rows.append([InlineKeyboardButton(text="✓ Закрыть", callback_data=f"inbox:action:{item['id']}:close")])
        if employee_id:
            rows.append([InlineKeyboardButton(text="👤 Профиль сотрудника", callback_data=f"employee:{employee_id}")])
        rows.append(
            [
                InlineKeyboardButton(text="← Сотрудники", callback_data="inbox:staff"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def negotiation_keyboard(item_id: int, employee_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="−500", callback_data=f"staff:raiseadj:{item_id}:-500"),
                    InlineKeyboardButton(text="−100", callback_data=f"staff:raiseadj:{item_id}:-100"),
                    InlineKeyboardButton(text="+100", callback_data=f"staff:raiseadj:{item_id}:100"),
                    InlineKeyboardButton(text="+500", callback_data=f"staff:raiseadj:{item_id}:500"),
                ],
                [InlineKeyboardButton(text="📨 Отправить предложение", callback_data=f"staff:raisesend:{item_id}")],
                [InlineKeyboardButton(text="✅ Принять запрос", callback_data=f"staff:raiseaccept:{item_id}")],
                [InlineKeyboardButton(text="👤 Профиль сотрудника", callback_data=f"employee:{employee_id}")],
                [
                    InlineKeyboardButton(text="← Сообщение", callback_data=f"inbox:item:{item_id}"),
                    InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
                ],
            ]
        )

    async def show_negotiation(callback: CallbackQuery, item_id: int, note: str | None = None) -> None:
        state = game.start_raise_negotiation(callback.from_user.id, item_id)
        if not state:
            await present(callback.message, "Запрос уже неактуален.", result_actions("inbox:staff", "← Сотрудники"))
            return
        employee = state["employee"]
        payload = state["payload"]
        text = (
            f"<b>🤝 Переговоры · {employee['alias']}</b>\n\n"
            f"Текущая ставка: {employee['pay_per_job']:,} ₽\n"
            f"Запрос сотрудника: <b>{int(payload['requested_pay']):,} ₽</b>\n"
            f"Твоё предложение: <b>{int(payload['offer_pay']):,} ₽</b>\n\n"
            "Измени встречную ставку и отправь предложение."
        )
        if note:
            text = f"{text}\n\n<b>Ответ</b>\n{note}"
        await present(callback.message, text, negotiation_keyboard(item_id, employee["id"]))

    def analytics_text(player_id: int) -> str:
        simulation.advance(player_id)
        game.process_payroll(player_id)
        with db.connect() as conn:
            shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
            stats = conn.execute(
                """SELECT COUNT(*) orders,
                          COALESCE(SUM(revenue),0) revenue,
                          COALESCE(SUM(revenue-cost-employee_cost),0) profit,
                          COALESCE(SUM(employee_cost),0) wages
                   FROM orders WHERE player_id=? AND created_at>=datetime('now','-7 day')""",
                (player_id,),
            ).fetchone()
            disputes = conn.execute(
                "SELECT COUNT(*) FROM disputes WHERE player_id=? AND created_at>=datetime('now','-7 day')",
                (player_id,),
            ).fetchone()[0]
            refunds = -int(conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM ledger WHERE player_id=? AND kind='refund' AND created_at>=datetime('now','-7 day')",
                (player_id,),
            ).fetchone()[0])
            accrued = int(conn.execute(
                "SELECT COALESCE(SUM(wages_accrued),0) FROM employees WHERE player_id=?",
                (player_id,),
            ).fetchone()[0])
            payroll = conn.execute(
                """SELECT COALESCE(SUM(cash_paid),0) cash, COALESCE(SUM(deposit_added),0) deposit
                   FROM payroll_runs WHERE player_id=? AND created_at>=datetime('now','-7 day')""",
                (player_id,),
            ).fetchone()
        margin = stats["profit"] / stats["revenue"] * 100 if stats["revenue"] else 0.0
        dispute_rate = disputes / stats["orders"] * 100 if stats["orders"] else 0.0
        return (
            "<b>📊 Аналитика · 7 дней</b>\n\n"
            "<b>Продажи</b>\n"
            f"Заказов: {stats['orders']}\n"
            f"Выручка: <b>{stats['revenue']:,} ₽</b>\n"
            f"Расчётная прибыль: {stats['profit']:,} ₽ ({margin:.1f}%)\n"
            f"Диспуты: {disputes} ({dispute_rate:.1f}%)\n"
            f"Компенсации: {refunds:,} ₽\n\n"
            "<b>Персонал</b>\n"
            f"Начислено зарплаты: {stats['wages']:,} ₽\n"
            f"Выплачено деньгами: {payroll['cash']:,} ₽\n"
            f"В депозиты: {payroll['deposit']:,} ₽\n"
            f"К ближайшей выплате: <b>{accrued:,} ₽</b>\n\n"
            f"⭐ Рейтинг: {shop['rating']:.2f}"
        )

    def analytics_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💸 Выплаты", callback_data="analytics:payroll")],
                [
                    InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:analytics"),
                    InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
                ],
            ]
        )

    def admin_keyboard(current: float) -> InlineKeyboardMarkup:
        rows = [
            [
                InlineKeyboardButton(
                    text=("✓ " if abs(current - value) < 0.001 else "") + f"x{value}",
                    callback_data=f"admin:speed:{value}",
                )
                for value in (1, 15, 30, 60)
            ],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def set_speed(target: Message, player_id: int, value: float, *, edit: bool) -> None:
        simulation.advance(player_id)
        _, new = recruitment.set_player_multiplier(player_id, value)
        text = (
            "<b>⚙️ Скорость игры</b>\n\n"
            f"Множитель: <b>x{new:g}</b>\n"
            f"1 игровой час проходит за ~{60/new:.1f} реальной мин.\n\n"
            "Суточная выплата зарплаты остаётся привязана к реальным 24 часам."
        )
        await present(target, text, admin_keyboard(new), edit=edit)

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        created = simulation.ensure_player(message.from_user.id, message.from_user.username)
        if created:
            await message.answer(
                "<b>NIGHTSHIFT</b>\n\n"
                "Управляй деньгами, командой, клиентскими кейсами и рекламой. Мир продолжает работать, пока ты офлайн.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await message.answer("<b>NIGHTSHIFT</b>", reply_markup=ReplyKeyboardRemove())
        await show_dashboard(message, message.from_user.id, edit=False)

    @router.message(Command("menu"))
    async def menu_command(message: Message) -> None:
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        await show_dashboard(message, message.from_user.id, edit=False)

    @router.callback_query(F.data == "menu:home")
    async def menu_home(callback: CallbackQuery) -> None:
        await callback.answer()
        await show_dashboard(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data == "menu:inbox")
    async def inbox_root(callback: CallbackQuery) -> None:
        await callback.answer()
        simulation.advance(callback.from_user.id)
        game.process_payroll(callback.from_user.id)
        total, clients, staff = inbox_counts(callback.from_user.id)
        text = (
            "<b>📨 Входящие</b>\n\n"
            f"Всего открыто: <b>{total}</b>\n"
            f"Клиенты: {clients}\n"
            f"Сотрудники: {staff}\n\n"
            "Выбери тип сообщений."
        )
        await present(callback.message, text, inbox_root_keyboard(total, clients, staff))

    @router.callback_query(F.data.in_({"inbox:staff", "inbox:clients", "inbox:all"}))
    async def inbox_section(callback: CallbackQuery) -> None:
        await callback.answer()
        section = callback.data.split(":")[1]
        items = filtered_items(callback.from_user.id, section)
        title = {"staff": "👥 Сотрудники", "clients": "⚖️ Клиенты", "all": "📋 Все сообщения"}[section]
        text = f"<b>{title}</b>\n\nОткрыто: <b>{len(items)}</b>"
        await present(callback.message, text, filtered_keyboard(items, section))

    @router.callback_query(F.data.startswith("inbox:item:"))
    async def inbox_item(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int(callback.data.split(":")[2])
        item = game.inbox_item(callback.from_user.id, item_id)
        if not item or item["status"] != "open":
            await present(callback.message, "Сообщение уже неактуально.", result_actions("menu:inbox", "← Входящие"))
            return
        marker = {"urgent": "🔴", "important": "🟠"}.get(item["priority"], "")
        title = f"{marker} {item['title']}".strip()
        text = f"<b>{title}</b>\n\n{item['body']}"
        keyboard = staff_item_keyboard(item) if item["kind"] in STAFF_INBOX_KINDS else inbox_actions(item)
        await present(callback.message, text, keyboard)

    @router.callback_query(F.data.startswith("staff:raise:") & ~F.data.startswith("staff:raiseadj:") & ~F.data.startswith("staff:raiseaccept:"))
    async def raise_negotiate(callback: CallbackQuery) -> None:
        await callback.answer()
        await show_negotiation(callback, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("staff:raiseadj:"))
    async def raise_adjust(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, item_id, delta = callback.data.split(":")
        game.adjust_raise_offer(callback.from_user.id, int(item_id), int(delta))
        await show_negotiation(callback, int(item_id))

    @router.callback_query(F.data.startswith("staff:raisesend:"))
    async def raise_send(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int(callback.data.split(":")[2])
        result = game.submit_raise_offer(callback.from_user.id, item_id)
        item = game.inbox_item(callback.from_user.id, item_id)
        if item and item["status"] == "open":
            await show_negotiation(callback, item_id, result)
        else:
            await present(callback.message, f"<b>🤝 Договорились</b>\n\n{result}", result_actions("inbox:staff", "← Сотрудники"))

    @router.callback_query(F.data.startswith("staff:raiseaccept:"))
    async def raise_accept(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int(callback.data.split(":")[2])
        result = game.accept_raise_request(callback.from_user.id, item_id)
        await present(callback.message, f"<b>Готово</b>\n\n{result}", result_actions("inbox:staff", "← Сотрудники"))

    @router.callback_query(F.data.startswith("staff:deny:"))
    async def staff_deny(callback: CallbackQuery) -> None:
        await callback.answer()
        item_id = int(callback.data.split(":")[2])
        result = game.handle_inbox_action(callback.from_user.id, item_id, "deny")
        await present(callback.message, f"<b>Решение принято</b>\n\n{result}", result_actions("inbox:staff", "← Сотрудники"))

    @router.callback_query(F.data == "menu:analytics")
    async def analytics(callback: CallbackQuery) -> None:
        await callback.answer()
        await present(callback.message, analytics_text(callback.from_user.id), analytics_keyboard())

    @router.callback_query(F.data == "analytics:payroll")
    async def payroll(callback: CallbackQuery) -> None:
        await callback.answer()
        game.process_payroll(callback.from_user.id)
        await present(
            callback.message,
            game.payroll_summary(callback.from_user.id),
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="← Аналитика", callback_data="menu:analytics")],
                    [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
                ]
            ),
        )

    @router.message(Command("speed"))
    async def speed_command(message: Message) -> None:
        if message.from_user.id not in admin_ids:
            return
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        parts = (message.text or "").split()
        if len(parts) == 2:
            try:
                value = float(parts[1].replace(",", "."))
            except ValueError:
                await message.answer("Формат: /speed 60")
                return
            if not 0.1 <= value <= 240:
                await message.answer("Допустимый множитель: от 0.1 до 240.")
                return
            await set_speed(message, message.from_user.id, value, edit=False)
            return
        current = recruitment.player_multiplier(message.from_user.id)
        await message.answer(
            "<b>⚙️ Скорость игры</b>\n\n"
            f"Сейчас: <b>x{current:g}</b>\n"
            "Выбери стандартный множитель или используй /speed число.",
            reply_markup=admin_keyboard(current),
        )

    @router.message(Command("admin"))
    async def admin_command(message: Message) -> None:
        if message.from_user.id not in admin_ids:
            return
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        current = recruitment.player_multiplier(message.from_user.id)
        await message.answer(
            "<b>🛠 Админ-панель</b>\n\n"
            f"Скорость игрока: <b>x{current:g}</b>\n\n"
            "Быстрый выбор:",
            reply_markup=admin_keyboard(current),
        )

    @router.callback_query(F.data.startswith("admin:speed:"))
    async def admin_speed(callback: CallbackQuery) -> None:
        if callback.from_user.id not in admin_ids:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        value = float(callback.data.split(":")[2])
        await set_speed(callback.message, callback.from_user.id, value, edit=True)

    @router.message(Command("tick"))
    async def tick(message: Message) -> None:
        if message.from_user.id not in admin_ids:
            return
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        speed = simulation.effective_speed(message.from_user.id)
        with db.connect() as conn:
            conn.execute(
                "UPDATE shops SET last_simulated_at=? WHERE player_id=?",
                (iso(utcnow() - timedelta(hours=6 / speed)), message.from_user.id),
            )
        result = simulation.advance(message.from_user.id)
        candidates = recruitment.fast_forward(message.from_user.id, 6)
        await message.answer(
            "<b>⏩ Тестовый тик · 6 игровых часов</b>\n\n"
            f"Заказов: {result.orders_created}\n"
            f"Диспутов: {result.disputes_created}\n"
            f"Событий: {result.messages_created}\n"
            f"Новых кандидатов: {candidates}\n\n"
            "Суточная зарплата не ускоряется: она привязана к реальным 24 часам.",
        )

    return router
