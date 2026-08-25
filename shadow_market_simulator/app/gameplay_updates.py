from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import ui_commerce, ui_staff_handlers, workflow
from .ui_common import clean, money, nav_row, notice, present, tutorial_hint


def _procurement_products_keyboard(db, player_id: int, products) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for product in products:
        status = ui_commerce._stock_status(db, player_id, int(product["id"]))
        text = str(product["title"])
        if status != "нет запаса":
            text += f" · 🚚 {status}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"proc:product:{product['id']}",
                )
            ]
        )

    with db.connect() as conn:
        batch_count = int(
            conn.execute(
                """SELECT COUNT(*) FROM batches
                   WHERE player_id=? AND status IN ('receiving','warehouse')
                     AND remaining>0""",
                (player_id,),
            ).fetchone()[0]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=f"📦 Склад · {batch_count}",
                callback_data="team:batches",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sales_root_keyboard(rows) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=(
                    f"{row['title']} · {int(row['stock'])} ед. · "
                    f"{ui_commerce.rating(float(row['quality_avg']), int(row['rating_count']))}"
                ),
                callback_data=f"sales:product:{row['id']}",
            )
        ]
        for row in rows
    ]
    buttons.append(
        [
            InlineKeyboardButton(
                text="⚙️ Фасовки",
                callback_data="sales:packaging",
            ),
            InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _render_packaging(target: Message, game, player_id: int) -> None:
    rule = game.global_packaging_rule(player_id)
    text = (
        "<b>⚙️ Фасовки</b>\n\n"
        "Новые партии распределяются так:\n\n"
        f"×1 · <b>{rule['pct_1']}%</b>\n"
        f"×2 · <b>{rule['pct_2']}%</b>\n"
        f"×5 · <b>{rule['pct_5']}%</b>"
    )
    if ui_commerce.claim_tip(game.db, player_id, "packaging"):
        text += (
            "\n\n💡 Эти доли применяются к товару, который закладчики "
            "будут готовить к витрине после следующих передач."
        )
    await present(target, text, ui_commerce.packaging_keyboard(rule))


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


def _install_handoff_update() -> None:
    workflow.TASK_LABELS["handoff"] = "готовит мастер-клад"
    original = workflow.WorkflowGameService.allocate_to_retail
    if not getattr(original, "_nightshift_updated", False):

        def allocate_to_retail(
            self,
            player_id: int,
            batch_id: int,
            retail_employee_id: int,
            quantity: int,
        ) -> str:
            result = original(
                self,
                player_id,
                batch_id,
                retail_employee_id,
                quantity,
            )
            if not result.startswith("Назначено "):
                return result

            with self.db.connect() as conn:
                allocation = conn.execute(
                    """SELECT a.quantity, a.unit_cost, p.title product_title,
                              w.alias wholesale_alias, r.alias retail_alias,
                              r.deposit retail_deposit
                       FROM retail_allocations a
                       JOIN products p ON p.id=a.product_id
                       JOIN employees w ON w.id=a.wholesale_employee_id
                       JOIN employees r ON r.id=a.retail_employee_id
                       WHERE a.player_id=? AND a.batch_id=?
                         AND a.retail_employee_id=?
                       ORDER BY a.id DESC LIMIT 1""",
                    (player_id, batch_id, retail_employee_id),
                ).fetchone()
            if not allocation:
                return result

            allocated = int(allocation["quantity"])
            retail_after = (
                self._employee_exposure(player_id, retail_employee_id)
                + allocated * int(allocation["unit_cost"])
            )
            unsecured = max(
                0,
                retail_after - int(allocation["retail_deposit"]),
            )
            warning = (
                "\n\n🔴 После получения у закладчика будет не покрыто "
                f"депозитом: {unsecured:,} ₽."
                if unsecured
                else ""
            )
            return (
                "<b>✅ Принято</b>\n\n"
                f"Назначено <b>{allocated} ед.</b> "
                f"{allocation['product_title']} сотруднику "
                f"👤 {allocation['retail_alias']}.\n\n"
                f"🚚 {allocation['wholesale_alias']} готовит мастер-клад. "
                f"После завершения 👤 {allocation['retail_alias']} "
                f"автоматически начнёт подготовку товара к витрине."
                f"{warning}"
            )

        allocate_to_retail._nightshift_updated = True
        workflow.WorkflowGameService.allocate_to_retail = allocate_to_retail

    ui_staff_handlers.render_batch = _render_batch


def _install_ui_update() -> None:
    ui_commerce._procurement_products_keyboard = _procurement_products_keyboard
    ui_commerce._sales_root_keyboard = _sales_root_keyboard
    ui_commerce.render_packaging = _render_packaging


def apply_gameplay_updates() -> None:
    """Install the two remaining legacy presentation/handoff overlays."""
    _install_handoff_update()
    _install_ui_update()
