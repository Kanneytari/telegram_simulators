from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


def build_workflow_router(game) -> Router:
    router = Router(name="staff-workflow")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def nav(back: str, label: str = "← Назад") -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=back), InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")]
        ])

    def offer_by_id(player_id: int, offer_id: int):
        return {int(row["id"]): row for row in game.offers(player_id)}.get(offer_id)

    async def show_offer_staff(target: Message, player_id: int, offer_id: int) -> None:
        offer = offer_by_id(player_id, offer_id)
        if not offer:
            await present(target, "Предложение больше недоступно.", nav("menu:offers", "← Закупки"))
            return
        total = int(offer["quantity"] * offer["unit_cost"])
        staff = game.warehouse_staff_for_offer(player_id, offer_id)
        rows = []
        for employee in staff:
            unsecured = int(employee.get("unsecured_after", 0))
            if unsecured:
                label = f"🔴 {employee['alias']} · сверх депозита {unsecured:,} ₽"
            else:
                label = f"✅ {employee['alias']} · покрыто депозитом"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"workflow:offerstaff:{offer_id}:{employee['id']}")])
        rows.append([InlineKeyboardButton(text="← Закупки", callback_data="menu:offers"), InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")])
        text = (
            f"<b>📦 {offer['product_title']}</b>\n\n"
            f"Партия: {offer['quantity']} ед.\n"
            f"Стоимость: <b>{total:,} ₽</b>\n\n"
            "<b>Кому доверить партию</b>\n"
            "Депозит не является жёстким лимитом. Можно передать сотруднику товар сверх покрытия, но риск потери возрастёт."
        )
        if not staff:
            text += "\n\n🔴 Нет активного оптового сотрудника."
        await present(target, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(
        F.data.startswith("offer:")
        & ~F.data.startswith("offer:purchase:")
        & ~F.data.startswith("offer:staff:")
        & ~F.data.startswith("offer:no_coverage")
    )
    async def offer_entry(callback: CallbackQuery) -> None:
        parts = callback.data.split(":")
        offer_id = None
        if len(parts) == 2 and parts[1].isdigit():
            offer_id = int(parts[1])
        elif len(parts) >= 3 and parts[2].isdigit() and parts[1] in {"confirm", "buy"}:
            offer_id = int(parts[2])
        if offer_id is None:
            return
        await callback.answer()
        await show_offer_staff(callback.message, callback.from_user.id, offer_id)

    @router.callback_query(F.data.startswith("workflow:offerstaff:"))
    async def offer_staff(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, offer_id, employee_id = callback.data.split(":")
        offer = offer_by_id(callback.from_user.id, int(offer_id))
        staff = game.warehouse_staff_for_offer(callback.from_user.id, int(offer_id))
        employee = next((row for row in staff if row["id"] == int(employee_id)), None)
        if not offer or not employee:
            await show_offer_staff(callback.message, callback.from_user.id, int(offer_id))
            return
        total = int(offer["quantity"] * offer["unit_cost"])
        unsecured = int(employee["unsecured_after"])
        risk = (
            f"🔴 После закупки не покрыто депозитом: <b>{unsecured:,} ₽</b>\n"
            "Если сотрудник окажется недобросовестным, магазин рискует потерять часть или весь непокрытый товар."
            if unsecured else
            "Партия полностью покрывается текущим депозитом сотрудника."
        )
        text = (
            "<b>Подтвердить закупку?</b>\n\n"
            f"Товар: {offer['product_title']}\n"
            f"Количество: {offer['quantity']} ед.\n"
            f"Стоимость: <b>{total:,} ₽</b>\n\n"
            f"Ответственный: <b>{employee['alias']}</b>\n"
            f"Сейчас на ответственности: {employee['exposure']:,} ₽\n"
            f"Депозит: {employee['deposit']:,} ₽\n\n"
            f"{risk}"
        )
        await present(callback.message, text, InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Купить", callback_data=f"workflow:purchase:{offer_id}:{employee_id}")],
            [InlineKeyboardButton(text="← Выбрать сотрудника", callback_data=f"offer:{offer_id}")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ]))

    @router.callback_query(F.data.startswith("workflow:purchase:"))
    async def purchase(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, offer_id, employee_id = callback.data.split(":")
        result = game.buy_offer_for_employee(callback.from_user.id, int(offer_id), int(employee_id))
        await present(callback.message, f"<b>📦 Закупка</b>\n\n{result}", nav("menu:offers", "← Закупки"))

    def employee_keyboard(employee_id: int, role: str) -> InlineKeyboardMarkup:
        rows = [[InlineKeyboardButton(text="⭐ Отзывы о работе", callback_data=f"employee:reviews:{employee_id}")]]
        if role == "warehouse":
            rows.append([InlineKeyboardButton(text="📦 Партии и распределение", callback_data=f"workflow:batches:{employee_id}")])
        else:
            rows.append([InlineKeyboardButton(text="⚙️ Фасовки", callback_data=f"workflow:packemployee:{employee_id}")])
        rows.extend([
            [InlineKeyboardButton(text="🔁 Сменить роль", callback_data=f"workflow:role:{employee_id}")],
            [InlineKeyboardButton(text="Уволить сотрудника", callback_data=f"employee:fire:{employee_id}")],
            [InlineKeyboardButton(text="← Команда", callback_data="menu:team"), InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
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
        parts = callback.data.split(":")
        if len(parts) != 2 or not parts[1].isdigit():
            return
        await callback.answer()
        employee_id = int(parts[1])
        text = game.employee_details(callback.from_user.id, employee_id)
        with game.db.connect() as conn:
            employee = conn.execute("SELECT role FROM employees WHERE id=? AND player_id=? AND active=1", (employee_id, callback.from_user.id)).fetchone()
        if not text or not employee:
            await present(callback.message, "Сотрудник не найден.", nav("menu:team", "← Команда"))
            return
        await present(callback.message, text, employee_keyboard(employee_id, employee["role"]))

    @router.callback_query(F.data.startswith("workflow:role:"))
    async def role_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        with game.db.connect() as conn:
            employee = conn.execute("SELECT * FROM employees WHERE id=? AND player_id=? AND active=1", (employee_id, callback.from_user.id)).fetchone()
        if not employee:
            await present(callback.message, "Сотрудник недоступен.", nav("menu:team", "← Команда"))
            return
        current = "оптовый" if employee["role"] == "warehouse" else "розничный"
        new = "розничный" if employee["role"] == "warehouse" else "оптовый"
        await present(callback.message, (
            f"<b>Сменить роль · {employee['alias']}</b>\n\n"
            f"Сейчас: {current}\n"
            f"Новая роль: <b>{new}</b>\n\n"
            "Смена возможна только без товара на руках и незавершённых задач. Ставка перейдёт на базовый ориентир новой роли."
        ), InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Сменить роль", callback_data=f"workflow:roleconfirm:{employee_id}")],
            [InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")],
        ]))

    @router.callback_query(F.data.startswith("workflow:roleconfirm:"))
    async def role_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        result = game.change_employee_role(callback.from_user.id, employee_id)
        await present(callback.message, f"<b>👥 Роль сотрудника</b>\n\n{result}", nav(f"employee:{employee_id}", "← Профиль"))

    @router.callback_query(F.data.startswith("workflow:batches:"))
    @router.callback_query(F.data.startswith("employee:batches:"))
    async def batches(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        rows_data = game.active_batches(callback.from_user.id, employee_id)
        rows = []
        for batch in rows_data:
            state = "принимается" if batch["status"] == "receiving" else "готова"
            rows.append([InlineKeyboardButton(
                text=f"#{batch['id']} · {batch['product_title']} · {batch['remaining']} ед. · {state}",
                callback_data=f"workflow:batch:{batch['id']}",
            )])
        rows.append([InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")])
        text = "<b>📦 Партии на ответственности</b>\n\n"
        text += "Выбери готовую партию, чтобы распределить часть товара между розничными сотрудниками." if rows_data else "Активных партий нет."
        await present(callback.message, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("workflow:batch:"))
    async def batch(callback: CallbackQuery) -> None:
        await callback.answer()
        batch_id = int(callback.data.split(":")[2])
        batch_row, staff = game.retail_staff_for_batch(callback.from_user.id, batch_id)
        if not batch_row:
            await present(callback.message, "Партия не найдена.", nav("menu:team", "← Команда"))
            return
        with game.db.connect() as conn:
            product = conn.execute("SELECT title FROM products WHERE id=?", (batch_row["product_id"],)).fetchone()
        text = (
            f"<b>📦 Партия #{batch_id} · {product['title']}</b>\n\n"
            f"Статус: {'принимается' if batch_row['status']=='receiving' else 'готова к распределению'}\n"
            f"Осталось у оптового сотрудника: <b>{batch_row['remaining']} ед.</b>\n"
            f"Себестоимость остатка: {int(batch_row['remaining']*batch_row['unit_cost']):,} ₽"
        )
        rows = []
        if batch_row["status"] == "warehouse":
            text += "\n\n<b>Передать рознице</b>\nВыбери сотрудника и затем количество."
            for employee in staff:
                unsecured_now = max(0, employee["exposure"] - employee["deposit"])
                extra = f" · 🔴 {unsecured_now:,} ₽" if unsecured_now else ""
                rows.append([InlineKeyboardButton(
                    text=f"{employee['alias']} · депозит {employee['deposit']:,} ₽{extra}",
                    callback_data=f"workflow:alloc:{batch_id}:{employee['id']}:10",
                )])
        rows.append([InlineKeyboardButton(text="← Партии", callback_data=f"workflow:batches:{batch_row['responsible_employee_id']}")])
        await present(callback.message, text, InlineKeyboardMarkup(inline_keyboard=rows))

    async def allocation_screen(target: Message, player_id: int, batch_id: int, employee_id: int, quantity: int) -> None:
        batch, staff = game.retail_staff_for_batch(player_id, batch_id)
        employee = next((row for row in staff if row["id"] == employee_id), None)
        if not batch or not employee or batch["status"] != "warehouse":
            await present(target, "Партия или сотрудник уже недоступны.", nav("menu:team", "← Команда"))
            return
        quantity = max(1, min(int(quantity), int(batch["remaining"])))
        value = quantity * int(batch["unit_cost"])
        after = int(employee["exposure"]) + value
        unsecured = max(0, after - int(employee["deposit"]))
        warning = f"\n\n🔴 Не покрыто депозитом после получения: <b>{unsecured:,} ₽</b>" if unsecured else "\n\nОбъём полностью покрывается депозитом."
        text = (
            f"<b>Распределение партии #{batch_id}</b>\n\n"
            f"Сотрудник: <b>{employee['alias']}</b>\n"
            f"Количество: <b>{quantity} ед.</b>\n"
            f"Стоимость по себестоимости: {value:,} ₽\n"
            f"Текущий товар на руках: {employee['exposure']:,} ₽\n"
            f"Депозит: {employee['deposit']:,} ₽"
            f"{warning}"
        )
        rows = [
            [
                InlineKeyboardButton(text="−10", callback_data=f"workflow:alloc:{batch_id}:{employee_id}:{max(1,quantity-10)}"),
                InlineKeyboardButton(text="−5", callback_data=f"workflow:alloc:{batch_id}:{employee_id}:{max(1,quantity-5)}"),
                InlineKeyboardButton(text="+5", callback_data=f"workflow:alloc:{batch_id}:{employee_id}:{min(int(batch['remaining']),quantity+5)}"),
                InlineKeyboardButton(text="+10", callback_data=f"workflow:alloc:{batch_id}:{employee_id}:{min(int(batch['remaining']),quantity+10)}"),
            ],
            [InlineKeyboardButton(text="✅ Передать", callback_data=f"workflow:allocconfirm:{batch_id}:{employee_id}:{quantity}")],
            [InlineKeyboardButton(text="← Партия", callback_data=f"workflow:batch:{batch_id}")],
        ]
        await present(target, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("workflow:alloc:"))
    async def allocation(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, batch_id, employee_id, quantity = callback.data.split(":")
        await allocation_screen(callback.message, callback.from_user.id, int(batch_id), int(employee_id), int(quantity))

    @router.callback_query(F.data.startswith("workflow:allocconfirm:"))
    async def allocation_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, batch_id, employee_id, quantity = callback.data.split(":")
        result = game.allocate_to_retail(callback.from_user.id, int(batch_id), int(employee_id), int(quantity))
        await present(callback.message, f"<b>📦 Распределение</b>\n\n{result}", nav(f"workflow:batch:{batch_id}", "← Партия"))

    @router.callback_query(F.data == "team:unassigned")
    async def unassigned(callback: CallbackQuery) -> None:
        await callback.answer()
        batches = game.unassigned_batches(callback.from_user.id)
        rows = [[InlineKeyboardButton(
            text=f"#{row['id']} · {row['product_title']} · {row['remaining']} ед.",
            callback_data=f"workflow:unassigned:{row['id']}",
        )] for row in batches]
        rows.append([InlineKeyboardButton(text="← Команда", callback_data="menu:team")])
        text = "<b>📦 Неназначенные партии</b>\n\n"
        text += "Выбери партию и назначь нового ответственного." if batches else "Все активные партии закреплены за сотрудниками."
        await present(callback.message, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("workflow:unassigned:"))
    async def unassigned_batch(callback: CallbackQuery) -> None:
        await callback.answer()
        batch_id = int(callback.data.split(":")[2])
        batches = {int(row["id"]): row for row in game.unassigned_batches(callback.from_user.id)}
        batch = batches.get(batch_id)
        if not batch:
            await present(callback.message, "Партия уже назначена.", nav("team:unassigned"))
            return
        with game.db.connect() as conn:
            staff = conn.execute("SELECT * FROM employees WHERE player_id=? AND active=1 AND role='warehouse' ORDER BY deposit DESC", (callback.from_user.id,)).fetchall()
        rows = []
        for employee in staff:
            exposure = game._employee_exposure(callback.from_user.id, int(employee["id"]))
            after = exposure + int(batch["remaining"]*batch["unit_cost"])
            unsecured = max(0, after-int(employee["deposit"]))
            label = f"🔴 {employee['alias']} · +{unsecured:,} ₽ риска" if unsecured else f"✅ {employee['alias']} · покрыто"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"workflow:unassignedassign:{batch_id}:{employee['id']}")])
        rows.append([InlineKeyboardButton(text="← Партии", callback_data="team:unassigned")])
        await present(callback.message, f"<b>Назначить партию #{batch_id}</b>\n\nОстаток: {batch['remaining']} ед.\nСтоимость: {int(batch['remaining']*batch['unit_cost']):,} ₽", InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("workflow:unassignedassign:"))
    async def unassigned_assign(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, batch_id, employee_id = callback.data.split(":")
        result = game.assign_unassigned_batch(callback.from_user.id, int(batch_id), int(employee_id))
        await present(callback.message, f"<b>📦 Ответственность</b>\n\n{result}", nav("team:unassigned", "← Партии"))

    @router.callback_query(F.data == "team:packrules")
    async def pack_team(callback: CallbackQuery) -> None:
        await callback.answer()
        with game.db.connect() as conn:
            employees = conn.execute("SELECT id, alias FROM employees WHERE player_id=? AND active=1 AND role='courier' ORDER BY alias", (callback.from_user.id,)).fetchall()
        rows = [[InlineKeyboardButton(text=row["alias"], callback_data=f"workflow:packemployee:{row['id']}")] for row in employees]
        rows.append([InlineKeyboardButton(text="← Команда", callback_data="menu:team")])
        await present(callback.message, "<b>⚙️ Распределение по фасовкам</b>\n\nНастрой правила каждого розничного сотрудника. Они применяются к следующему полученному им товару.", InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("workflow:packemployee:"))
    async def pack_employee(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        rules = game.packaging_rules(callback.from_user.id, employee_id)
        with game.db.connect() as conn:
            employee = conn.execute("SELECT alias FROM employees WHERE id=? AND player_id=?", (employee_id, callback.from_user.id)).fetchone()
        rows = [[InlineKeyboardButton(
            text=f"{rule['product_title']} · {rule['pct_1']}/{rule['pct_2']}/{rule['pct_5']}%",
            callback_data=f"workflow:packproduct:{employee_id}:{rule['product_id']}",
        )] for rule in rules]
        rows.append([InlineKeyboardButton(text="← Фасовки", callback_data="team:packrules")])
        await present(callback.message, f"<b>⚙️ Фасовки · {employee['alias'] if employee else 'Сотрудник'}</b>\n\nФормат на кнопках: ×1 / ×2 / ×5.", InlineKeyboardMarkup(inline_keyboard=rows))

    async def pack_product_screen(target: Message, player_id: int, employee_id: int, product_id: int) -> None:
        rule = next((row for row in game.packaging_rules(player_id, employee_id) if int(row["product_id"]) == product_id), None)
        if not rule:
            await present(target, "Правило недоступно.", nav(f"workflow:packemployee:{employee_id}"))
            return
        text = (
            f"<b>⚙️ {rule['product_title']}</b>\n\n"
            f"×1: <b>{rule['pct_1']}%</b>\n"
            f"×2: <b>{rule['pct_2']}%</b>\n"
            f"×5: <b>{rule['pct_5']}%</b>\n\n"
            "Сумма всегда равна 100%. Правило применяется при подготовке новых позиций."
        )
        rows = []
        for pack, value in ((1, rule["pct_1"]), (2, rule["pct_2"]), (5, rule["pct_5"])):
            rows.append([
                InlineKeyboardButton(text="−10", callback_data=f"workflow:packadj:{employee_id}:{product_id}:{pack}:-10"),
                InlineKeyboardButton(text=f"×{pack} · {value}%", callback_data="workflow:noop"),
                InlineKeyboardButton(text="+10", callback_data=f"workflow:packadj:{employee_id}:{product_id}:{pack}:10"),
            ])
        rows.append([InlineKeyboardButton(text="← Товары", callback_data=f"workflow:packemployee:{employee_id}")])
        await present(target, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("workflow:packproduct:"))
    async def pack_product(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, employee_id, product_id = callback.data.split(":")
        await pack_product_screen(callback.message, callback.from_user.id, int(employee_id), int(product_id))

    @router.callback_query(F.data.startswith("workflow:packadj:"))
    async def pack_adjust(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, employee_id, product_id, pack, delta = callback.data.split(":")
        game.adjust_packaging_rule(callback.from_user.id, int(employee_id), int(product_id), int(pack), int(delta))
        await pack_product_screen(callback.message, callback.from_user.id, int(employee_id), int(product_id))

    @router.callback_query(F.data == "workflow:noop")
    async def noop(callback: CallbackQuery) -> None:
        await callback.answer()

    return router
