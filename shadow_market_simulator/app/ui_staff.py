from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .courier_management import (
    BONUS_COST,
    DEPOSIT_PCTS,
    DEPOSIT_TARGETS,
    PHONE,
    REST_OPTIONS,
    TRANSPORT,
)
from .courier_model import condition_band, pace_band, relationship_band
from .employee_rename import rename_employee
from .recruitment import CHANNELS, DURATION_OPTIONS, VOLUME_OPTIONS
from .ui_common import clean, money, nav_row, notice, pct, present, rating


class RenameEmployeeState(StatesGroup):
    waiting_for_name = State()


def _employee_dicts(game, player_id: int) -> list[dict]:
    return [dict(row) for row in game.employees(player_id)]


def _employee_status(game, player_id: int, employee_id: int) -> str:
    row = next((item for item in _employee_dicts(game, player_id) if int(item["id"]) == employee_id), None)
    return str(row.get("status_text", "свободен")) if row else "свободен"


def _team_keyboard(game, player_id: int, employees) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for employee in employees:
        role_icon = "🚚" if employee["role"] == "warehouse" else "👤"
        status = str(employee.get("status_text") or "свободен")
        exposure = int(employee.get("exposure", 0))
        deposit = int(employee["deposit"])
        if employee["role"] == "courier":
            _, condition = condition_band(float(employee["stress"]))
            detail = condition if float(employee["stress"]) >= 45 else (status if status != "свободен" else "свободен")
        else:
            detail = status
        risk = f" · 🔴 {money(exposure - deposit)}" if exposure > deposit else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{role_icon} {employee['alias']} · {detail}{risk}",
                callback_data=f"team:employee:{employee['id']}",
            )
        ])

    with game.db.connect() as conn:
        batch_count = int(conn.execute(
            """SELECT COUNT(*) FROM batches
               WHERE player_id=? AND status IN ('receiving','warehouse') AND remaining>0""",
            (player_id,),
        ).fetchone()[0])
    if batch_count:
        rows.append([InlineKeyboardButton(text=f"Партии · {batch_count}", callback_data="team:batches")])
    rows.append([
        InlineKeyboardButton(text="Нанять", callback_data="team:recruit"),
        InlineKeyboardButton(text="Оплата", callback_data="team:terms"),
    ])
    rows.append([InlineKeyboardButton(text="Меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_team(target: Message, game, simulation, player_id: int, *, flash: str | None = None) -> None:
    simulation.advance(player_id)
    employees = _employee_dicts(game, player_id)
    stressed = sum(row["role"] == "courier" and float(row["stress"]) >= 62 for row in employees)
    risky = sum(int(row.get("exposure", 0)) > int(row["deposit"]) for row in employees)
    body = f"<b>👥 Команда · {len(employees)}</b>"
    warnings: list[str] = []
    if stressed:
        warnings.append(f"🟡 Перегружены: {stressed}")
    if risky:
        warnings.append(f"🔴 Товар сверх депозита: {risky}")
    if warnings:
        body += "\n\n" + "\n".join(warnings)
    await present(target, notice(flash, body), _team_keyboard(game, player_id, employees))


def _courier_profile_text(game, player_id: int, employee_id: int) -> str | None:
    with game.db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1 AND role='courier'",
            (employee_id, player_id),
        ).fetchone()
        profile = conn.execute(
            "SELECT * FROM courier_profiles WHERE employee_id=?",
            (employee_id,),
        ).fetchone()
    if not employee or not profile:
        return None

    snapshot = game.courier_management_snapshot(player_id, employee_id)
    if not snapshot:
        return None
    exposure = game._employee_exposure(player_id, employee_id)
    unsecured = max(0, exposure - int(employee["deposit"]))
    service = game.employee_service_metrics(player_id, employee_id)
    pace_n = int(profile["pace_observation_count"] or 0)
    if pace_n >= 2:
        observed = float(profile["pace_observation_sum"] or 0) / pace_n
        pace_text = pace_band(observed)
    else:
        pace_text = "мало данных"
    reliability = game._reliability_label(employee, profile)
    observations = game._observations(employee, profile)[:3]
    status = _employee_status(game, player_id, employee_id)

    text = (
        f"<b>👤 {clean(employee['alias'])} · розничный сотрудник</b>\n\n"
        f"{snapshot['condition_icon']} {snapshot['condition']} · отношения {snapshot['relationship']}\n"
        f"Сейчас: {clean(status)}\n\n"
        f"Темп: <b>{pace_text}</b>\n"
        f"Качество: <b>{rating(service['rating'], service['count'])}</b> · {service['count']} заказов\n"
        f"Надёжность: <b>{reliability}</b>\n\n"
        f"Ответственность: {money(exposure)} · депозит {money(employee['deposit'])}\n"
        f"Оснащение: {snapshot['transport']} · {snapshot['phone']}"
    )
    if unsecured:
        text += f"\n🔴 Без покрытия: {money(unsecured)}"
    if observations:
        text += "\n\n<b>Что известно</b>\n" + "\n".join(f"• {clean(line)}" for line in observations)
    return text


def _warehouse_profile_text(game, player_id: int, employee_id: int) -> str | None:
    with game.db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1 AND role='warehouse'",
            (employee_id, player_id),
        ).fetchone()
    if not employee:
        return None
    exposure = game._employee_exposure(player_id, employee_id)
    unsecured = max(0, exposure - int(employee["deposit"]))
    batches = game.active_batches(player_id, employee_id)
    units = sum(int(row["remaining"]) for row in batches)
    status = _employee_status(game, player_id, employee_id)
    _, condition = condition_band(float(employee["stress"]))
    text = (
        f"<b>🚚 {clean(employee['alias'])} · оптовый сотрудник</b>\n\n"
        f"Сейчас: <b>{clean(status)}</b> · {condition}\n"
        f"Отношения: {relationship_band(float(employee['loyalty']))}\n\n"
        f"Ответственность: {money(exposure)} · депозит {money(employee['deposit'])}\n"
        f"Партии: {len(batches)} · {units} ед.\n"
        f"Успешных операций: {int(employee['jobs_done'])}"
    )
    if unsecured:
        text += f"\n🔴 Без покрытия: {money(unsecured)}"
    return text


def _profile_keyboard(employee_id: int, role: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if role == "courier":
        rows.extend([
            [
                InlineKeyboardButton(text=f"Премия · {money(BONUS_COST)}", callback_data=f"team:bonus:{employee_id}"),
                InlineKeyboardButton(text="Отдых", callback_data=f"team:rest:{employee_id}"),
            ],
            [
                InlineKeyboardButton(text="Развитие", callback_data=f"team:development:{employee_id}"),
                InlineKeyboardButton(text="Ещё", callback_data=f"team:more:{employee_id}"),
            ],
        ])
    else:
        rows.extend([
            [InlineKeyboardButton(text="Партии", callback_data=f"team:batches:{employee_id}")],
            [InlineKeyboardButton(text="Ещё", callback_data=f"team:more:{employee_id}")],
        ])
    rows.append(nav_row("menu:team", "← Команда"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_profile(target: Message, game, player_id: int, employee_id: int, *, flash: str | None = None) -> None:
    with game.db.connect() as conn:
        employee = conn.execute(
            "SELECT role FROM employees WHERE id=? AND player_id=? AND active=1",
            (employee_id, player_id),
        ).fetchone()
    if not employee:
        await render_team(target, game, game.simulation, player_id, flash="Сотрудник недоступен.")
        return
    role = str(employee["role"])
    text = _courier_profile_text(game, player_id, employee_id) if role == "courier" else _warehouse_profile_text(game, player_id, employee_id)
    if not text:
        await render_team(target, game, game.simulation, player_id, flash="Сотрудник недоступен.")
        return
    await present(target, notice(flash, text), _profile_keyboard(employee_id, role))


def rest_keyboard(employee_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"12 ч · {money(REST_OPTIONS[12]['cost'])}", callback_data=f"team:restdo:{employee_id}:12"),
            InlineKeyboardButton(text=f"24 ч · {money(REST_OPTIONS[24]['cost'])}", callback_data=f"team:restdo:{employee_id}:24"),
        ],
        nav_row(f"team:employee:{employee_id}", "← Профиль", menu=False),
    ])


async def render_rest(target: Message, game, player_id: int, employee_id: int) -> None:
    snapshot = game.courier_management_snapshot(player_id, employee_id)
    if not snapshot:
        await render_profile(target, game, player_id, employee_id)
        return
    text = f"<b>Отдых · {clean(snapshot['alias'])}</b>\n\nСейчас: {snapshot['condition_icon']} {snapshot['condition']}"
    await present(target, text, rest_keyboard(employee_id))


def development_keyboard(game, player_id: int, employee_id: int) -> InlineKeyboardMarkup:
    snapshot = game.courier_management_snapshot(player_id, employee_id)
    rows: list[list[InlineKeyboardButton]] = [[InlineKeyboardButton(text="Изменить депозит", callback_data=f"team:deposit:{employee_id}")]]
    if snapshot:
        t_level = int(snapshot["transport_level"])
        p_level = int(snapshot["phone_level"])
        if t_level < 2:
            title, cost, _ = TRANSPORT[t_level + 1]
            rows.append([InlineKeyboardButton(text=f"{title.capitalize()} · {money(cost)}", callback_data=f"team:upgradeconfirm:{employee_id}:transport")])
        if p_level < 2:
            title, cost, _ = PHONE[p_level + 1]
            rows.append([InlineKeyboardButton(text=f"Телефон: {title} · {money(cost)}", callback_data=f"team:upgradeconfirm:{employee_id}:phone")])
    rows.append(nav_row(f"team:employee:{employee_id}", "← Профиль"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_development(target: Message, game, player_id: int, employee_id: int, *, flash: str | None = None) -> None:
    s = game.courier_management_snapshot(player_id, employee_id)
    if not s:
        await render_profile(target, game, player_id, employee_id)
        return
    deposit_text = (
        f"{money(s['deposit'])} / {money(s['deposit_target'])}\nВ депозит идёт {s['deposit_pct']}% заработка"
        if s["plan_active"]
        else f"{money(s['deposit'])} · цель достигнута\nДальше действует ставка команды {s['standard_pct']}%"
    )
    text = (
        f"<b>Развитие · {clean(s['alias'])}</b>\n\n"
        f"Вложено: <b>{money(s['invested_total'])}</b>\n\n"
        f"<b>Депозит</b>\n{deposit_text}\n\n"
        f"<b>Оснащение</b>\nТранспорт: {s['transport']}\nТелефон: {s['phone']}"
    )
    await present(target, notice(flash, text), development_keyboard(game, player_id, employee_id))


def deposit_keyboard(employee_id: int, snapshot) -> InlineKeyboardMarkup:
    pct_row = [InlineKeyboardButton(
        text=("✓ " if int(snapshot["deposit_pct"]) == value else "") + f"{value}%",
        callback_data=f"team:depositpct:{employee_id}:{value}",
    ) for value in DEPOSIT_PCTS]
    target_rows = [[InlineKeyboardButton(
        text=("✓ " if int(snapshot["deposit_target"]) == value else "") + money(value),
        callback_data=f"team:deposittarget:{employee_id}:{value}",
    )] for value in DEPOSIT_TARGETS]
    return InlineKeyboardMarkup(inline_keyboard=[pct_row, *target_rows, nav_row(f"team:development:{employee_id}", "← Развитие", menu=False)])


async def render_deposit(target: Message, game, player_id: int, employee_id: int, *, flash: str | None = None) -> None:
    s = game.courier_management_snapshot(player_id, employee_id)
    if not s:
        await render_profile(target, game, player_id, employee_id)
        return
    text = (
        f"<b>Депозит · {clean(s['alias'])}</b>\n\n"
        f"Сейчас: {money(s['deposit'])} / {money(s['deposit_target'])}\n"
        f"Из заработка: <b>{s['deposit_pct']}%</b>\n\n"
        "Большая доля быстрее увеличивает покрытие, но сотрудник получает меньше денег на руки."
    )
    await present(target, notice(flash, text), deposit_keyboard(employee_id, s))


def more_keyboard(employee_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Переименовать", callback_data=f"team:rename:{employee_id}")],
        [InlineKeyboardButton(text="Сменить роль", callback_data=f"team:role:{employee_id}")],
        [InlineKeyboardButton(text="Уволить", callback_data=f"team:fire:{employee_id}")],
        nav_row(f"team:employee:{employee_id}", "← Профиль"),
    ])


async def render_more(target: Message, game, player_id: int, employee_id: int) -> None:
    with game.db.connect() as conn:
        employee = conn.execute("SELECT alias FROM employees WHERE id=? AND player_id=? AND active=1", (employee_id, player_id)).fetchone()
    if not employee:
        await render_team(target, game, game.simulation, player_id, flash="Сотрудник недоступен.")
        return
    await present(target, f"<b>{clean(employee['alias'])} · ещё</b>", more_keyboard(employee_id))


def batches_keyboard(rows) -> InlineKeyboardMarkup:
    buttons = []
    for batch in rows:
        state = "принимается" if batch["status"] == "receiving" else "готова"
        buttons.append([InlineKeyboardButton(
            text=f"{batch['product_title']} · {batch['remaining']} ед. · {batch['employee_alias']} · {state}",
            callback_data=f"team:batch:{batch['id']}",
        )])
    buttons.append(nav_row("menu:team", "← Команда"))
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def render_batches(target: Message, game, player_id: int, employee_id: int | None = None, *, flash: str | None = None) -> None:
    with game.db.connect() as conn:
        params: tuple = (player_id,) if employee_id is None else (player_id, employee_id)
        extra = "" if employee_id is None else " AND b.responsible_employee_id=?"
        rows = conn.execute(
            f"""SELECT b.*, p.title product_title, COALESCE(e.alias,'без ответственного') employee_alias
                FROM batches b JOIN products p ON p.id=b.product_id
                LEFT JOIN employees e ON e.id=b.responsible_employee_id
                WHERE b.player_id=? AND b.status IN ('receiving','warehouse') AND b.remaining>0 {extra}
                ORDER BY CASE b.status WHEN 'warehouse' THEN 0 ELSE 1 END, b.id DESC""",
            params,
        ).fetchall()
    body = f"<b>📦 Партии · {len(rows)}</b>"
    if not rows:
        body += "\n\nАктивных партий нет."
    await present(target, notice(flash, body), batches_keyboard(rows))


def _recipient_label(employee: dict) -> str:
    status = str(employee.get("status_text") or "свободен")
    if status == "свободен":
        status = "готов принять"
    unsecured = max(0, int(employee.get("exposure", 0)) - int(employee["deposit"]))
    risk = f" · 🔴 уже {money(unsecured)}" if unsecured else ""
    return f"{employee['alias']} · {status}{risk}"


async def render_batch(target: Message, game, player_id: int, batch_id: int, *, flash: str | None = None) -> None:
    batch, staff = game.retail_staff_for_batch(player_id, batch_id)
    if not batch:
        await render_batches(target, game, player_id, flash="Партия недоступна.")
        return
    with game.db.connect() as conn:
        product = conn.execute("SELECT title FROM products WHERE id=?", (batch["product_id"],)).fetchone()
        responsible = conn.execute("SELECT alias FROM employees WHERE id=?", (batch["responsible_employee_id"],)).fetchone() if batch["responsible_employee_id"] else None
        warehouse_count = int(conn.execute(
            "SELECT COUNT(*) FROM employees WHERE player_id=? AND active=1 AND role='warehouse'",
            (player_id,),
        ).fetchone()[0])
    enriched = {int(row["id"]): row for row in _employee_dicts(game, player_id)}
    rows: list[list[InlineKeyboardButton]] = []
    if batch["status"] == "warehouse":
        for employee in staff:
            data = dict(employee)
            data.update({k: v for k, v in enriched.get(int(employee["id"]), {}).items() if k in {"status_text", "stress"}})
            rows.append([InlineKeyboardButton(
                text=_recipient_label(data),
                callback_data=f"team:alloc:{batch_id}:{employee['id']}:{min(10, int(batch['remaining']))}",
            )])
        if warehouse_count > 1:
            rows.append([InlineKeyboardButton(text="Сменить ответственного", callback_data=f"team:reassign:{batch_id}")])
    rows.append(nav_row("team:batches", "← Партии"))
    state = "принимается" if batch["status"] == "receiving" else "готова к передаче"
    text = (
        f"<b>{clean(product['title'])} · партия #{batch_id}</b>\n\n"
        f"{int(batch['remaining'])} ед. · {money(int(batch['remaining'] * batch['unit_cost']))}\n"
        f"Ответственный: {clean(responsible['alias']) if responsible else 'не назначен'} · {state}"
    )
    if batch["status"] == "warehouse":
        text += "\n\nКому передать?"
    await present(target, notice(flash, text), InlineKeyboardMarkup(inline_keyboard=rows))


async def render_allocation(target: Message, game, player_id: int, batch_id: int, employee_id: int, quantity: int) -> None:
    batch, staff = game.retail_staff_for_batch(player_id, batch_id)
    employee = next((row for row in staff if int(row["id"]) == employee_id), None)
    if not batch or not employee or batch["status"] != "warehouse":
        await render_batch(target, game, player_id, batch_id, flash="Партия или сотрудник уже недоступны.")
        return
    quantity = max(1, min(int(quantity), int(batch["remaining"])))
    value = quantity * int(batch["unit_cost"])
    after = int(employee["exposure"]) + value
    unsecured = max(0, after - int(employee["deposit"]))
    presets = sorted({min(int(batch["remaining"]), value) for value in (10, 20, 30) if value <= int(batch["remaining"])})
    rows: list[list[InlineKeyboardButton]] = []
    if presets:
        rows.append([InlineKeyboardButton(
            text=("✓ " if value == quantity else "") + str(value),
            callback_data=f"team:alloc:{batch_id}:{employee_id}:{value}",
        ) for value in presets])
    rows.append([
        InlineKeyboardButton(text="−5", callback_data=f"team:alloc:{batch_id}:{employee_id}:{max(1, quantity-5)}"),
        InlineKeyboardButton(text="+5", callback_data=f"team:alloc:{batch_id}:{employee_id}:{min(int(batch['remaining']), quantity+5)}"),
    ])
    if quantity != int(batch["remaining"]):
        rows.append([InlineKeyboardButton(text=f"Всё · {batch['remaining']} ед.", callback_data=f"team:alloc:{batch_id}:{employee_id}:{batch['remaining']}")])
    rows.append([InlineKeyboardButton(text=f"Передать {quantity} ед.", callback_data=f"team:allocdo:{batch_id}:{employee_id}:{quantity}")])
    rows.append(nav_row(f"team:batch:{batch_id}", "← Партия"))
    text = (
        f"<b>Передать {clean(employee['alias'])}</b>\n\n"
        f"Количество: <b>{quantity} ед.</b> · {money(value)}\n"
        f"После передачи: ответственность {money(after)} · депозит {money(employee['deposit'])}"
    )
    text += f"\n🔴 Без покрытия: {money(unsecured)}" if unsecured else "\nТовар полностью покрыт."
    await present(target, text, InlineKeyboardMarkup(inline_keyboard=rows))


async def render_reassign(target: Message, game, player_id: int, batch_id: int) -> None:
    with game.db.connect() as conn:
        batch = conn.execute(
            "SELECT * FROM batches WHERE id=? AND player_id=? AND status='warehouse' AND remaining>0",
            (batch_id, player_id),
        ).fetchone()
        if not batch:
            await render_batches(target, game, player_id, flash="Партия недоступна.")
            return
        staff = conn.execute(
            """SELECT * FROM employees WHERE player_id=? AND active=1 AND role='warehouse' AND id<>? ORDER BY deposit DESC""",
            (player_id, batch["responsible_employee_id"] or -1),
        ).fetchall()
    value = int(batch["remaining"] * batch["unit_cost"])
    rows = []
    for employee in staff:
        after = game._employee_exposure(player_id, int(employee["id"])) + value
        unsecured = max(0, after - int(employee["deposit"]))
        suffix = f" · 🔴 {money(unsecured)}" if unsecured else " · покрыто"
        rows.append([InlineKeyboardButton(text=f"{employee['alias']}{suffix}", callback_data=f"team:reassigndo:{batch_id}:{employee['id']}")])
    rows.append(nav_row(f"team:batch:{batch_id}", "← Партия"))
    await present(target, f"<b>Сменить ответственного</b>\n\nПартия #{batch_id} · {money(value)}", InlineKeyboardMarkup(inline_keyboard=rows))


def terms_root_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Розница", callback_data="team:terms:courier"),
            InlineKeyboardButton(text="Опт", callback_data="team:terms:warehouse"),
        ],
        nav_row("menu:team", "← Команда"),
    ])


def _policy_line(role: str, policy) -> str:
    if role == "courier":
        return f"{money(policy['fixed_fee'])} за заказ + {pct(policy['base_rate_bps']/100, 1)} с продажи · депозит {policy['deposit_contribution_pct']}%"
    return f"{pct(policy['base_rate_bps']/100, 1)} с передачи + доплата за риск · депозит {policy['deposit_contribution_pct']}%"


async def render_terms_root(target: Message, game, player_id: int, *, flash: str | None = None) -> None:
    retail = game.compensation_policy(player_id, "courier")
    wholesale = game.compensation_policy(player_id, "warehouse")
    text = (
        "<b>Оплата команды</b>\n\n"
        f"Розница\n{_policy_line('courier', retail)}\n\n"
        f"Опт\n{_policy_line('warehouse', wholesale)}"
    )
    await present(target, notice(flash, text), terms_root_keyboard())


def terms_editor_keyboard(role: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if role == "courier":
        rows.extend([
            [InlineKeyboardButton(text="Фикс −50", callback_data="team:termsdraft:fixed_fee:-50"), InlineKeyboardButton(text="Фикс +50", callback_data="team:termsdraft:fixed_fee:50")],
            [InlineKeyboardButton(text="Продажа −0,5%", callback_data="team:termsdraft:base_rate_bps:-50"), InlineKeyboardButton(text="Продажа +0,5%", callback_data="team:termsdraft:base_rate_bps:50")],
        ])
    else:
        rows.extend([
            [InlineKeyboardButton(text="Передача −0,5%", callback_data="team:termsdraft:base_rate_bps:-50"), InlineKeyboardButton(text="Передача +0,5%", callback_data="team:termsdraft:base_rate_bps:50")],
            [InlineKeyboardButton(text="Риск −0,5%", callback_data="team:termsdraft:risk_rate_bps:-50"), InlineKeyboardButton(text="Риск +0,5%", callback_data="team:termsdraft:risk_rate_bps:50")],
        ])
    rows.append([InlineKeyboardButton(text="Депозит −5%", callback_data="team:termsdraft:deposit_contribution_pct:-5"), InlineKeyboardButton(text="Депозит +5%", callback_data="team:termsdraft:deposit_contribution_pct:5")])
    rows.append([InlineKeyboardButton(text="Применить", callback_data="team:termsapply")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="team:terms")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_terms_editor(target: Message, game, player_id: int, state: FSMContext, role: str, *, reset: bool = False) -> None:
    data = await state.get_data()
    draft = data.get("terms_draft") if not reset and data.get("terms_role") == role else None
    original = data.get("terms_original") if draft else None
    if draft is None:
        policy = game.compensation_policy(player_id, role)
        draft = dict(policy)
        original = dict(policy)
        await state.update_data(terms_role=role, terms_draft=draft, terms_original=original)
    title = "розница" if role == "courier" else "опт"
    text = (
        f"<b>Оплата · {title}</b>\n\n"
        f"Сейчас\n{_policy_line(role, original)}\n\n"
        f"Новые условия\n<b>{_policy_line(role, draft)}</b>\n\n"
        "Изменение повлияет на отношение всей группы."
    )
    await present(target, text, terms_editor_keyboard(role))


def recruitment_root_keyboard(candidate_count: int) -> InlineKeyboardMarkup:
    rows = []
    if candidate_count:
        rows.append([InlineKeyboardButton(text=f"Кандидаты · {candidate_count}", callback_data="team:candidates")])
    rows.append([InlineKeyboardButton(text="Новый поиск", callback_data="team:recruit:new")])
    rows.append(nav_row("menu:team", "← Команда"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_recruitment_root(target: Message, recruitment, player_id: int, *, flash: str | None = None) -> None:
    candidates = recruitment.candidates(player_id)
    status = recruitment.campaign_status_text(player_id)
    body = f"<b>🔎 Найм</b>\n\n{status}"
    await present(target, notice(flash, body), recruitment_root_keyboard(len(candidates)))


def channels_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{channel.icon} {channel.title}", callback_data=f"recruit:channel:{code}")] for code, channel in CHANNELS.items()]
    rows.append(nav_row("team:recruit", "← Найм"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_channels(target: Message) -> None:
    await present(target, "<b>Новый поиск</b>\n\nГде искать сотрудников?", channels_keyboard())


def recruitment_draft_keyboard(draft, quote) -> InlineKeyboardMarkup:
    role = str(draft["role"])
    deposit_step = 50_000 if role == "warehouse" else 10_000
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=("✓ " if role == "courier" else "") + "Розница", callback_data="recruit:set:role:courier"),
            InlineKeyboardButton(text=("✓ " if role == "warehouse" else "") + "Опт", callback_data="recruit:set:role:warehouse"),
        ],
        [
            InlineKeyboardButton(text=f"Депозит −{money(deposit_step)}", callback_data=f"recruit:adj:min_deposit:-{deposit_step}"),
            InlineKeyboardButton(text=f"Депозит +{money(deposit_step)}", callback_data=f"recruit:adj:min_deposit:{deposit_step}"),
        ],
        [
            InlineKeyboardButton(text=("✓ " if draft["experience_required"] else "") + "Опыт", callback_data="recruit:toggle:experience_required"),
            InlineKeyboardButton(text=("✓ " if draft["car_required"] else "") + "Авто", callback_data="recruit:toggle:car_required"),
        ],
        [InlineKeyboardButton(text=("✓ " if value == int(draft["traffic_multiplier"]) else "") + f"×{value}", callback_data=f"recruit:set:traffic_multiplier:{value}") for value in VOLUME_OPTIONS],
        [InlineKeyboardButton(text=("✓ " if value == int(draft["duration_hours"]) else "") + f"{value} ч", callback_data=f"recruit:set:duration_hours:{value}") for value in DURATION_OPTIONS],
        [InlineKeyboardButton(text=f"Запустить · {money(quote['cost'])}", callback_data="recruit:run")],
        nav_row("team:recruit:new", "← Каналы"),
    ])


async def render_recruitment_draft(target: Message, recruitment, player_id: int) -> None:
    draft = recruitment.ensure_draft(player_id)
    channel = recruitment.get_channel(draft["channel"])
    quote = recruitment.quote(player_id, draft)
    role = "розница" if draft["role"] == "courier" else "опт"
    text = (
        f"<b>{channel.icon} {clean(channel.title)} · {role}</b>\n\n"
        f"Ожидаемо {quote['expected_min']}–{quote['expected_max']} откликов · <b>{money(quote['cost'])}</b>\n"
        f"Депозит от {money(draft['min_deposit'])} · опыт {'нужен' if draft['experience_required'] else 'не обязателен'} · "
        f"авто {'нужно' if draft['car_required'] else 'не требуется'}\n"
        f"Охват ×{draft['traffic_multiplier']} · срок {draft['duration_hours']} ч"
    )
    await present(target, text, recruitment_draft_keyboard(draft, quote))


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


async def render_candidate(target: Message, game, player_id: int, candidate_id: int) -> None:
    with game.db.connect() as conn:
        row = conn.execute(
            """SELECT c.*, rc.terms_fixed_fee, rc.terms_base_rate_bps, rc.terms_risk_rate_bps, rc.terms_deposit_pct
               FROM candidates c LEFT JOIN recruitment_campaigns rc ON rc.id=c.campaign_id
               WHERE c.id=? AND c.player_id=? AND c.status='open'""",
            (candidate_id, player_id),
        ).fetchone()
        equipment = conn.execute("SELECT phone_level FROM courier_candidate_equipment WHERE candidate_id=?", (candidate_id,)).fetchone()
    if not row:
        return
    role = "розница" if row["role"] == "courier" else "опт"
    lines = [f"<b>{'👤' if row['role']=='courier' else '🚚'} {clean(row['alias'])} · {role}</b>", "", f"Депозит: {money(row['deposit'])}", f"Автомобиль: {'есть' if row['has_car'] else 'нет'}"]
    if row["role"] == "courier":
        phone = PHONE[int(equipment["phone_level"] if equipment else 0)][0]
        lines.append(f"Телефон: {phone}")
        terms = f"{money(row['terms_fixed_fee'])} + {pct(row['terms_base_rate_bps']/100, 1)} с продажи · депозит {int(row['terms_deposit_pct'])}%"
    else:
        terms = f"{pct(row['terms_base_rate_bps']/100, 1)} с передачи · депозит {int(row['terms_deposit_pct'])}%"
    lines.extend(["", "Условия", terms])
    summary = str(row["summary"] or "").strip()
    if summary:
        lines.extend(["", "По анкете", summary])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Нанять", callback_data=f"team:hire:{candidate_id}"),
            InlineKeyboardButton(text="Отказать", callback_data=f"team:reject:{candidate_id}"),
        ],
        nav_row("team:candidates", "← Кандидаты"),
    ])
    await present(target, "\n".join(lines), keyboard)


def build_staff_router(game, simulation, recruitment) -> Router:
    router = Router(name="compact-staff")

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
        s = game.courier_management_snapshot(callback.from_user.id, employee_id)
        if not s:
            return
        table = TRANSPORT if slot == "transport" else PHONE
        current = int(s["transport_level"] if slot == "transport" else s["phone_level"])
        title, cost, _ = table[min(2, current + 1)]
        text = (
            f"<b>Подтвердить улучшение?</b>\n\n"
            f"{clean(s['alias'])} · {title}\n"
            f"Стоимость: <b>{money(cost)}</b>\n\n"
            "Вложение закреплено за сотрудником и не возвращается при его уходе."
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Купить · {money(cost)}", callback_data=f"team:upgradedo:{employee_id}:{slot}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"team:development:{employee_id}")],
        ])
        await present(callback.message, text, keyboard)

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
            employee = conn.execute("SELECT alias FROM employees WHERE id=? AND player_id=? AND active=1", (employee_id, callback.from_user.id)).fetchone()
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
        await message.answer(result["text"], reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Профиль", callback_data=f"team:employee:{employee_id}")]]))

    @router.callback_query(F.data.startswith("team:role:") & ~F.data.startswith("team:roleconfirm:"))
    async def role_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int(callback.data.split(":")[2])
        with game.db.connect() as conn:
            employee = conn.execute("SELECT * FROM employees WHERE id=? AND player_id=? AND active=1", (employee_id, callback.from_user.id)).fetchone()
        if not employee:
            return
        current = "опт" if employee["role"] == "warehouse" else "розница"
        new = "розница" if employee["role"] == "warehouse" else "опт"
        text = f"<b>Сменить роль · {clean(employee['alias'])}</b>\n\nСейчас: {current}\nНовая роль: <b>{new}</b>\n\nСмена возможна только без товара и активных задач."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"Сменить на {new}", callback_data=f"team:roleconfirm:{employee_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"team:more:{employee_id}")],
        ])
        await present(callback.message, text, keyboard)

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
            employee = conn.execute("SELECT * FROM employees WHERE id=? AND player_id=? AND active=1", (employee_id, callback.from_user.id)).fetchone()
        if not employee:
            return
        payout = int(employee["deposit"]) + int(employee["wages_accrued"])
        text = (
            f"<b>Уволить {clean(employee['alias'])}?</b>\n\n"
            f"Вернуть сотруднику: <b>{money(payout)}</b>\n\n"
            "Увольнение возможно только после завершения задач и освобождения от товара."
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Уволить", callback_data=f"team:fireconfirm:{employee_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"team:more:{employee_id}")],
        ])
        await present(callback.message, text, keyboard)

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
        await render_allocation(callback.message, game, callback.from_user.id, int(batch_raw), int(employee_raw), int(quantity_raw))

    @router.callback_query(F.data.startswith("team:allocdo:"))
    async def allocation_do(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, batch_raw, employee_raw, quantity_raw = callback.data.split(":")
        result = game.allocate_to_retail(callback.from_user.id, int(batch_raw), int(employee_raw), int(quantity_raw))
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
            batch = conn.execute("SELECT * FROM batches WHERE id=? AND player_id=? AND status='warehouse' AND remaining>0", (batch_id, callback.from_user.id)).fetchone()
            employee = conn.execute("SELECT * FROM employees WHERE id=? AND player_id=? AND active=1 AND role='warehouse'", (employee_id, callback.from_user.id)).fetchone()
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
        role = callback.data.split(":")[2]
        await render_terms_editor(callback.message, game, callback.from_user.id, state, role, reset=True)

    @router.callback_query(F.data.startswith("team:termsdraft:"))
    async def terms_adjust(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        _, _, field, delta_raw = callback.data.split(":")
        data = await state.get_data()
        role = data.get("terms_role")
        draft = dict(data.get("terms_draft") or {})
        if not role or field not in draft:
            return
        draft[field] = int(draft[field]) + int(delta_raw)
        if field == "deposit_contribution_pct":
            draft[field] = max(0, min(100, int(draft[field])))
        elif field == "fixed_fee":
            draft[field] = max(0, int(draft[field]))
        else:
            draft[field] = max(0, int(draft[field]))
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
        recruitment.update_draft(callback.from_user.id, field, value if field == "role" else int(value))
        await render_recruitment_draft(callback.message, recruitment, callback.from_user.id)

    @router.callback_query(F.data.startswith("recruit:adj:"))
    async def recruit_adj(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, field, delta = callback.data.split(":")
        recruitment.adjust_draft(callback.from_user.id, field, int(delta))
        await render_recruitment_draft(callback.message, recruitment, callback.from_user.id)

    @router.callback_query(F.data.startswith("recruit:toggle:"))
    async def recruit_toggle(callback: CallbackQuery) -> None:
        await callback.answer()
        field = callback.data.split(":")[2]
        draft = recruitment.ensure_draft(callback.from_user.id)
        recruitment.update_draft(callback.from_user.id, field, 0 if draft[field] else 1)
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
