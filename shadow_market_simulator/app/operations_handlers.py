from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


def build_operations_router(game) -> Router:
    router = Router(name="operations-management")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def offer_by_id(player_id: int, offer_id: int):
        return {int(row["id"]): row for row in game.offers(player_id)}.get(offer_id)

    def offer_staff_keyboard(offer_id: int, staff) -> InlineKeyboardMarkup:
        rows = []
        for employee in staff:
            marker = "✅" if employee["eligible"] else "▫️"
            rows.append([
                InlineKeyboardButton(
                    text=f"{marker} {employee['alias']} · свободно {employee['free_coverage']:,} ₽",
                    callback_data=(
                        f"offer:staff:{offer_id}:{employee['id']}"
                        if employee["eligible"] else "offer:no_coverage"
                    ),
                )
            ])
        rows.append([
            InlineKeyboardButton(text="← Закупки", callback_data="menu:offers"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def show_offer_staff(target: Message, player_id: int, offer_id: int) -> None:
        offer = offer_by_id(player_id, offer_id)
        if not offer:
            await present(target, "Предложение больше недоступно.", InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="← Закупки", callback_data="menu:offers")
            ]]))
            return
        total = int(offer["quantity"] * offer["unit_cost"])
        staff = game.warehouse_staff_for_offer(player_id, offer_id)
        text = (
            f"<b>📦 {offer['product_title']}</b>\n\n"
            f"Партия: {offer['quantity']} ед.\n"
            f"Стоимость: <b>{total:,} ₽</b>\n\n"
            "<b>Ответственный сотрудник</b>\n"
            "Партия закрепляется за оптовым сотрудником. Его свободный депозит должен покрывать стоимость партии."
        )
        if not staff:
            text += "\n\n🔴 В команде нет активных оптовых сотрудников."
        elif not any(row["eligible"] for row in staff):
            text += "\n\n🔴 Ни у одного сотрудника не хватает свободного покрытия."
        await present(target, text, offer_staff_keyboard(offer_id, staff))

    @router.callback_query(
        F.data.startswith("offer:")
        & ~F.data.startswith("offer:staff:")
        & ~F.data.startswith("offer:purchase:")
        & ~F.data.startswith("offer:confirm:")
        & ~F.data.startswith("offer:buy:")
        & ~F.data.startswith("offer:no_coverage")
    )
    async def offer_open(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = callback.data.split(":")
        if len(parts) != 2 or not parts[1].isdigit():
            return
        await show_offer_staff(callback.message, callback.from_user.id, int(parts[1]))

    @router.callback_query(F.data.startswith("offer:confirm:"))
    @router.callback_query(F.data.startswith("offer:buy:"))
    async def offer_legacy_buy(callback: CallbackQuery) -> None:
        await callback.answer()
        await show_offer_staff(callback.message, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data == "offer:no_coverage")
    async def no_coverage(callback: CallbackQuery) -> None:
        await callback.answer("Депозит не покрывает стоимость новой партии", show_alert=True)

    @router.callback_query(F.data.startswith("offer:staff:"))
    async def offer_staff(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, offer_id, employee_id = callback.data.split(":")
        offer = offer_by_id(callback.from_user.id, int(offer_id))
        staff = game.warehouse_staff_for_offer(callback.from_user.id, int(offer_id))
        employee = next((row for row in staff if row["id"] == int(employee_id)), None)
        if not offer or not employee or not employee["eligible"]:
            await show_offer_staff(callback.message, callback.from_user.id, int(offer_id))
            return
        total = int(offer["quantity"] * offer["unit_cost"])
        text = (
            "<b>Подтвердить закупку?</b>\n\n"
            f"Товар: {offer['product_title']}\n"
            f"Количество: {offer['quantity']} ед.\n"
            f"Стоимость: <b>{total:,} ₽</b>\n\n"
            f"Ответственный: <b>{employee['alias']}</b>\n"
            f"Текущая ответственность: {employee['exposure']:,} ₽\n"
            f"Свободное покрытие: {employee['free_coverage']:,} ₽"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Купить", callback_data=f"offer:purchase:{offer_id}:{employee_id}")],
            [InlineKeyboardButton(text="← Выбрать сотрудника", callback_data=f"offer:{offer_id}")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ])
        await present(callback.message, text, keyboard)

    @router.callback_query(F.data.startswith("offer:purchase:"))
    async def offer_purchase(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, offer_id, employee_id = callback.data.split(":")
        result = game.buy_offer_for_employee(callback.from_user.id, int(offer_id), int(employee_id))
        await present(
            callback.message,
            f"<b>📦 Закупка</b>\n\n{result}",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← Закупки", callback_data="menu:offers")],
                [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
            ]),
        )

    def employee_keyboard(employee_id: int, is_warehouse: bool, active: bool) -> InlineKeyboardMarkup:
        rows = [[InlineKeyboardButton(text="⭐ Отзывы о работе", callback_data=f"employee:reviews:{employee_id}")]]
        if is_warehouse:
            rows.append([InlineKeyboardButton(text="📦 Партии на ответственности", callback_data=f"employee:batches:{employee_id}")])
        if active:
            rows.append([InlineKeyboardButton(text="Уволить сотрудника", callback_data=f"employee:fire:{employee_id}")])
        rows.append([
            InlineKeyboardButton(text="← Команда", callback_data="menu:team"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @router.callback_query(
        F.data.startswith("employee:")
        & ~F.data.startswith("employee:reviews:")
        & ~F.data.startswith("employee:batches:")
        & ~F.data.startswith("employee:fire:")
        & ~F.data.startswith("employee:fireconfirm:")
        & ~F.data.startswith("employee:action:")
    )
    async def employee_profile(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = callback.data.split(":")
        if len(parts) != 2 or not parts[1].isdigit():
            return
        employee_id = int(parts[1])
        text = game.employee_details(callback.from_user.id, employee_id)
        if not text:
            await present(callback.message, "Сотрудник не найден.", InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="← Команда", callback_data="menu:team")
            ]]))
            return
        with game.db.connect() as conn:
            employee = conn.execute("SELECT role, active FROM employees WHERE id=? AND player_id=?", (employee_id, callback.from_user.id)).fetchone()
        await present(callback.message, text, employee_keyboard(employee_id, employee["role"] == "warehouse", bool(employee["active"])))

    def review_lines(reviews, include_employee: bool) -> str:
        if not reviews:
            return "Отзывов пока нет."
        blocks = []
        for row in reviews:
            date = str(row["created_at"])[:10]
            stars = "★" * int(row["rating"]) + "☆" * (5 - int(row["rating"]))
            head = f"{row['product_title']} × {row['quantity']} · {date}"
            if include_employee:
                head += f" · {row['employee_alias']}"
            blocks.append(f"<b>{head}</b>\n{stars}\n{row['text']}")
        return "\n\n".join(blocks)

    @router.callback_query(F.data.startswith("employee:reviews:"))
    async def employee_reviews(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        reviews = game.employee_reviews(callback.from_user.id, employee_id)
        with game.db.connect() as conn:
            employee = conn.execute("SELECT alias FROM employees WHERE id=? AND player_id=?", (employee_id, callback.from_user.id)).fetchone()
        title = employee["alias"] if employee else "Сотрудник"
        await present(
            callback.message,
            f"<b>⭐ Отзывы · {title}</b>\n\n{review_lines(reviews, False)}",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")],
                [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
            ]),
        )

    @router.callback_query(F.data.startswith("employee:fire:") & ~F.data.startswith("employee:fireconfirm:"))
    async def fire_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        with game.db.connect() as conn:
            employee = conn.execute("SELECT * FROM employees WHERE id=? AND player_id=? AND active=1", (employee_id, callback.from_user.id)).fetchone()
        if not employee:
            await present(callback.message, "Сотрудник уже не работает.", InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="← Команда", callback_data="menu:team")
            ]]))
            return
        payout = int(employee["deposit"]) + int(employee["wages_accrued"])
        text = (
            f"<b>Уволить {employee['alias']}?</b>\n\n"
            f"Депозит к возврату: {employee['deposit']:,} ₽\n"
            f"Начисленная зарплата: {employee['wages_accrued']:,} ₽\n"
            f"Итоговый расчёт: <b>{payout:,} ₽</b>\n\n"
            "Для оптового сотрудника сначала должны быть переданы все партии на ответственности."
        )
        await present(callback.message, text, InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить увольнение", callback_data=f"employee:fireconfirm:{employee_id}")],
            [InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")],
        ]))

    @router.callback_query(F.data.startswith("employee:fireconfirm:"))
    async def fire_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        result = game.fire_employee(callback.from_user.id, employee_id)
        back = f"employee:{employee_id}" if result["status"] == "inventory" else "menu:team"
        label = "← Профиль" if result["status"] == "inventory" else "← Команда"
        await present(callback.message, f"<b>👥 Команда</b>\n\n{result['message']}", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=back)],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ]))

    @router.callback_query(F.data.startswith("employee:batches:"))
    async def employee_batches(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        batches = game.employee_inventory(callback.from_user.id, employee_id)
        with game.db.connect() as conn:
            employee = conn.execute("SELECT alias FROM employees WHERE id=? AND player_id=?", (employee_id, callback.from_user.id)).fetchone()
        rows = []
        for batch in batches:
            value = int(batch["remaining"] * batch["unit_cost"])
            rows.append([InlineKeyboardButton(
                text=f"#{batch['id']} · {batch['product_title']} · {value:,} ₽",
                callback_data=f"batch:transfer:{batch['id']}",
            )])
        rows.append([InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")])
        text = f"<b>📦 Партии · {employee['alias'] if employee else 'Сотрудник'}</b>\n\n"
        if batches:
            text += "Выбери партию, если хочешь передать ответственность другому сотруднику."
        else:
            text += "Активных партий на ответственности нет."
        await present(callback.message, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("batch:transfer:"))
    async def batch_transfer(callback: CallbackQuery) -> None:
        await callback.answer()
        batch_id = int(callback.data.split(":")[2])
        batch, options = game.batch_transfer_options(callback.from_user.id, batch_id)
        if not batch:
            await present(callback.message, "Партия больше недоступна.", InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="← Команда", callback_data="menu:team")
            ]]))
            return
        value = int(batch["remaining"] * batch["unit_cost"])
        rows = []
        for employee in options:
            rows.append([InlineKeyboardButton(
                text=f"{'✅' if employee['eligible'] else '▫️'} {employee['alias']} · {employee['free']:,} ₽",
                callback_data=f"batch:assign:{batch_id}:{employee['id']}" if employee["eligible"] else "offer:no_coverage",
            )])
        rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"employee:batches:{batch['responsible_employee_id']}")])
        await present(
            callback.message,
            f"<b>Передать партию #{batch_id}</b>\n\nСтоимость остатка: <b>{value:,} ₽</b>\n\nВыбери оптового сотрудника с достаточным свободным покрытием.",
            InlineKeyboardMarkup(inline_keyboard=rows),
        )

    @router.callback_query(F.data.startswith("batch:assign:"))
    async def batch_assign(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, batch_id, employee_id = callback.data.split(":")
        result = game.reassign_batch(callback.from_user.id, int(batch_id), int(employee_id))
        await present(callback.message, f"<b>📦 Ответственность изменена</b>\n\n{result}", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Команда", callback_data="menu:team")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ]))

    @router.callback_query(F.data.startswith("store:reviews:"))
    async def product_reviews(callback: CallbackQuery) -> None:
        await callback.answer()
        product_id = int(callback.data.split(":")[2])
        reviews = game.product_reviews(callback.from_user.id, product_id)
        with game.db.connect() as conn:
            product = conn.execute("SELECT title FROM products WHERE id=?", (product_id,)).fetchone()
        title = product["title"] if product else "Товар"
        await present(
            callback.message,
            f"<b>⭐ Отзывы · {title}</b>\n\n{review_lines(reviews, True)}",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← Товар", callback_data=f"store:product:{product_id}")],
                [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
            ]),
        )

    return router
