from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


def _clean_status(value: str | None) -> str:
    status = (value or "").strip()
    if status.lower() == "свободен":
        return ""
    prefix = "свободен · "
    if status.lower().startswith(prefix):
        return status[len(prefix):].strip()
    return status


def recipient_button_text(employee: dict) -> str:
    """Build a retail-recipient label with the idle marker next to the courier name."""
    unsecured_now = max(0, int(employee["exposure"]) - int(employee["deposit"]))
    status = _clean_status(employee.get("status_text"))
    idle_ready = bool(employee.get("idle_ready"))

    prefix = "🟢 " if idle_ready else ""
    label = f"{prefix}{employee['alias']} · депозит {int(employee['deposit']):,} ₽"

    if status and not idle_ready:
        label += f" · {status}"
    if unsecured_now:
        label += f" · 🔴 {unsecured_now:,} ₽"

    return label


def build_courier_idle_router(game) -> Router:
    """Render retail-recipient selection with the same idle marker as the Team screen."""
    router = Router(name="courier-idle-recipient-selection")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    @router.callback_query(F.data.regexp(r"^workflow:batch:\d+$"))
    async def batch(callback: CallbackQuery) -> None:
        await callback.answer()
        batch_id = int((callback.data or "").split(":")[2])
        batch_row, staff = game.retail_staff_for_batch(callback.from_user.id, batch_id)
        if not batch_row:
            await present(
                callback.message,
                "Партия не найдена.",
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="← Команда", callback_data="menu:team")]
                ]),
            )
            return

        with game.db.connect() as conn:
            product = conn.execute(
                "SELECT title FROM products WHERE id=?",
                (batch_row["product_id"],),
            ).fetchone()

        text = (
            f"<b>📦 Партия #{batch_id} · {product['title']}</b>\n\n"
            f"Статус: {'принимается' if batch_row['status']=='receiving' else 'готова к распределению'}\n"
            f"Осталось у оптового сотрудника: <b>{batch_row['remaining']} ед.</b>\n"
            f"Себестоимость остатка: {int(batch_row['remaining'] * batch_row['unit_cost']):,} ₽"
        )

        rows = []
        if batch_row["status"] == "warehouse":
            text += (
                "\n\n<b>Передать рознице</b>\n"
                "🟢 — курьер полностью простаивает и прямо сейчас готов принять новую партию."
            )
            for employee in staff:
                rows.append([
                    InlineKeyboardButton(
                        text=recipient_button_text(employee),
                        callback_data=f"workflow:alloc:{batch_id}:{employee['id']}:10",
                    )
                ])

        rows.append([
            InlineKeyboardButton(
                text="← Партии",
                callback_data=f"workflow:batches:{batch_row['responsible_employee_id']}",
            )
        ])
        await present(callback.message, text, InlineKeyboardMarkup(inline_keyboard=rows))

    return router
