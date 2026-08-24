from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


def build_workflow_allocation_router(game) -> Router:
    router = Router(name="retail-allocation-controls")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    async def render(target: Message, player_id: int, batch_id: int, employee_id: int, quantity: int) -> None:
        batch, staff = game.retail_staff_for_batch(player_id, batch_id)
        employee = next((row for row in staff if row["id"] == employee_id), None)
        if not batch or not employee or batch["status"] != "warehouse":
            await present(target, "Партия или сотрудник уже недоступны.", InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="← Команда", callback_data="menu:team")
            ]]))
            return
        quantity = max(1, min(int(quantity), int(batch["remaining"])))
        value = quantity * int(batch["unit_cost"])
        exposure_after = int(employee["exposure"]) + value
        unsecured = max(0, exposure_after - int(employee["deposit"]))
        rule = game.global_packaging_rule(player_id)
        mix = f"×1 {rule['pct_1']}% · ×2 {rule['pct_2']}% · ×5 {rule['pct_5']}%"
        risk = (
            f"🔴 Не покрыто депозитом после получения: <b>{unsecured:,} ₽</b>"
            if unsecured else "Объём полностью покрывается депозитом."
        )
        text = (
            f"<b>Распределить товар</b>\n\n"
            f"Сотрудник: <b>{employee['alias']}</b>\n"
            f"Количество: <b>{quantity} ед.</b>\n"
            f"Себестоимость: {value:,} ₽\n\n"
            f"Товар на руках сейчас: {employee['exposure']:,} ₽\n"
            f"Депозит: {employee['deposit']:,} ₽\n"
            f"{risk}\n\n"
            f"Фасовки по общей настройке команды:\n{mix}"
        )
        presets = sorted({min(int(batch["remaining"]), value) for value in (5, 10, 25, 50, 100) if value <= int(batch["remaining"])})
        rows = []
        if presets:
            rows.append([
                InlineKeyboardButton(text=str(value), callback_data=f"workflow:alloc:{batch_id}:{employee_id}:{value}")
                for value in presets[:5]
            ])
        rows.append([
            InlineKeyboardButton(text="−10", callback_data=f"workflow:alloc:{batch_id}:{employee_id}:{max(1,quantity-10)}"),
            InlineKeyboardButton(text="−5", callback_data=f"workflow:alloc:{batch_id}:{employee_id}:{max(1,quantity-5)}"),
            InlineKeyboardButton(text="+5", callback_data=f"workflow:alloc:{batch_id}:{employee_id}:{min(int(batch['remaining']),quantity+5)}"),
            InlineKeyboardButton(text="+10", callback_data=f"workflow:alloc:{batch_id}:{employee_id}:{min(int(batch['remaining']),quantity+10)}"),
        ])
        rows.append([InlineKeyboardButton(
            text=f"Всё · {int(batch['remaining'])} ед.",
            callback_data=f"workflow:alloc:{batch_id}:{employee_id}:{int(batch['remaining'])}",
        )])
        rows.append([InlineKeyboardButton(text="✅ Назначить", callback_data=f"workflow:allocconfirm:{batch_id}:{employee_id}:{quantity}")])
        rows.append([InlineKeyboardButton(text="← Партия", callback_data=f"workflow:batch:{batch_id}")])
        await present(target, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("workflow:alloc:") & ~F.data.startswith("workflow:allocconfirm:"))
    async def allocation(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, batch_id, employee_id, quantity = callback.data.split(":")
        await render(callback.message, callback.from_user.id, int(batch_id), int(employee_id), int(quantity))

    @router.callback_query(F.data.startswith("workflow:allocconfirm:"))
    async def confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, batch_id, employee_id, quantity = callback.data.split(":")
        result = game.allocate_to_retail(callback.from_user.id, int(batch_id), int(employee_id), int(quantity))
        await present(callback.message, f"<b>📦 Распределение</b>\n\n{result}", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Партия", callback_data=f"workflow:batch:{batch_id}")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ]))

    return router
