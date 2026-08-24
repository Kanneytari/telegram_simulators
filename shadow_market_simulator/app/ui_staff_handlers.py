from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .courier_management import PHONE, TRANSPORT
from .employee_rename import rename_employee
from .recruitment import CHANNELS
from .ui_common import clean, money, nav_row, notice, pct, present
from .ui_staff import (
    RenameEmployeeState,
    render_allocation,
    render_batches,
    render_channels,
    render_deposit,
    render_development,
    render_more,
    render_profile,
    render_reassign,
    render_recruitment_draft,
    render_recruitment_root,
    render_rest,
    render_team,
    render_terms_editor,
    render_terms_root,
)


async def render_batch(target: Message, game, player_id: int, batch_id: int, *, flash: str | None = None) -> None:
    batch, staff = game.retail_staff_for_batch(player_id, batch_id)
    if not batch:
        await render_batches(target, game, player_id, flash="Партия недоступна.")
        return
    with game.db.connect() as conn:
        product = conn.execute("SELECT title FROM products WHERE id=?", (batch["product_id"],)).fetchone()
        responsible = conn.execute("SELECT alias FROM employees WHERE id=? AND active=1", (batch["responsible_employee_id"],)).fetchone() if batch["responsible_employee_id"] else None
        warehouse_count = int(conn.execute("SELECT COUNT(*) FROM employees WHERE player_id=? AND active=1 AND role='warehouse'", (player_id,)).fetchone()[0])
    state = "получает" if batch["status"] == "receiving" else "готова к передаче"
    text = (
        f"<b>{clean(product['title'])} · партия #{batch_id}</b>\n\n"
        f"Осталось: {int(batch['remaining'])} ед. · {money(int(batch['remaining'] * batch['unit_cost']))}\n"
        f"Складмен: {clean(responsible['alias']) if responsible else 'не назначен'} · {state}"
    )
    rows: list[list[InlineKeyboardButton]] = []
    if not responsible:
        text += "\n\n🔴 Сначала назначь складмена."
        if warehouse_count:
            rows.append([InlineKeyboardButton(text="Назначить складмена", callback_data=f"team:reassign:{batch_id}")])
        else:
            rows.append([InlineKeyboardButton(text="Нанять сотрудника", callback_data="team:recruit")])
    elif batch["status"] == "warehouse":
        text += "\n\nКому передать?"
        employees = {int(row["id"]): row for row in game.employees(player_id)}
        for employee in staff:
            live = employees.get(int(employee["id"]), {})
            status = str(live.get("status_text") or "свободен")
            if status == "свободен": status = "готов принять"
            unsecured = max(0, int(employee.get("exposure", 0)) - int(employee["deposit"]))
            risk = f" · 🔴 уже не покрыто {money(unsecured)}" if unsecured else ""
            rows.append([InlineKeyboardButton(text=f"{employee['alias']} · {status}{risk}", callback_data=f"team:alloc:{batch_id}:{employee['id']}:{min(10, int(batch['remaining']))}")])
        if warehouse_count > 1:
            rows.append([InlineKeyboardButton(text="Сменить складмена", callback_data=f"team:reassign:{batch_id}")])
    rows.append(nav_row("team:batches", "← Склад"))
    await present(target, notice(flash, text), InlineKeyboardMarkup(inline_keyboard=rows))

async def render_candidate(target: Message, game, player_id: int, candidate_id: int) -> None:
    with game.db.connect() as conn:
        row = conn.execute(
            """SELECT c.*, rc.terms_fixed_fee, rc.terms_base_rate_bps, rc.terms_risk_rate_bps, rc.terms_deposit_pct
               FROM candidates c LEFT JOIN recruitment_campaigns rc ON rc.id=c.campaign_id
               WHERE c.id=? AND c.player_id=? AND c.status='open'""",
            (candidate_id, player_id),
        ).fetchone()
        profile = conn.execute("SELECT transport_level, phone_level FROM courier_candidate_profiles WHERE candidate_id=?", (candidate_id,)).fetchone()
    if not row:
        await present(target, "Кандидат уже недоступен.", InlineKeyboardMarkup(inline_keyboard=[nav_row("team:candidates", "← Кандидаты")]))
        return
    role = str(row["role"]); role_text = "закладчик" if role == "courier" else "складмен"
    experience = {0: "нет", 1: "есть", 2: "сильный"}.get(int(row["experience_level"] or 0), "нет данных")
    lines = [f"<b>{'👤' if role == 'courier' else '🚚'} {clean(row['alias'])} · {role_text}</b>", "", f"Депозит: {money(row['deposit'])}", f"Опыт: {experience}"]
    policy = game.compensation_policy(player_id, role)
    if role == "courier":
        transport_level = int(profile["transport_level"] if profile else (2 if row["has_car"] else 0))
        lines.extend([f"Передвижение: {TRANSPORT[transport_level][0]}", f"Телефон: {PHONE[int(profile['phone_level'] if profile else 0)][0]}"])
        fixed = int(row["terms_fixed_fee"] if row["terms_fixed_fee"] is not None else policy["fixed_fee"])
        rate = int(row["terms_base_rate_bps"] if row["terms_base_rate_bps"] is not None else policy["base_rate_bps"])
        deposit_pct = int(row["terms_deposit_pct"] if row["terms_deposit_pct"] is not None else policy["deposit_contribution_pct"])
        terms = f"{money(fixed)} за заказ + {pct(rate / 100, 1)} с продажи\n{deposit_pct}% заработка идёт в депозит"
    else:
        rate = int(row["terms_base_rate_bps"] if row["terms_base_rate_bps"] is not None else policy["base_rate_bps"])
        deposit_pct = int(row["terms_deposit_pct"] if row["terms_deposit_pct"] is not None else policy["deposit_contribution_pct"])
        terms = f"{pct(rate / 100, 1)} с передачи\n{deposit_pct}% заработка идёт в депозит"
    lines.extend(["", "<b>Условия</b>", terms])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Нанять", callback_data=f"team:hire:{candidate_id}"), InlineKeyboardButton(text="Отказать", callback_data=f"team:reject:{candidate_id}")],
        nav_row("team:candidates", "← Кандидаты"),
    ])
    await present(target, "\n".join(lines), keyboard)

def candidates_keyboard(candidates) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=("🚚 " if row["role"] == "warehouse" else "👤 ") + f"{row['alias']} · депозит {money(row['deposit'])}",
        callback_data=f"team:candidate:{row['id']}",
    )] for row in candidates]
    rows.append([InlineKeyboardButton(text="Новый поиск", callback_data="team:recruit:new")])
    rows.append(nav_row("team:recruit", "← Найм"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_candidates(target: Message, recruitment, player_id: int, *, flash: str | None = None) -> None:
    candidates = recruitment.candidates(player_id)
    body = f"<b>Кандидаты · {len(candidates)}</b>"
    if not candidates:
        body += "\n\nСвежих откликов нет."
    await present(target, notice(flash, body), candidates_keyboard(candidates))


def build_staff_router(game, simulation, recruitment) -> Router:
    router = Router(name="canonical-staff-handlers")

    @router.callback_query(F.data == "menu:team")
    async def team(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_team(callback.message, game, simulation, callback.from_user.id)

    @router.callback_query(F.data.startswith("team:employee:"))
    async def employee(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        await render_profile(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("team:bonus:"))
    async def bonus(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        result = game.give_bonus(callback.from_user.id, employee_id)
        await render_profile(callback.message, game, callback.from_user.id, employee_id, flash=result["message"])

    @router.callback_query(F.data.startswith("team:rest:") & ~F.data.startswith("team:restdo:"))
    async def rest(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_rest(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("team:restdo:"))
    async def rest_do(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, employee_raw, hours_raw = callback.data.split(":")
        result = game.send_to_rest(callback.from_user.id, int(employee_raw), int(hours_raw))
        await render_profile(callback.message, game, callback.from_user.id, int(employee_raw), flash=result["message"])

    @router.callback_query(F.data.startswith("team:development:"))
    async def development(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_development(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("team:deposit:") & ~F.data.startswith("team:depositpct:") & ~F.data.startswith("team:deposittarget:"))
    async def deposit(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_deposit(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("team:depositpct:"))
    async def deposit_pct(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, employee_raw, value_raw = callback.data.split(":")
        result = game.set_deposit_plan(callback.from_user.id, int(employee_raw), int(value_raw))
        await render_deposit(callback.message, game, callback.from_user.id, int(employee_raw), flash=result["message"])

    @router.callback_query(F.data.startswith("team:deposittarget:"))
    async def deposit_target(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, employee_raw, value_raw = callback.data.split(":")
        result = game.set_deposit_target(callback.from_user.id, int(employee_raw), int(value_raw))
        await render_deposit(callback.message, game, callback.from_user.id, int(employee_raw), flash=result["message"])

    @router.callback_query(F.data.startswith("team:upgradeconfirm:"))
    async def upgrade_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, employee_raw, slot = callback.data.split(":")
        employee_id = int(employee_raw)
        snapshot = game.courier_management_snapshot(callback.from_user.id, employee_id)
        if not snapshot:
            return
        table = TRANSPORT if slot == "transport" else PHONE
        current = int(snapshot["transport_level"] if slot == "transport" else snapshot["phone_level"])
        title, cost, _ = table[min(2, current + 1)]
        text = (
            f"<b>Подтвердить улучшение?</b>\n\n"
            f"{clean(snapshot['alias'])} · {title}\n"
            f"Стоимость: <b>{money(cost)}</b>\n\n"
            "Вложение закреплено за сотрудником и не возвращается при его уходе."
        )
        await present(callback.message, text, InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Купить · {money(cost)}", callback_data=f"team:upgradedo:{employee_id}:{slot}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"team:development:{employee_id}")],
        ]))

    @router.callback_query(F.data.startswith("team:upgradedo:"))
    async def upgrade_do(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, employee_raw, slot = callback.data.split(":")
        employee_id = int(employee_raw)
        result = game.upgrade_equipment(callback.from_user.id, employee_id, slot)
        await render_development(callback.message, game, callback.from_user.id, employee_id, flash=result["message"])

    @router.callback_query(F.data.startswith("team:more:"))
    async def more(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_more(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("team:rename:"))
    async def rename_start(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        with game.db.connect() as conn:
            employee = conn.execute(
                "SELECT alias FROM employees WHERE id=? AND player_id=? AND active=1",
                (employee_id, callback.from_user.id),
            ).fetchone()
        if not employee:
            return
        await state.set_state(RenameEmployeeState.waiting_for_name)
        await state.update_data(employee_id=employee_id)
        await present(
            callback.message,
            f"<b>Переименовать {clean(employee['alias'])}</b>\n\nОтправь новое имя. Максимум 24 символа.",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data=f"team:more:{employee_id}")]]),
        )

    @router.message(RenameEmployeeState.waiting_for_name)
    async def rename_finish(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        employee_id = int(data.get("employee_id", 0))
        result = rename_employee(game, message.from_user.id, employee_id, message.text or "")
        if result["status"] in {"invalid", "duplicate"}:
            await message.answer(f"{result['text']}\n\nОтправь другое имя.")
            return
        await state.clear()
        await message.answer(result["text"], reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Профиль", callback_data=f"team:employee:{employee_id}")
        ]]))

    @router.callback_query(F.data.startswith("team:role:") & ~F.data.startswith("team:roleconfirm:"))
    async def role_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        with game.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1",
                (employee_id, callback.from_user.id),
            ).fetchone()
        if not employee:
            return
        current = "складмен" if employee["role"] == "warehouse" else "закладчик"
        new = "закладчик" if employee["role"] == "warehouse" else "складмен"
        await present(
            callback.message,
            f"<b>Сменить роль · {clean(employee['alias'])}</b>\n\nСейчас: {current}\nНовая роль: <b>{new}</b>\n\nСмена возможна только без товара и активных задач.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"Сменить на {new}", callback_data=f"team:roleconfirm:{employee_id}")],
                [InlineKeyboardButton(text="Отмена", callback_data=f"team:more:{employee_id}")],
            ]),
        )

    @router.callback_query(F.data.startswith("team:roleconfirm:"))
    async def role_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        result = game.change_employee_role(callback.from_user.id, employee_id)
        await render_profile(callback.message, game, callback.from_user.id, employee_id, flash=result)

    @router.callback_query(F.data.startswith("team:fire:") & ~F.data.startswith("team:fireconfirm:"))
    async def fire_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        with game.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1",
                (employee_id, callback.from_user.id),
            ).fetchone()
        if not employee:
            return
        payout = int(employee["deposit"]) + int(employee["wages_accrued"])
        await present(
            callback.message,
            f"<b>Уволить {clean(employee['alias'])}?</b>\n\nВернуть сотруднику: <b>{money(payout)}</b>\n\nУвольнение возможно только после завершения задач и освобождения от товара.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Уволить", callback_data=f"team:fireconfirm:{employee_id}")],
                [InlineKeyboardButton(text="Отмена", callback_data=f"team:more:{employee_id}")],
            ]),
        )

    @router.callback_query(F.data.startswith("team:fireconfirm:"))
    async def fire_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        result = game.fire_employee(callback.from_user.id, employee_id)
        if result["status"] == "inventory":
            await render_profile(callback.message, game, callback.from_user.id, employee_id, flash=result["message"])
        else:
            await render_team(callback.message, game, simulation, callback.from_user.id, flash=result["message"])

    @router.callback_query(F.data == "team:batches")
    async def batches(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_batches(callback.message, game, callback.from_user.id)

    @router.callback_query(F.data.regexp(r"^team:batches:\d+$"))
    async def employee_batches(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_batches(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("team:batch:"))
    async def batch(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_batch(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("team:alloc:") & ~F.data.startswith("team:allocdo:"))
    async def allocation(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, batch_raw, employee_raw, quantity_raw = callback.data.split(":")
        await render_allocation(
            callback.message,
            game,
            callback.from_user.id,
            int(batch_raw),
            int(employee_raw),
            int(quantity_raw),
        )

    @router.callback_query(F.data.startswith("team:allocdo:"))
    async def allocation_do(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, batch_raw, employee_raw, quantity_raw = callback.data.split(":")
        result = game.allocate_to_retail(
            callback.from_user.id,
            int(batch_raw),
            int(employee_raw),
            int(quantity_raw),
        )
        await render_batch(callback.message, game, callback.from_user.id, int(batch_raw), flash=result)

    @router.callback_query(F.data.startswith("team:reassign:") & ~F.data.startswith("team:reassigndo:"))
    async def reassign(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_reassign(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("team:reassigndo:"))
    async def reassign_do(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, batch_raw, employee_raw = callback.data.split(":")
        batch_id = int(batch_raw)
        employee_id = int(employee_raw)
        with game.db.connect() as conn:
            batch = conn.execute(
                "SELECT * FROM batches WHERE id=? AND player_id=? AND status='warehouse' AND remaining>0",
                (batch_id, callback.from_user.id),
            ).fetchone()
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1 AND role='warehouse'",
                (employee_id, callback.from_user.id),
            ).fetchone()
            if not batch or not employee:
                result = "Партия или сотрудник уже недоступны."
            else:
                conn.execute("UPDATE batches SET responsible_employee_id=? WHERE id=?", (employee_id, batch_id))
                result = f"Ответственный: {employee['alias']}."
        await render_batch(callback.message, game, callback.from_user.id, batch_id, flash=result)

    @router.callback_query(F.data == "team:terms")
    async def terms(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.update_data(terms_role=None, terms_draft=None, terms_original=None)
        await render_terms_root(callback.message, game, callback.from_user.id)

    @router.callback_query(F.data.regexp(r"^team:terms:(courier|warehouse)$"))
    async def terms_role(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await render_terms_editor(callback.message, game, callback.from_user.id, state, callback.data.split(":")[2], reset=True)

    @router.callback_query(F.data.startswith("team:termsdraft:"))
    async def terms_adjust(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        _, _, field, delta_raw = callback.data.split(":")
        data = await state.get_data()
        role = data.get("terms_role")
        draft = dict(data.get("terms_draft") or {})
        if not role or field not in draft:
            return
        draft[field] = max(0, int(draft[field]) + int(delta_raw))
        if field == "deposit_contribution_pct":
            draft[field] = min(100, draft[field])
        await state.update_data(terms_draft=draft)
        await render_terms_editor(callback.message, game, callback.from_user.id, state, str(role))

    @router.callback_query(F.data == "team:termsapply")
    async def terms_apply(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        role = str(data.get("terms_role") or "")
        draft = dict(data.get("terms_draft") or {})
        original = dict(data.get("terms_original") or {})
        if role not in {"courier", "warehouse"} or not draft or not original:
            await render_terms_root(callback.message, game, callback.from_user.id)
            return
        reactions = []
        for field in ("fixed_fee", "base_rate_bps", "risk_rate_bps", "deposit_contribution_pct"):
            if field in draft and field in original:
                delta = int(draft[field]) - int(original[field])
                if delta:
                    result = game.adjust_compensation_policy(callback.from_user.id, role, field, delta)
                    if result.get("reaction"):
                        reactions.append(result["reaction"])
        await state.update_data(terms_role=None, terms_draft=None, terms_original=None)
        flash = "Условия применены ко всей группе."
        if reactions:
            flash += " " + reactions[-1]
        await render_terms_root(callback.message, game, callback.from_user.id, flash=flash)

    @router.callback_query(F.data == "team:recruit")
    async def recruit(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_recruitment_root(callback.message, recruitment, callback.from_user.id)

    @router.callback_query(F.data == "team:recruit:new")
    async def recruit_new(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_channels(callback.message)

    @router.callback_query(F.data.startswith("recruit:channel:"))
    async def recruit_channel(callback: CallbackQuery) -> None:
        await callback.answer()
        code = callback.data.split(":")[2]
        if code not in CHANNELS:
            return
        recruitment.ensure_draft(callback.from_user.id, code)
        await render_recruitment_draft(callback.message, recruitment, callback.from_user.id)

    @router.callback_query(F.data.startswith("recruit:set:"))
    async def recruit_set(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, field, value = callback.data.split(":")
        recruitment.update_draft(callback.from_user.id, field, int(value))
        await render_recruitment_draft(callback.message, recruitment, callback.from_user.id)

    @router.callback_query(F.data.startswith("recruit:adj:"))
    async def recruit_adj(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, field, delta = callback.data.split(":")
        recruitment.adjust_draft(callback.from_user.id, field, int(delta))
        await render_recruitment_draft(callback.message, recruitment, callback.from_user.id)

    @router.callback_query(F.data.startswith("recruit:cycle:"))
    async def recruit_cycle(callback: CallbackQuery) -> None:
        await callback.answer()
        field = callback.data.split(":")[2]
        draft = recruitment.ensure_draft(callback.from_user.id)
        if field == "role":
            recruitment.update_draft(callback.from_user.id, "role", "warehouse" if draft["role"] == "courier" else "courier")
        elif field == "experience":
            recruitment.update_draft(callback.from_user.id, "experience_required", 0 if int(draft["experience_required"]) else 1)
        elif field == "transport" and draft["role"] == "courier":
            recruitment.update_draft(callback.from_user.id, "transport_required", (int(draft["transport_required"]) + 1) % 3)
        elif field == "coverage":
            recruitment.update_draft(callback.from_user.id, "traffic_multiplier", {1: 2, 2: 4, 4: 1}.get(int(draft["traffic_multiplier"]), 1))
        await render_recruitment_draft(callback.message, recruitment, callback.from_user.id)

    @router.callback_query(F.data == "recruit:run")
    async def recruit_run(callback: CallbackQuery) -> None:
        await callback.answer()
        result = recruitment.start_campaign(callback.from_user.id)
        await render_recruitment_root(callback.message, recruitment, callback.from_user.id, flash=result)

    @router.callback_query(F.data == "team:candidates")
    async def candidates(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_candidates(callback.message, recruitment, callback.from_user.id)

    @router.callback_query(F.data.startswith("team:candidate:"))
    async def candidate(callback: CallbackQuery) -> None:
        await callback.answer()
        await render_candidate(callback.message, game, callback.from_user.id, int(callback.data.split(":")[2]))

    @router.callback_query(F.data.startswith("team:hire:"))
    async def hire(callback: CallbackQuery) -> None:
        await callback.answer()
        result = game.hire_candidate(callback.from_user.id, int(callback.data.split(":")[2]))
        await render_candidates(callback.message, recruitment, callback.from_user.id, flash=result)

    @router.callback_query(F.data.startswith("team:reject:"))
    async def reject(callback: CallbackQuery) -> None:
        await callback.answer()
        game.reject_candidate(callback.from_user.id, int(callback.data.split(":")[2]))
        await render_candidates(callback.message, recruitment, callback.from_user.id, flash="Кандидату отказано.")

    return router
