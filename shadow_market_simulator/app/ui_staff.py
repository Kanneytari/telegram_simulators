from __future__ import annotations

from .tutorial import hooks as tutorial_hooks

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from .courier_management import (
    BONUS_COST,
    DEPOSIT_PCTS,
    DEPOSIT_TARGETS,
    PHONE,
    REST_OPTIONS,
    TRANSPORT,
)
from .courier_model import condition_band, pace_band, relationship_band
from .recruitment import CHANNELS, DURATION_OPTIONS
from .ui_common import claim_tip, clean, money, nav_row, notice, pct, present, rating, tutorial_hint


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
        risk = f" · 🔴 не покрыто {money(exposure - deposit)}" if exposure > deposit else ""
        rows.append([InlineKeyboardButton(
            text=f"{role_icon} {employee['alias']} · {status}{risk}",
            callback_data=f"team:employee:{employee['id']}",
        )])
    rows.append([
        InlineKeyboardButton(text="Нанять", callback_data="team:recruit"),
        InlineKeyboardButton(text="Оплата", callback_data="team:terms"),
    ])
    rows.append([InlineKeyboardButton(text="Меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@tutorial_hooks.handoff_team
async def render_team(target: Message, game, simulation, player_id: int, *, flash: str | None = None) -> None:
    simulation.advance(player_id)
    employees = _employee_dicts(game, player_id)
    stressed = sum(row["role"] == "courier" and float(row["stress"]) >= 62 for row in employees)
    risky = sum(int(row.get("exposure", 0)) > int(row["deposit"]) for row in employees)
    body = f"<b>👥 Команда · {len(employees)}</b>"
    warnings: list[str] = []
    if stressed:
        warnings.append(f"🟡 Перегружено закладчиков: {stressed}")
    if risky:
        warnings.append(f"🔴 Непокрытый товар у сотрудников: {risky}")
    if warnings:
        body += "\n\n" + "\n".join(warnings)
    await present(target, notice(flash, body), _team_keyboard(game, player_id, employees))

def _courier_profile_text(game, player_id: int, employee_id: int) -> str | None:
    with game.db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1 AND role='courier'",
            (employee_id, player_id),
        ).fetchone()
        profile = conn.execute("SELECT * FROM courier_profiles WHERE employee_id=?", (employee_id,)).fetchone()
    if not employee or not profile:
        return None
    snapshot = game.courier_management_snapshot(player_id, employee_id)
    if not snapshot:
        return None
    exposure = game._employee_exposure(player_id, employee_id)
    unsecured = max(0, exposure - int(employee["deposit"]))
    service = game.employee_service_metrics(player_id, employee_id)
    pace_n = int(profile["pace_observation_count"] or 0)
    pace_text = pace_band(float(profile["pace_observation_sum"] or 0) / pace_n) if pace_n >= 2 else "мало данных"
    reliability = game._reliability_label(employee, profile)
    observations = game._observations(employee, profile)[:3]
    status = _employee_status(game, player_id, employee_id)
    coverage = f"🔴 Не покрыто депозитом: {money(unsecured)}" if unsecured else "🟢 Полностью покрыто депозитом"
    text = (
        f"<b>👤 {clean(employee['alias'])} · закладчик</b>\n\n"
        f"<b>Состояние</b>\n"
        f"{snapshot['condition_icon']} {snapshot['condition'].capitalize()}\n"
        f"Отношения: {snapshot['relationship']}\n"
        f"Сейчас: {clean(status)}\n\n"
        f"<b>Работа</b>\n"
        f"Темп: <b>{pace_text}</b>\n"
        f"Оценка: <b>{rating(service['rating'], service['count'])}</b> · {service['count']} заказов\n"
        f"Надёжность: <b>{reliability}</b>\n\n"
        f"<b>Товар</b>\n"
        f"На руках: {money(exposure)}\n"
        f"Депозит: {money(employee['deposit'])}\n"
        f"{coverage}\n\n"
        f"<b>Оснащение</b>\n"
        f"Передвижение: {snapshot['transport']}\n"
        f"Телефон: {snapshot['phone']}"
    )
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
    coverage = f"🔴 Не покрыто депозитом: {money(unsecured)}" if unsecured else "🟢 Полностью покрыто депозитом"
    return (
        f"<b>🚚 {clean(employee['alias'])} · складмен</b>\n\n"
        f"<b>Состояние</b>\n"
        f"Сейчас: {clean(status)}\n"
        f"Самочувствие: {condition}\n"
        f"Отношения: {relationship_band(float(employee['loyalty']))}\n\n"
        f"<b>Товар</b>\n"
        f"На руках: {money(exposure)}\n"
        f"Депозит: {money(employee['deposit'])}\n"
        f"{coverage}\n"
        f"Партии: {len(batches)} · {units} ед.\n\n"
        f"<b>Работа</b>\n"
        f"Успешных передач: {int(employee['jobs_done'])}"
    )

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
            [InlineKeyboardButton(text="Товар", callback_data=f"team:batches:{employee_id}")],
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
        f"{money(s['deposit'])} / {money(s['deposit_target'])}\n{s['deposit_pct']}% заработка направляется в депозит"
        if s["plan_active"]
        else f"{money(s['deposit'])} · цель достигнута\nДальше действует ставка команды {s['standard_pct']}%"
    )
    t_level = int(s["transport_level"]); p_level = int(s["phone_level"])
    transport_text = f"Сейчас: {s['transport']}"
    if t_level < 2:
        title, cost, _ = TRANSPORT[t_level + 1]
        benefit = "Велосипед ускоряет работу закладчика." if t_level == 0 else "Автомобиль ещё сильнее ускоряет работу закладчика."
        transport_text += f"\nСледующее: {title} · {money(cost)}\n{benefit}"
    phone_text = f"Сейчас: {s['phone']}"
    if p_level < 2:
        title, cost, _ = PHONE[p_level + 1]
        phone_text += f"\nСледующий: {title} · {money(cost)}\nЛучший телефон снижает вероятность ошибок."
    text = (
        f"<b>Развитие · {clean(s['alias'])}</b>\n\n"
        f"<b>Депозит</b>\n{deposit_text}\n\n"
        f"<b>Передвижение</b>\n{transport_text}\n\n"
        f"<b>Телефон</b>\n{phone_text}"
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


def batches_keyboard(rows, back_callback: str = "menu:product", back_text: str = "← Товар") -> InlineKeyboardMarkup:
    buttons = []
    for batch in rows:
        state = "получает" if batch["status"] == "receiving" else "готово"
        buttons.append([InlineKeyboardButton(
            text=f"{batch['product_title']} · {batch['remaining']} ед. · {batch['employee_alias']} · {state}",
            callback_data=f"team:batch:{batch['id']}",
        )])
    buttons.append(nav_row(back_callback, back_text))
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def render_batches(target: Message, game, player_id: int, employee_id: int | None = None, *, flash: str | None = None) -> None:
    with game.db.connect() as conn:
        params: tuple = (player_id,) if employee_id is None else (player_id, employee_id)
        extra = "" if employee_id is None else " AND b.responsible_employee_id=?"
        rows = conn.execute(
            f"""SELECT b.*, p.title product_title, COALESCE(e.alias,'без складмена') employee_alias
                FROM batches b JOIN products p ON p.id=b.product_id
                LEFT JOIN employees e ON e.id=b.responsible_employee_id
                WHERE b.player_id=? AND b.status IN ('receiving','warehouse') AND b.remaining>0 {extra}
                ORDER BY CASE b.status WHEN 'warehouse' THEN 0 ELSE 1 END, b.id DESC""",
            params,
        ).fetchall()
    body = f"<b>🚚 Склад · {len(rows)}</b>"
    if not rows:
        body += "\n\nНа складе нет активных партий."
    elif employee_id is None and game.needs_first_handoff_tutorial(player_id):
        body += "\n\n" + tutorial_hint("Выбери партию стаффа, которую хочешь передать закладчику.")
    keyboard = batches_keyboard(rows) if employee_id is None else batches_keyboard(rows, f"team:employee:{employee_id}", "← Профиль")
    await present(target, notice(flash, body), keyboard)

async def render_allocation(target: Message, game, player_id: int, batch_id: int, employee_id: int, quantity: int) -> None:
    batch, staff = game.retail_staff_for_batch(player_id, batch_id)
    employee = next((row for row in staff if int(row["id"]) == employee_id), None)
    if not batch or not employee or batch["status"] != "warehouse":
        await render_batches(target, game, player_id, flash="Партия или сотрудник уже недоступны.")
        return
    quantity = max(0, min(int(quantity), int(batch["remaining"])))
    value = quantity * int(batch["unit_cost"])
    after = int(employee["exposure"]) + value
    unsecured = max(0, after - int(employee["deposit"]))
    rows: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton(text="−5", callback_data=f"team:alloc:{batch_id}:{employee_id}:{max(0, quantity-5)}"),
        InlineKeyboardButton(text=f"📦 {quantity} ед.", callback_data=f"team:alloc:{batch_id}:{employee_id}:{quantity}"),
        InlineKeyboardButton(text="+5", callback_data=f"team:alloc:{batch_id}:{employee_id}:{min(int(batch['remaining']), quantity+5)}"),
    ]]
    if quantity > 0:
        rows.append([InlineKeyboardButton(text=f"✅ Отправить {quantity} ед.", callback_data=f"team:allocdo:{batch_id}:{employee_id}:{quantity}")])
    rows.append(nav_row(f"team:batch:{batch_id}", "← Назад"))
    text = (
        f"<b>Передать {clean(employee['alias'])}</b>\n\n"
        f"Количество: <b>{quantity} ед.</b> · {money(value)}\n"
        f"После передачи: товар на руках {money(after)} · депозит {money(employee['deposit'])}"
    )
    if quantity <= 0:
        text += "\n\nСвободного залога недостаточно даже для 5 ед. Можно выбрать количество вручную, если готов оставить часть товара непокрытой."
    else:
        text += f"\n🔴 Не покрыто депозитом: {money(unsecured)}" if unsecured else "\n🟢 Полностью покрыто депозитом."
    if game.needs_first_handoff_tutorial(player_id):
        if quantity > 0:
            text += "\n\n" + tutorial_hint(f"Проверь количество и нажми кнопку «✅ Отправить {quantity} ед.».")
        else:
            text += "\n\n" + tutorial_hint("Выбери количество от 5 ед. или вернись и выбери другого закладчика.")
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
    await present(target, f"<b>Сменить складмена</b>\n\nПартия #{batch_id} · {money(value)}", InlineKeyboardMarkup(inline_keyboard=rows))


def terms_root_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Закладчики", callback_data="team:terms:courier"),
            InlineKeyboardButton(text="Складмены", callback_data="team:terms:warehouse"),
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
        f"Закладчики\n{_policy_line('courier', retail)}\n\n"
        f"Складмены\n{_policy_line('warehouse', wholesale)}"
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
        draft = dict(policy); original = dict(policy)
        await state.update_data(terms_role=role, terms_draft=draft, terms_original=original)
    title = "закладчики" if role == "courier" else "складмены"
    text = (
        f"<b>Оплата · {title}</b>\n\n"
        f"Сейчас\n{_policy_line(role, original)}\n\n"
        f"Новые условия\n<b>{_policy_line(role, draft)}</b>\n\n"
        "Изменение повлияет на отношение всей группы."
    )
    if role == "warehouse":
        text += "\n\nДоплата за риск начисляется только на стоимость товара сверх депозита складмена."
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
    text = (
        "<b>Новый поиск</b>\n\nГде искать сотрудников?\n\n"
        "🟨 Стикеры\nДешевле · больше случайных откликов\n\n"
        "🧱 Граффити\nСредняя цена · среднее качество кандидатов\n\n"
        "🕸 Форумы\nДороже · кандидаты в среднем сильнее"
    )
    await present(target, text, channels_keyboard())

def recruitment_draft_keyboard(draft, quote) -> InlineKeyboardMarkup:
    role = str(draft["role"])
    deposit_step = 50_000 if role == "warehouse" else 10_000
    role_label = "Закладчик" if role == "courier" else "Складмен"
    coverage_labels = {1: "×1 - Обычный", 2: "×2 - Расширенный", 4: "×4 - Максимальный"}
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"Роль: {role_label}", callback_data="recruit:cycle:role")],
        [
            InlineKeyboardButton(text=f"Депозит −{money(deposit_step)}", callback_data=f"recruit:adj:min_deposit:-{deposit_step}"),
            InlineKeyboardButton(text=f"Депозит +{money(deposit_step)}", callback_data=f"recruit:adj:min_deposit:{deposit_step}"),
        ],
        [InlineKeyboardButton(text="Опыт: Обязателен" if draft["experience_required"] else "Опыт: Не важен", callback_data="recruit:cycle:experience")],
    ]
    if role == "courier":
        transport_labels = {0: "Пеший курьер", 1: "Велокурьер", 2: "Автокурьер"}
        rows.append([InlineKeyboardButton(text=f"Транспорт: {transport_labels[int(draft['transport_required'])]}", callback_data="recruit:cycle:transport")])
    rows.extend([
        [InlineKeyboardButton(text=f"Охват: {coverage_labels[int(draft['traffic_multiplier'])]}", callback_data="recruit:cycle:coverage")],
        [InlineKeyboardButton(text=("✓ " if value == int(draft["duration_hours"]) else "") + f"{value} ч", callback_data=f"recruit:set:duration_hours:{value}") for value in DURATION_OPTIONS],
        [InlineKeyboardButton(text=f"Запустить · {money(quote['cost'])}", callback_data="recruit:run")],
        nav_row("team:recruit:new", "← Каналы"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def render_recruitment_draft(target: Message, recruitment, player_id: int) -> None:
    draft = recruitment.ensure_draft(player_id)
    channel = recruitment.get_channel(draft["channel"])
    quote = recruitment.quote(player_id, draft)
    role = "закладчик" if draft["role"] == "courier" else "складмен"
    coverage = {1: "обычный", 2: "расширенный", 4: "максимальный"}[int(draft["traffic_multiplier"])]
    requirements = [f"Депозит от {money(draft['min_deposit'])}", "опыт обязателен" if draft["experience_required"] else "опыт не важен"]
    if draft["role"] == "courier":
        requirements.append({0: "пеший курьер", 1: "велокурьер", 2: "автокурьер"}[int(draft["transport_required"])])
    text = (
        f"<b>{channel.icon} {clean(channel.title)} · {role}</b>\n\n"
        f"Ожидаемо {quote['expected_min']}–{quote['expected_max']} откликов · <b>{money(quote['cost'])}</b>\n"
        + " · ".join(requirements)
        + f"\nОхват: {coverage} · срок {draft['duration_hours']} ч"
    )
    if claim_tip(recruitment.db, player_id, "recruitment_requirements"):
        text += "\n\n💡 Более строгие требования уменьшают число кандидатов, но помогают отсеять слабые варианты. Чем выше депозит, тем меньше риск магазина."
    await present(target, text, recruitment_draft_keyboard(draft, quote))

