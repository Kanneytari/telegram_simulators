from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .employee_rename import rename_employee


class RenameEmployeeState(StatesGroup):
    waiting_for_name = State()


def employee_profile_keyboard(employee_id: int, role: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"employee:rename:{employee_id}")],
        [InlineKeyboardButton(text="💰 Условия работы", callback_data=f"team:terms:{role}")],
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
    router = Router(name="employee-profile")

    async def present(
        target: Message,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
    ) -> None:
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

    @router.callback_query(F.data.startswith("employee:rename:"))
    async def start_rename(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        try:
            employee_id = int((callback.data or "").split(":")[2])
        except (IndexError, ValueError):
            return
        with game.db.connect() as conn:
            employee = conn.execute(
                "SELECT alias FROM employees WHERE id=? AND player_id=? AND active=1",
                (employee_id, callback.from_user.id),
            ).fetchone()
        if not employee:
            await present(callback.message, "Сотрудник больше недоступен.")
            return
        await state.set_state(RenameEmployeeState.waiting_for_name)
        await state.update_data(employee_id=employee_id)
        await present(
            callback.message,
            f"<b>✏️ Переименовать сотрудника</b>\n\n"
            f"Текущее имя: <b>{employee['alias']}</b>\n\n"
            "Отправь новое имя следующим сообщением. Максимум 24 символа.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data=f"employee:{employee_id}")],
            ]),
        )

    @router.message(RenameEmployeeState.waiting_for_name)
    async def finish_rename(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        employee_id = int(data.get("employee_id", 0))
        result = rename_employee(
            game,
            message.from_user.id,
            employee_id,
            message.text or "",
        )
        if result["status"] in {"invalid", "duplicate"}:
            await message.answer(
                f"{result['text']}\n\nОтправь другое имя.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Отмена", callback_data=f"employee:{employee_id}")],
                ]),
            )
            return

        await state.clear()
        await message.answer(
            result["text"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")],
                [
                    InlineKeyboardButton(text="← Команда", callback_data="menu:team"),
                    InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
                ],
            ]),
        )

    return router
