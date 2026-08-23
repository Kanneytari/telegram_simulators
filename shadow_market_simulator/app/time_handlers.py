from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .db import Database
from .simulation import iso, utcnow


def build_time_router(db: Database, simulation, recruitment, admin_ids: frozenset[int]) -> Router:
    router = Router(name="time-controls")

    def keyboard(current: float) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=("✓ " if abs(current - value) < 0.001 else "") + f"x{value}",
                        callback_data=f"admin:speed:{value}",
                    )
                    for value in (1, 15, 30, 60)
                ],
                [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
            ]
        )

    async def apply_speed(target: Message, player_id: int, value: float, *, edit: bool) -> None:
        simulation.advance(player_id)
        old, new = recruitment.set_player_multiplier(player_id, value)
        simulation.rescale_existing_timers(player_id, old, new)
        text = (
            "<b>⚙️ Скорость игры</b>\n\n"
            f"Множитель: <b>x{new:g}</b>\n"
            f"1 игровой час: ~{60/new:.1f} реальной мин.\n\n"
            "Игровые дедлайны пересчитаны.\n"
            "Payroll остаётся раз в реальные 24 часа."
        )
        if edit:
            await target.edit_text(text, reply_markup=keyboard(new))
        else:
            await target.answer(text, reply_markup=keyboard(new))

    @router.message(Command("speed"))
    async def speed(message: Message) -> None:
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
            await apply_speed(message, message.from_user.id, value, edit=False)
            return
        current = simulation.effective_speed(message.from_user.id)
        await message.answer(
            "<b>⚙️ Скорость игры</b>\n\n"
            f"Сейчас: <b>x{current:g}</b>\n\n"
            "Быстрый выбор:",
            reply_markup=keyboard(current),
        )

    @router.message(Command("admin"))
    async def admin(message: Message) -> None:
        if message.from_user.id not in admin_ids:
            return
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        current = simulation.effective_speed(message.from_user.id)
        await message.answer(
            "<b>🛠 Админ-панель</b>\n\n"
            f"Скорость: <b>x{current:g}</b>\n\n"
            "Быстрый выбор:",
            reply_markup=keyboard(current),
        )

    @router.callback_query(F.data.startswith("admin:speed:"))
    async def speed_callback(callback: CallbackQuery) -> None:
        if callback.from_user.id not in admin_ids:
            await callback.answer("Нет доступа", show_alert=True)
            return
        await callback.answer()
        value = float(callback.data.split(":")[2])
        await apply_speed(callback.message, callback.from_user.id, value, edit=True)

    @router.message(Command("tick"))
    async def tick(message: Message) -> None:
        if message.from_user.id not in admin_ids:
            return
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        speed_value = simulation.effective_speed(message.from_user.id)

        # Existing deadlines are moved by six game hours; payroll is deliberately excluded.
        simulation.fast_forward_timers(message.from_user.id, 6)
        with db.connect() as conn:
            conn.execute(
                "UPDATE shops SET last_simulated_at=? WHERE player_id=?",
                (iso(utcnow() - timedelta(hours=6 / speed_value)), message.from_user.id),
            )

        result = simulation.advance(message.from_user.id)
        candidates = recruitment.fast_forward(message.from_user.id, 6)
        await message.answer(
            "<b>⏩ Тестовый тик</b>\n\n"
            "Промотано: <b>6 игровых часов</b>\n\n"
            f"Заказов: {result.orders_created}\n"
            f"Диспутов: {result.disputes_created}\n"
            f"Событий: {result.messages_created}\n"
            f"Новых кандидатов: {candidates}\n\n"
            "Payroll не проматывается."
        )

    return router
