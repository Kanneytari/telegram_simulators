from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .courier_management import BONUS_COST, DEPOSIT_PCTS, DEPOSIT_TARGETS, PHONE, REST_OPTIONS, TRANSPORT


def courier_management_keyboard(employee_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"🎁 Премия {BONUS_COST:,} ₽",
                callback_data=f"employee:manage:bonus:{employee_id}",
            ),
            InlineKeyboardButton(
                text="🏖 Отдых",
                callback_data=f"employee:manage:rest:{employee_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="💰 Депозит",
                callback_data=f"employee:manage:deposit:{employee_id}",
            ),
            InlineKeyboardButton(
                text="🧰 Оснащение",
                callback_data=f"employee:manage:equipment:{employee_id}",
            ),
        ],
        [InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")],
        [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
    ])


def courier_rest_keyboard(employee_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"12 ч · {REST_OPTIONS[12]['cost']:,} ₽",
                callback_data=f"employee:manage:restdo:{employee_id}:12",
            ),
            InlineKeyboardButton(
                text=f"24 ч · {REST_OPTIONS[24]['cost']:,} ₽",
                callback_data=f"employee:manage:restdo:{employee_id}:24",
            ),
        ],
        [InlineKeyboardButton(text="← Управление", callback_data=f"employee:manage:{employee_id}")],
        [InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")],
    ])


def courier_deposit_keyboard(employee_id: int) -> InlineKeyboardMarkup:
    pct_row = [
        InlineKeyboardButton(
            text=f"{pct}%",
            callback_data=f"employee:manage:depositpct:{employee_id}:{pct}",
        )
        for pct in DEPOSIT_PCTS
    ]
    target_row = [
        InlineKeyboardButton(
            text=f"{target // 1000}k",
            callback_data=f"employee:manage:deposittarget:{employee_id}:{target}",
        )
        for target in DEPOSIT_TARGETS
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        pct_row,
        target_row,
        [InlineKeyboardButton(text="← Управление", callback_data=f"employee:manage:{employee_id}")],
        [InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")],
    ])


def courier_equipment_keyboard(game, player_id: int, employee_id: int) -> InlineKeyboardMarkup:
    snapshot = game.courier_management_snapshot(player_id, employee_id)
    rows: list[list[InlineKeyboardButton]] = []
    if snapshot:
        t_level = int(snapshot["transport_level"])
        p_level = int(snapshot["phone_level"])
        if t_level < 2:
            next_level = t_level + 1
            rows.append([
                InlineKeyboardButton(
                    text=f"🛵 {TRANSPORT[next_level][0]} · {TRANSPORT[next_level][1]:,} ₽",
                    callback_data=f"employee:manage:upgrade:{employee_id}:transport",
                )
            ])
        if p_level < 2:
            next_level = p_level + 1
            rows.append([
                InlineKeyboardButton(
                    text=f"📱 {PHONE[next_level][0]} · {PHONE[next_level][1]:,} ₽",
                    callback_data=f"employee:manage:upgrade:{employee_id}:phone",
                )
            ])
    rows.extend([
        [InlineKeyboardButton(text="← Управление", callback_data=f"employee:manage:{employee_id}")],
        [InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_courier_management_router(game) -> Router:
    router = Router(name="courier-management")

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

    async def management_screen(callback: CallbackQuery, employee_id: int, notice: str | None = None) -> None:
        text = game.courier_management_text(callback.from_user.id, employee_id)
        if not text:
            await present(
                callback.message,
                "Сотрудник недоступен.",
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="← Команда", callback_data="menu:team")],
                    [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
                ]),
            )
            return
        if notice:
            text = f"{notice}\n\n{text}"
        await present(callback.message, text, courier_management_keyboard(employee_id))

    @router.callback_query(F.data.regexp(r"^employee:manage:\d+$"))
    async def management(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int((callback.data or "").split(":")[2])
        await management_screen(callback, employee_id)

    @router.callback_query(F.data.startswith("employee:manage:bonus:"))
    async def bonus(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            employee_id = int((callback.data or "").split(":")[3])
        except (IndexError, ValueError):
            return
        result = game.give_bonus(callback.from_user.id, employee_id)
        await management_screen(callback, employee_id, result["message"])

    @router.callback_query(F.data.startswith("employee:manage:rest:"))
    async def rest_menu(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            employee_id = int((callback.data or "").split(":")[3])
        except (IndexError, ValueError):
            return
        text = game.courier_rest_text(callback.from_user.id, employee_id)
        if not text:
            await management_screen(callback, employee_id)
            return
        await present(callback.message, text, courier_rest_keyboard(employee_id))

    @router.callback_query(F.data.startswith("employee:manage:restdo:"))
    async def rest_do(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            parts = (callback.data or "").split(":")
            employee_id = int(parts[3])
            hours = int(parts[4])
        except (IndexError, ValueError):
            return
        result = game.send_to_rest(callback.from_user.id, employee_id, hours)
        await management_screen(callback, employee_id, result["message"])

    @router.callback_query(F.data.startswith("employee:manage:deposit:"))
    async def deposit_menu(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            employee_id = int((callback.data or "").split(":")[3])
        except (IndexError, ValueError):
            return
        text = game.courier_deposit_text(callback.from_user.id, employee_id)
        if not text:
            await management_screen(callback, employee_id)
            return
        await present(callback.message, text, courier_deposit_keyboard(employee_id))

    @router.callback_query(F.data.startswith("employee:manage:depositpct:"))
    async def deposit_pct(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            parts = (callback.data or "").split(":")
            employee_id = int(parts[3])
            pct = int(parts[4])
        except (IndexError, ValueError):
            return
        result = game.set_deposit_plan(callback.from_user.id, employee_id, pct)
        text = game.courier_deposit_text(callback.from_user.id, employee_id)
        if not text:
            await management_screen(callback, employee_id, result["message"])
            return
        await present(
            callback.message,
            f"{result['message']}\n\n{text}",
            courier_deposit_keyboard(employee_id),
        )

    @router.callback_query(F.data.startswith("employee:manage:deposittarget:"))
    async def deposit_target(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            parts = (callback.data or "").split(":")
            employee_id = int(parts[3])
            target = int(parts[4])
        except (IndexError, ValueError):
            return
        result = game.set_deposit_target(callback.from_user.id, employee_id, target)
        text = game.courier_deposit_text(callback.from_user.id, employee_id)
        if not text:
            await management_screen(callback, employee_id, result["message"])
            return
        await present(
            callback.message,
            f"{result['message']}\n\n{text}",
            courier_deposit_keyboard(employee_id),
        )

    @router.callback_query(F.data.startswith("employee:manage:equipment:"))
    async def equipment_menu(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            employee_id = int((callback.data or "").split(":")[3])
        except (IndexError, ValueError):
            return
        text = game.courier_equipment_text(callback.from_user.id, employee_id)
        if not text:
            await management_screen(callback, employee_id)
            return
        await present(
            callback.message,
            text,
            courier_equipment_keyboard(game, callback.from_user.id, employee_id),
        )

    @router.callback_query(F.data.startswith("employee:manage:upgrade:"))
    async def upgrade(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            parts = (callback.data or "").split(":")
            employee_id = int(parts[3])
            slot = parts[4]
        except (IndexError, ValueError):
            return
        result = game.upgrade_equipment(callback.from_user.id, employee_id, slot)
        text = game.courier_equipment_text(callback.from_user.id, employee_id)
        if not text:
            await management_screen(callback, employee_id, result["message"])
            return
        await present(
            callback.message,
            f"{result['message']}\n\n{text}",
            courier_equipment_keyboard(game, callback.from_user.id, employee_id),
        )

    return router
