from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from .keyboards import main_menu
from .team_keyboard import employee_list


def build_workflow_dashboard_router(db, game, simulation, admin_ids: frozenset[int]) -> Router:
    router = Router(name="workflow-dashboard")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup | None = None, *, edit: bool = True) -> None:
        if not edit:
            await target.answer(text, reply_markup=markup)
            return
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def dashboard_snapshot(player_id: int) -> tuple[str, int, int, dict]:
        simulation.advance(player_id)
        game.process_payroll(player_id)
        customer = game.customer_metrics(player_id)
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
            warehouse = conn.execute(
                """SELECT COALESCE(SUM(remaining),0) units,
                          COALESCE(SUM(remaining*unit_cost),0) cost
                   FROM batches
                   WHERE player_id=? AND status IN ('receiving','warehouse')""",
                (player_id,),
            ).fetchone()
            transit = conn.execute(
                """SELECT COALESCE(SUM(quantity),0) units,
                          COALESCE(SUM(quantity*unit_cost),0) cost
                   FROM retail_allocations
                   WHERE player_id=? AND status IN ('waiting','preparing')""",
                (player_id,),
            ).fetchone()
            published = conn.execute(
                """SELECT COALESCE(SUM(position_count*pack_size),0) units,
                          COALESCE(SUM(position_count*pack_size*unit_cost),0) cost
                   FROM retail_positions
                   WHERE player_id=? AND position_count>0""",
                (player_id,),
            ).fetchone()
            inbox = conn.execute(
                """SELECT COUNT(*) opened,
                          SUM(CASE WHEN priority IN ('important','urgent') THEN 1 ELSE 0 END) urgent
                   FROM inbox WHERE player_id=? AND status='open'""",
                (player_id,),
            ).fetchone()
            employees = int(conn.execute(
                "SELECT COUNT(*) FROM employees WHERE player_id=? AND active=1",
                (player_id,),
            ).fetchone()[0])
            tasks = int(conn.execute(
                "SELECT COUNT(*) FROM employee_tasks WHERE player_id=? AND status='active'",
                (player_id,),
            ).fetchone()[0])
            unassigned = int(conn.execute(
                """SELECT COUNT(*) FROM batches
                   WHERE player_id=? AND responsible_employee_id IS NULL
                     AND status='warehouse' AND remaining>0""",
                (player_id,),
            ).fetchone()[0])
            settings = conn.execute("SELECT time_multiplier FROM settings WHERE player_id=?", (player_id,)).fetchone()

        opened = int(inbox["opened"] or 0)
        urgent = int(inbox["urgent"] or 0)
        free_cash = int(shop["balance"]) - deposits - wages - int(shop["reserve_target"])
        total_units = int(warehouse["units"] or 0) + int(transit["units"] or 0) + int(published["units"] or 0)
        total_cost = int(warehouse["cost"] or 0) + int(transit["cost"] or 0) + int(published["cost"] or 0)
        alert = f" · 🔴 {urgent}" if urgent else ""
        speed = float(settings["time_multiplier"] or 1.0)
        speed_line = f"\n⏩ Тестовая скорость: x{speed:g}" if speed != 1.0 else ""
        unassigned_line = f"\n🔴 Без ответственного: {unassigned} парт." if unassigned else ""
        quality = f"{customer['product_rating']:.2f}/5" if customer["product_rating"] else "—"
        service = f"{customer['courier_rating']:.2f}/5" if customer["courier_rating"] else "—"
        text = (
            f"<b>🌒 {shop['name']}</b>\n\n"
            f"<b>Финансы</b>\n"
            f"Баланс: <b>{shop['balance']:,} ₽</b>\n"
            f"Свободно: <b>{free_cash:,} ₽</b>\n"
            f"Начислено сотрудникам: {wages:,} ₽\n\n"
            f"<b>Доверие и клиенты</b>\n"
            f"🛡 Доверие: <b>{customer['trust_score']:.0f}/100</b>\n"
            f"🧪 Качество товара: {quality}\n"
            f"👤 Работа курьеров: {service}\n"
            f"♻️ Постоянных клиентов: <b>{customer['regulars']}</b>\n"
            f"📦 Стабильность наличия: {customer['availability'] * 100:.0f}%\n"
            f"Допустимая премия к рынку: ~+{customer['premium_allowance'] * 100:.0f}%\n\n"
            f"<b>Операции</b>\n"
            f"Товар в системе: {total_units} ед. · ~{total_cost:,} ₽\n"
            f"На витрине: {int(published['units'] or 0)} ед.\n"
            f"Активных задач: {tasks}\n"
            f"Команда: {employees}\n"
            f"Входящие: {opened}{alert}"
            f"{unassigned_line}"
            f"{speed_line}"
        )
        return text, opened, urgent, customer

    def dashboard_keyboard(opened: int, urgent: int, player_id: int) -> InlineKeyboardMarkup:
        base = main_menu(opened, urgent, is_admin=player_id in admin_ids)
        rows = [list(row) for row in base.inline_keyboard]
        rows.insert(1, [InlineKeyboardButton(text="🤝 Клиенты и доверие", callback_data="menu:customers")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def show_dashboard(target: Message, player_id: int, *, edit: bool) -> None:
        text, opened, urgent, _ = dashboard_snapshot(player_id)
        await present(
            target,
            text,
            dashboard_keyboard(opened, urgent, player_id),
            edit=edit,
        )

    async def show_team(target: Message, player_id: int, *, edit: bool) -> None:
        simulation.advance(player_id)
        employees = game.employees(player_id)
        busy = sum(row.get("status_text") != "свободен" for row in employees)
        risky = sum(int(row.get("exposure", 0)) > int(row["deposit"]) for row in employees)
        text = (
            f"<b>👥 Команда</b>\n\n"
            f"В штате: <b>{len(employees)}</b>\n"
            f"Сейчас заняты: {busy}\n"
            f"С товаром сверх депозита: <b>{risky}</b>\n\n"
            "На кнопке показаны роль, имя, депозит и текущая задача, если она есть. "
            "🟢 означает розничного сотрудника, который полностью простаивает: доступен, не ждёт передачу, не выполняет задачу и не держит товар или позиции на витрине. "
            "🔴 означает, что стоимость товара под ответственностью выше его депозита."
        )
        await present(target, text, employee_list(employees), edit=edit)

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        created = simulation.ensure_player(message.from_user.id, message.from_user.username)
        intro = (
            "<b>NIGHTSHIFT</b>\n\n"
            "Главный двигатель роста — доверие покупателей. Держи качественный товар, аккуратных курьеров и постоянное наличие, "
            "а честные клиентские проблемы решай разумно. Тогда покупатели будут возвращаться, спрос вырастет, "
            "и магазин сможет продавать дороже рынка.\n\n"
            "Следи за блоком «Доверие и клиенты» на главном экране — это основной индикатор долгосрочного прогресса."
            if created else
            "<b>NIGHTSHIFT</b>"
        )
        await message.answer(intro, reply_markup=ReplyKeyboardRemove())
        await show_dashboard(message, message.from_user.id, edit=False)

    @router.message(Command("menu"))
    async def menu(message: Message) -> None:
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        await show_dashboard(message, message.from_user.id, edit=False)

    @router.callback_query(F.data == "menu:home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        await show_dashboard(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data == "menu:team")
    async def team(callback: CallbackQuery) -> None:
        await callback.answer()
        await show_team(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data == "reset:confirm")
    async def reset_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        with db.connect() as conn:
            conn.execute("DELETE FROM shops WHERE player_id=?", (callback.from_user.id,))
        simulation.ensure_player(callback.from_user.id, callback.from_user.username)
        await show_dashboard(callback.message, callback.from_user.id, edit=True)

    @router.callback_query(F.data == "reset:cancel")
    async def reset_cancel(callback: CallbackQuery) -> None:
        await callback.answer("Сброс отменён")
        simulation.ensure_player(callback.from_user.id, callback.from_user.username)
        await show_dashboard(callback.message, callback.from_user.id, edit=True)

    return router
