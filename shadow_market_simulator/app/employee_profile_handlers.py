from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


def employee_profile_keyboard(employee_id: int, role: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="⭐ Отзывы о работе", callback_data=f"employee:reviews:{employee_id}")],
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"employee:rename:{employee_id}")],
        [InlineKeyboardButton(text="💰 Доля в депозит", callback_data=f"employee:depositshare:{employee_id}:current")],
    ]
    if role == "warehouse":
        rows.append([
            InlineKeyboardButton(
                text="📦 Партии и распределение",
                callback_data=f"workflow:batches:{employee_id}",
            )
        ])
    rows.extend([
        [InlineKeyboardButton(text="🔁 Сменить роль", callback_data=f"workflow:role:{employee_id}")],
        [InlineKeyboardButton(text="Уволить сотрудника", callback_data=f"employee:fire:{employee_id}")],
        [
            InlineKeyboardButton(text="← Команда", callback_data="menu:team"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_employee_profile_router(game) -> Router:
    """Own the employee profile so packaging remains a Team-wide setting only."""
    router = Router(name="employee-profile-global-packaging")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    @router.callback_query(F.data.regexp(r"^employee:\d+$"))
    async def employee_profile(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        employee_id = int((callback.data or "").split(":")[1])
        text = game.employee_details(callback.from_user.id, employee_id)
        with game.db.connect() as conn:
            employee = conn.execute(
                "SELECT role FROM employees WHERE id=? AND player_id=? AND active=1",
                (employee_id, callback.from_user.id),
            ).fetchone()
        if not text or not employee:
            await present(
                callback.message,
                "Сотрудник не найден.",
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="← Команда", callback_data="menu:team")],
                    [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
                ]),
            )
            return
        await present(
            callback.message,
            text,
            employee_profile_keyboard(employee_id, employee["role"]),
        )

    return router
