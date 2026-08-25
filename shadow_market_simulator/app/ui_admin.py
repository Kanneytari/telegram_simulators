from __future__ import annotations

from app.presentation.vocabulary import HOME, button
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.engine.simulation import iso, parse_dt, utcnow
from .ui_common import present


def build_admin_router(db, simulation, recruitment, game, admin_ids: frozenset[int]) -> Router:
    router = Router(name="compact-admin")

    def is_admin(player_id: int) -> bool:
        return player_id in admin_ids

    def panel_keyboard(current: float) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="+6 игровых часов", callback_data="admin:tick")],
            [
                InlineKeyboardButton(text=("✓ " if abs(current - 1) < 0.001 else "") + "×1", callback_data="admin:speed:1"),
                InlineKeyboardButton(text=("✓ " if abs(current - 15) < 0.001 else "") + "×15", callback_data="admin:speed:15"),
            ],
            [
                InlineKeyboardButton(text=("✓ " if abs(current - 30) < 0.001 else "") + "×30", callback_data="admin:speed:30"),
                InlineKeyboardButton(text=("✓ " if abs(current - 60) < 0.001 else "") + "×60", callback_data="admin:speed:60"),
            ],
            [InlineKeyboardButton(text="Сбросить игру", callback_data="admin:reset")],
            [button(HOME)],
        ])

    def reset_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Сбросить игру", callback_data="admin:reset:confirm")],
            [InlineKeyboardButton(text="Отмена", callback_data="admin:panel")],
        ])

    def panel_text(player_id: int) -> str:
        current = simulation.effective_speed(player_id)
        day_minutes = 24.0 * 60.0 / max(0.1, current)
        return (
            "<b>🛠 Админ</b>\n\n"
            f"Скорость: <b>×{current:g}</b>\n"
            f"Игровые сутки: ~{day_minutes:.0f} реальных мин."
        )

    def rescale_payroll_clock(player_id: int, old_multiplier: float, new_multiplier: float, now=None) -> None:
        now = now or utcnow()
        old_speed = max(0.1, float(old_multiplier))
        new_speed = max(0.1, float(new_multiplier))
        with db.connect() as conn:
            row = conn.execute("SELECT last_payroll_at FROM settings WHERE player_id=?", (player_id,)).fetchone()
            if not row or not row["last_payroll_at"]:
                conn.execute("UPDATE settings SET last_payroll_at=? WHERE player_id=?", (iso(now), player_id))
                return
            last = parse_dt(row["last_payroll_at"])
            elapsed_game_seconds = max(0.0, (now - last).total_seconds()) * old_speed
            adjusted_last = now - timedelta(seconds=elapsed_game_seconds / new_speed)
            conn.execute("UPDATE settings SET last_payroll_at=? WHERE player_id=?", (iso(adjusted_last), player_id))

    def fast_forward_payroll(player_id: int, game_hours: float) -> None:
        speed = max(0.1, float(simulation.effective_speed(player_id)))
        with db.connect() as conn:
            row = conn.execute("SELECT last_payroll_at FROM settings WHERE player_id=?", (player_id,)).fetchone()
            if not row or not row["last_payroll_at"]:
                return
            last = parse_dt(row["last_payroll_at"])
            conn.execute(
                "UPDATE settings SET last_payroll_at=? WHERE player_id=?",
                (iso(last - timedelta(hours=max(0.0, game_hours) / speed)), player_id),
            )

    def execute_tick(player_id: int) -> str:
        game.process_payroll(player_id)
        speed = simulation.effective_speed(player_id)
        simulation.fast_forward_timers(player_id, 6)
        fast_forward_payroll(player_id, 6)
        with db.connect() as conn:
            conn.execute(
                "UPDATE shops SET last_simulated_at=? WHERE player_id=?",
                (iso(utcnow() - timedelta(hours=6 / speed)), player_id),
            )
        result = simulation.advance(player_id)
        candidates = recruitment.fast_forward(player_id, 6)
        payroll = game.process_payroll(player_id)
        if payroll is None:
            payroll_text = "ещё не наступила"
        elif payroll["status"] == "paid":
            payroll_text = f"выплачено {payroll['cash']:,} ₽"
        elif payroll["status"] == "shortfall":
            payroll_text = "задержана: не хватает денег"
        else:
            payroll_text = "начислений нет"
        return (
            "<b>+6 игровых часов</b>\n\n"
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
        old, new = recruitment.set_player_multiplier(player_id, value)
        rescale_payroll_clock(player_id, old, new, now=now)
        simulation.rescale_existing_timers(player_id, old, new, now=now)
        effective = max(0.1, float(simulation.effective_speed(player_id)))
        text = (
            "<b>Скорость игры</b>\n\n"
            f"Сейчас: <b>×{effective:g}</b>\n"
            f"1 игровой час: ~{60/effective:.1f} реальной мин."
        )
        await present(target, text, panel_keyboard(effective), edit=edit)

    @router.message(Command("admin"))
    async def admin(message: Message) -> None:
        if not is_admin(message.from_user.id):
            return
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        current = simulation.effective_speed(message.from_user.id)
        await present(message, panel_text(message.from_user.id), panel_keyboard(current), edit=False)

    @router.message(Command("speed"))
    async def speed_command(message: Message) -> None:
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
                await message.answer("Допустимо: от 0,1 до 240.")
                return
            await apply_speed(message, message.from_user.id, value, edit=False)
            return
        current = simulation.effective_speed(message.from_user.id)
        await present(message, f"<b>Скорость игры</b>\n\nСейчас: <b>×{current:g}</b>", panel_keyboard(current), edit=False)

    @router.message(Command("tick"))
    async def tick_command(message: Message) -> None:
        if not is_admin(message.from_user.id):
            return
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        await message.answer(execute_tick(message.from_user.id))

    @router.callback_query(F.data == "admin:panel")
    async def panel(callback: CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        simulation.ensure_player(callback.from_user.id, callback.from_user.username)
        current = simulation.effective_speed(callback.from_user.id)
        await present(callback.message, panel_text(callback.from_user.id), panel_keyboard(current))

    @router.callback_query(F.data.startswith("admin:speed:"))
    async def speed(callback: CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        await apply_speed(callback.message, callback.from_user.id, float(callback.data.split(":")[2]), edit=True)

    @router.callback_query(F.data == "admin:tick")
    async def tick(callback: CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        text = execute_tick(callback.from_user.id)
        current = simulation.effective_speed(callback.from_user.id)
        await present(callback.message, text, panel_keyboard(current))

    @router.callback_query(F.data == "admin:reset")
    async def reset(callback: CallbackQuery) -> None:
        if not is_admin(callback.from_user.id):
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        await present(
            callback.message,
            "<b>Сбросить игру?</b>\n\nБудут удалены деньги, команда, товар, заказы и текущий прогресс.",
            reset_keyboard(),
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
        await present(callback.message, "Игра сброшена. Начато новое прохождение.", panel_keyboard(current))

    return router
