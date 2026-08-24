from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .courier_idle_handlers import recipient_button_text


def build_workflow_reassign_router(game) -> Router:
    router = Router(name="wholesale-reassignment")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    @router.callback_query(F.data.startswith("workflow:batch:"))
    async def batch_screen(callback: CallbackQuery) -> None:
        await callback.answer()
        batch_id = int(callback.data.split(":")[2])
        batch, retail_staff = game.retail_staff_for_batch(callback.from_user.id, batch_id)
        if not batch:
            await present(callback.message, "Партия не найдена.", InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="← Команда", callback_data="menu:team")
            ]]))
            return
        with game.db.connect() as conn:
            product = conn.execute("SELECT title FROM products WHERE id=?", (batch["product_id"],)).fetchone()
        text = (
            f"<b>📦 Партия #{batch_id} · {product['title']}</b>\n\n"
            f"Статус: {'принимается' if batch['status']=='receiving' else 'готова к распределению'}\n"
            f"Осталось у оптового сотрудника: <b>{batch['remaining']} ед.</b>\n"
            f"Себестоимость остатка: {int(batch['remaining']*batch['unit_cost']):,} ₽"
        )
        rows = []
        if batch["status"] == "warehouse":
            text += (
                "\n\n<b>Передать рознице</b>\n"
                "Выбери сотрудника и затем количество.\n"
                "🟢 — курьер полностью простаивает и прямо сейчас готов принять новую партию."
            )
            for employee in retail_staff:
                rows.append([InlineKeyboardButton(
                    text=recipient_button_text(employee),
                    callback_data=f"workflow:alloc:{batch_id}:{employee['id']}:10",
                )])
            rows.append([InlineKeyboardButton(text="🔁 Сменить оптового ответственного", callback_data=f"workflow:reassign:{batch_id}")])
        rows.append([InlineKeyboardButton(text="← Партии", callback_data=f"workflow:batches:{batch['responsible_employee_id']}")])
        await present(callback.message, text, InlineKeyboardMarkup(inline_keyboard=rows))

    @router.callback_query(F.data.startswith("workflow:reassign:") & ~F.data.startswith("workflow:reassignconfirm:"))
    async def reassign(callback: CallbackQuery) -> None:
        await callback.answer()
        batch_id = int(callback.data.split(":")[2])
        with game.db.connect() as conn:
            batch = conn.execute(
                "SELECT * FROM batches WHERE id=? AND player_id=? AND status='warehouse' AND remaining>0",
                (batch_id, callback.from_user.id),
            ).fetchone()
            if not batch:
                await present(callback.message, "Партия недоступна.")
                return
            staff = conn.execute(
                """SELECT * FROM employees
                   WHERE player_id=? AND active=1 AND role='warehouse' AND id<>?
                   ORDER BY deposit DESC""",
                (callback.from_user.id, batch["responsible_employee_id"] or -1),
            ).fetchall()
        value = int(batch["remaining"] * batch["unit_cost"])
        rows = []
        for employee in staff:
            exposure = game._employee_exposure(callback.from_user.id, int(employee["id"]))
            after = exposure + value
            unsecured = max(0, after - int(employee["deposit"]))
            label = f"🔴 {employee['alias']} · сверх депозита {unsecured:,} ₽" if unsecured else f"✅ {employee['alias']} · покрыто"
            rows.append([InlineKeyboardButton(
                text=label,
                callback_data=f"workflow:reassignconfirm:{batch_id}:{employee['id']}",
            )])
        rows.append([InlineKeyboardButton(text="← Партия", callback_data=f"workflow:batch:{batch_id}")])
        await present(
            callback.message,
            f"<b>Сменить ответственного · партия #{batch_id}</b>\n\n"
            f"Стоимость остатка: <b>{value:,} ₽</b>\n\n"
            "Можно назначить сотрудника даже при недостаточном покрытии. В этом случае риск потери возрастёт.",
            InlineKeyboardMarkup(inline_keyboard=rows),
        )

    @router.callback_query(F.data.startswith("workflow:reassignconfirm:"))
    async def reassign_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, batch_id, employee_id = callback.data.split(":")
        with game.db.connect() as conn:
            batch = conn.execute(
                "SELECT * FROM batches WHERE id=? AND player_id=? AND status='warehouse' AND remaining>0",
                (int(batch_id), callback.from_user.id),
            ).fetchone()
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1 AND role='warehouse'",
                (int(employee_id), callback.from_user.id),
            ).fetchone()
            if not batch or not employee:
                result = "Партия или сотрудник уже недоступны."
            else:
                conn.execute("UPDATE batches SET responsible_employee_id=? WHERE id=?", (employee["id"], batch["id"]))
                exposure = game._employee_exposure(callback.from_user.id, int(employee["id"]))
                unsecured = max(0, exposure - int(employee["deposit"]))
                result = f"Партия #{batch_id} теперь закреплена за {employee['alias']}."
                if unsecured:
                    result += f"\n\n🔴 Не покрыто депозитом: {unsecured:,} ₽."
        await present(callback.message, f"<b>📦 Ответственность</b>\n\n{result}", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Партия", callback_data=f"workflow:batch:{batch_id}")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ]))

    return router
