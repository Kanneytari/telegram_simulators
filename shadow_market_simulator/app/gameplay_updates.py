from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import ui_staff_handlers, workflow
from .ui_common import clean, money, nav_row, notice, present, tutorial_hint


async def _render_batch(
    target: Message,
    game,
    player_id: int,
    batch_id: int,
    *,
    flash: str | None = None,
) -> None:
    batch, staff = game.retail_staff_for_batch(player_id, batch_id)
    if not batch:
        await ui_staff_handlers.render_batches(
            target,
            game,
            player_id,
            flash="Партия недоступна.",
        )
        return

    with game.db.connect() as conn:
        product = conn.execute(
            "SELECT title FROM products WHERE id=?",
            (batch["product_id"],),
        ).fetchone()
        responsible = (
            conn.execute(
                "SELECT alias FROM employees WHERE id=? AND active=1",
                (batch["responsible_employee_id"],),
            ).fetchone()
            if batch["responsible_employee_id"]
            else None
        )
        warehouse_count = int(
            conn.execute(
                """SELECT COUNT(*) FROM employees
                   WHERE player_id=? AND active=1 AND role='warehouse'""",
                (player_id,),
            ).fetchone()[0]
        )

    warehouse_line = (
        f"Складмен: 🚚 {clean(responsible['alias'])}"
        if responsible
        else "Складмен: не назначен"
    )
    if responsible and batch["status"] == "receiving":
        warehouse_line += " · получает"

    text = (
        f"<b>{clean(product['title'])} · партия #{batch_id}</b>\n\n"
        f"Осталось: {int(batch['remaining'])} ед. · "
        f"{money(int(batch['remaining'] * batch['unit_cost']))}\n"
        f"{warehouse_line}"
    )
    rows: list[list[InlineKeyboardButton]] = []
    tutorial = game.needs_first_handoff_tutorial(player_id)

    if not responsible:
        text += "\n\n🔴 Сначала назначь складмена."
        if tutorial:
            text += "\n\n" + tutorial_hint("Назначь складмена на эту партию.")
        if warehouse_count:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="Назначить складмена",
                        callback_data=f"team:reassign:{batch_id}",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="Нанять сотрудника",
                        callback_data="team:recruit",
                    )
                ]
            )
    elif batch["status"] == "warehouse":
        text += "\n\nВыберите кладмена"
        if tutorial:
            text += "\n\n" + tutorial_hint(
                "Выбери закладчика, которому передашь стафф."
            )
        employees = {int(row["id"]): row for row in game.employees(player_id)}
        for employee in staff:
            live = employees.get(int(employee["id"]), {})
            status = str(live.get("status_text") or "свободен")
            if status == "свободен":
                status = "готов принять"
            unsecured = max(
                0,
                int(employee.get("exposure", 0)) - int(employee["deposit"]),
            )
            risk = (
                f" · 🔴 уже не покрыто {money(unsecured)}" if unsecured else ""
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"👤 {employee['alias']} · {status}{risk}",
                        callback_data=(
                            f"team:alloc:{batch_id}:{employee['id']}:"
                            f"{int(employee.get('recommended_quantity', 0))}"
                        ),
                    )
                ]
            )
        if warehouse_count > 1:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="Сменить складмена",
                        callback_data=f"team:reassign:{batch_id}",
                    )
                ]
            )

    if tutorial and responsible and batch["status"] == "receiving":
        text += "\n\n" + tutorial_hint(
            "Складмен ещё получает партию. Вернись сюда, когда она будет готова."
        )
    rows.append(nav_row("team:batches", "← Склад"))
    await present(
        target,
        notice(flash, text),
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


def apply_gameplay_updates() -> None:
    """Install the remaining legacy presentation overlay."""
    workflow.TASK_LABELS["handoff"] = "готовит мастер-клад"
    ui_staff_handlers.render_batch = _render_batch
