from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .db import Database
from .simulation import iso, parse_dt, utcnow


def build_time_router(db: Database, simulation, recruitment, game, admin_ids: frozenset[int]) -> Router:
    router = Router(name="time-controls")

    def is_admin(player_id: int) -> bool:
        return player_id in admin_ids

    def speed_keyboard(current: float) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=("✓ " if abs(current - value) < 0.001 else "") + f"x{value}",
                        callback_data=f"admin:speed:{value}",
                    )
                    for value in (1, 15, 30, 60)
                ],
                [
                    InlineKeyboardButton(text="← Админ", callback_data="admin:panel"),
                    InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
                ],
            ]
        )

    def admin_panel_keyboard(current: float) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏩ Tick · +6 ч", callback_data="admin:tick")],
                [
                    InlineKeyboardButton(
                        text=("✓ " if abs(current - value) < 0.001 else "") + f"x{value}",
                        callback_data=f"admin:speed:{value}",
                    )
                    for value in (1, 15, 30, 60)
                ],
                [InlineKeyboardButton(text="🗑 Reset", callback_data="admin:reset")],
                [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
            ]
        )

    def reset_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Да, сбросить игру", callback_data="admin:reset:confirm")],
                [InlineKeyboardButton(text="← Админ", callback_data="admin:reset:cancel")],
            ]
        )

    def admin_panel_text(player_id: int) -> str:
        current = simulation.effective_speed(player_id)
        real_day_minutes = 24.0 * 60.0 / max(0.1, current)
        return (
            "<b>🛠 Админ-панель</b>\n\n"
            f"Скорость: <b>x{current:g}</b>\n"
            f"Игровые сутки: ~{real_day_minutes:.0f} реальной мин.\n\n"
            "Tick проматывает 6 игровых часов.\n"
            "Reset полностью начинает текущее прохождение заново."
        )

    def rescale_payroll_clock(player_id: int, old_multiplier: float, new_multiplier: float, now=None) -> None:
        """Preserve already elapsed game hours when /speed changes."""
        now = now or utcnow()
        old_speed = max(0.1, float(old_multiplier))
        new_speed = max(0.1, float(new_multiplier))
        with db.connect() as conn:
            row = conn.execute(
                "SELECT last_payroll_at FROM settings WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if not row or not row["last_payroll_at"]:
                conn.execute(
                    "UPDATE settings SET last_payroll_at=? WHERE player_id=?",
                    (iso(now), player_id),
                )
                return
            last = parse_dt(row["last_payroll_at"])
            elapsed_real_seconds = max(0.0, (now - last).total_seconds())
            elapsed_game_seconds = elapsed_real_seconds * old_speed
            adjusted_last = now - timedelta(seconds=elapsed_game_seconds / new_speed)
            conn.execute(
                "UPDATE settings SET last_payroll_at=? WHERE player_id=?",
                (iso(adjusted_last), player_id),
            )

    def fast_forward_payroll(player_id: int, game_hours: float) -> None:
        speed = max(0.1, float(simulation.effective_speed(player_id)))
        with db.connect() as conn:
            row = conn.execute(
                "SELECT last_payroll_at FROM settings WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if not row or not row["last_payroll_at"]:
                return
            last = parse_dt(row["last_payroll_at"])
            conn.execute(
                "UPDATE settings SET last_payroll_at=? WHERE player_id=?",
                (iso(last - timedelta(hours=max(0.0, game_hours) / speed)), player_id),
            )

    def execute_tick(player_id: int) -> str:
        game.process_payroll(player_id)
        speed_value = simulation.effective_speed(player_id)

        simulation.fast_forward_timers(player_id, 6)
        fast_forward_payroll(player_id, 6)
        with db.connect() as conn:
            conn.execute(
                "UPDATE shops SET last_simulated_at=? WHERE player_id=?",
                (iso(utcnow() - timedelta(hours=6 / speed_value)), player_id),
            )

        result = simulation.advance(player_id)
        candidates = recruitment.fast_forward(player_id, 6)
        payroll = game.process_payroll(player_id)
        if payroll is None:
            payroll_text = "ещё не наступил срок"
        elif payroll["status"] == "paid":
            payroll_text = f"выплачено {payroll['cash']:,} ₽"
        elif payroll["status"] == "shortfall":
            payroll_text = "задержано: не хватает денег"
        else:
            payroll_text = "расчётный день завершён, начислений нет"

        return (
            "<b>⏩ Тестовый тик</b>\n\n"
            "Промотано: <b>6 игровых часов</b>\n\n"
            f"Заказов: {result.orders_created}\n"
            f"Диспутов: {result.disputes_created}\n"
            f"Событий: {result.messages_created}\n"
            f"Новых кандидатов: {candidates}\n"
            f"Зарплата: {payroll_text}"
        )

    async def apply_speed(target: Message, player_id: int, value: float, *, edit: bool) -> None:
        simulation.advance(player_id)
        game.process_payroll(player_id)
        now = utcnow()

        # StaffInsight/Nightshift effective_speed is the player's absolute multiplier.
        old_multiplier, new_multiplier = recruitment.set_player_multiplier(player_id, value)
        rescale_payroll_clock(player_id, old_multiplier, new_multiplier, now=now)
        simulation.rescale_existing_timers(player_id, old_multiplier, new_multiplier, now=now)

        effective = max(0.1, float(simulation.effective_speed(player_id)))
        real_day_minutes = 24.0 * 60.0 / effective
        text = (
            "<b>⚙️ Скорость игры</b>\n\n"
            f"Множитель: <b>x{effective:g}</b>\n"
            f"1 игровой час: ~{60/effective:.1f} реальной мин.\n"
            f"Игровые сутки: ~{real_day_minutes:.0f} реальной мин.\n\n"
            "Игровые дедлайны и срок выплаты зарплаты пересчитаны."
        )
        if edit:
            await target.edit_text(text, reply_markup=speed_keyboard(effective))
        else:
            await target.answer(text, reply_markup=speed_keyboard(effective))

    @router.message(Command("speed"))
    async def speed(message: Message) -> None:
        if not is_admin(message.from_user.id):
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
            await apply_speed(message, message.from_user.id, value, edit=False)
            return
        current = simulation.effective_speed(message.from_user.id)
        await message.answer(
            "<b>⚙️ Скорость игры</b>\n\n"
            f"Сейчас: <b>x{current:g}</b>\n\n"
            "Быстрый выбор:",
            reply_markup=speed_keyboard(current),
        )

    @router.message(Command("admin"))
    async def admin(message: Message) -> None:
        if not is_admin(message.from_user.id):
            return
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        current = simulation.effective_speed(message.from_user.id)
        await message.answer(admin_panel_text(message.from_user.id), reply_markup=admin_panel_keyboard(current))

    @router.callback_query(F.data == "admin:panel")
    async def admin_panel(callback: CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        simulation.ensure_player(callback.from_user.id, callback.from_user.username)
        current = simulation.effective_speed(callback.from_user.id)
        await callback.message.edit_text(
            admin_panel_text(callback.from_user.id),
            reply_markup=admin_panel_keyboard(current),
        )

    @router.callback_query(F.data.startswith("admin:speed:"))
    async def speed_callback(callback: CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        value = float(callback.data.split(":")[2])
        await apply_speed(callback.message, callback.from_user.id, value, edit=True)

    @router.callback_query(F.data == "admin:tick")
    async def tick_callback(callback: CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        simulation.ensure_player(callback.from_user.id, callback.from_user.username)
        text = execute_tick(callback.from_user.id)
        current = simulation.effective_speed(callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=admin_panel_keyboard(current))

    @router.callback_query(F.data == "admin:reset")
    async def reset_callback(callback: CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        await callback.message.edit_text(
            "<b>🗑 Сбросить прохождение?</b>\n\n"
            "Будут удалены деньги, команда, товар, заказы и текущий прогресс.\n"
            "Журнал аналитических событий сохраняется.",
            reply_markup=reset_keyboard(),
        )

    @router.callback_query(F.data == "admin:reset:cancel")
    async def reset_cancel(callback: CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        current = simulation.effective_speed(callback.from_user.id)
        await callback.message.edit_text(
            admin_panel_text(callback.from_user.id),
            reply_markup=admin_panel_keyboard(current),
        )

    @router.callback_query(F.data == "admin:reset:confirm")
    async def reset_confirm(callback: CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        with db.connect() as conn:
            conn.execute("DELETE FROM shops WHERE player_id=?", (callback.from_user.id,))
        simulation.ensure_player(callback.from_user.id, callback.from_user.username)
        current = simulation.effective_speed(callback.from_user.id)
        await callback.message.edit_text(
            "<b>🗑 Игра сброшена</b>\n\nНачато новое прохождение.",
            reply_markup=admin_panel_keyboard(current),
        )

    @router.message(Command("tick"))
    async def tick(message: Message) -> None:
        if not is_admin(message.from_user.id):
            return
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        await message.answer(execute_tick(message.from_user.id))

    return router
