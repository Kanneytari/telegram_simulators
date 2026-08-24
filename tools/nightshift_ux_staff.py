from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "shadow_market_simulator" / "app"

def read(path): return Path(path).read_text(encoding="utf-8")
def write(path, text): Path(path).write_text(text, encoding="utf-8")
def once(path, old, new):
    text = read(path); count = text.count(old)
    if count != 1: raise RuntimeError(f"{path}: expected one match, got {count}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))
def section(path, start, end, new):
    text = read(path); i = text.find(start); j = text.find(end, i + len(start))
    if i < 0 or j < 0: raise RuntimeError(f"{path}: section missing {start!r} -> {end!r}")
    write(path, text[:i] + new.rstrip() + "\n\n" + text[j:])
def tail(path, start):
    text = read(path); i = text.find(start)
    if i < 0: raise RuntimeError(f"{path}: tail marker missing {start!r}")
    write(path, text[:i])

# Status means actual operational availability.
insights = APP / "staff_insights.py"
once(insights,
     '                        "Стартовые партии находятся у оптового сотрудника и не выставлены на витрину.\\n\\n"\n                        "Открой «Команда», выбери оптового сотрудника и самостоятельно распредели товар между розничными сотрудниками. "\n                        "Непокрытый депозитом риск появляется только после твоего решения передать сотруднику слишком дорогой объём.",',
     '                        "Стартовые партии уже находятся на складе у складмена.\\n\\n"\n                        "Открой «Товар» → «Склад» и распредели товар между закладчиками. "\n                        "После подготовки фасовки появятся на витрине и начнут продаваться автоматически.",')
section(insights, "    def _task_status(", "    def _activity_details(", r'''    def _task_status(self, player_id: int, employee_id: int) -> str:
        now = utcnow()
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=?",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                return "неизвестно"
            if not employee["active"]:
                return "не работает"
            resignation = conn.execute(
                """SELECT 1 FROM inbox
                   WHERE player_id=? AND status='open' AND kind='resignation_notice'
                     AND json_extract(payload_json, '$.employee_id')=? LIMIT 1""",
                (player_id, employee_id),
            ).fetchone()
            if resignation:
                return "готовится уйти"
            task = conn.execute(
                """SELECT t.* FROM employee_tasks t
                   WHERE t.player_id=? AND t.employee_id=? AND t.status='active'
                   ORDER BY t.completes_at LIMIT 1""",
                (player_id, employee_id),
            ).fetchone()
            if task:
                remaining_real = max(0.0, (parse_dt(task["completes_at"]) - now).total_seconds() / 3600.0)
                remaining_game = remaining_real * self.simulation.effective_speed(player_id)
                eta = "менее 1 ч" if remaining_game < 1 else f"~{remaining_game:.1f} ч"
                labels = {
                    "receive_batch": "получает партию",
                    "handoff": "готовит передачу",
                    "prepare_positions": "готовит товар",
                }
                return f"{labels.get(task['kind'], task['kind'])} · {eta}"
            if not employee["available"]:
                if employee["unavailable_until"]:
                    remaining_real = max(0.0, (parse_dt(employee["unavailable_until"]) - now).total_seconds() / 3600.0)
                    remaining_game = remaining_real * self.simulation.effective_speed(player_id)
                    eta = "менее 1 ч" if remaining_game < 1 else f"~{remaining_game:.1f} ч"
                    return f"отдыхает · {eta}" if employee["role"] == "courier" else f"недоступен · {eta}"
                return "временно недоступен"
            if employee["role"] == "courier":
                waiting = int(conn.execute(
                    """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                       WHERE player_id=? AND retail_employee_id=? AND status='waiting'""",
                    (player_id, employee_id),
                ).fetchone()[0])
                if waiting:
                    return f"ожидает товар · {waiting} ед."
                preparing = int(conn.execute(
                    """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                       WHERE player_id=? AND retail_employee_id=? AND status='preparing'""",
                    (player_id, employee_id),
                ).fetchone()[0])
                if preparing:
                    return f"готовит товар · {preparing} ед."
                published = int(conn.execute(
                    """SELECT COALESCE(SUM(position_count*pack_size),0) FROM retail_positions
                       WHERE player_id=? AND employee_id=? AND position_count>0""",
                    (player_id, employee_id),
                ).fetchone()[0])
                if published:
                    return f"ждёт продажи · {published} ед."
            else:
                ready = int(conn.execute(
                    """SELECT COALESCE(SUM(remaining),0) FROM batches
                       WHERE player_id=? AND responsible_employee_id=?
                         AND status='warehouse' AND remaining>0""",
                    (player_id, employee_id),
                ).fetchone()[0])
                if ready:
                    return f"ждёт распределения · {ready} ед."
        return "свободен"''')
text = read(insights)
text = text.replace('"Подготовка передачи рознице"', '"Подготовка передачи закладчику"')
text = text.replace('"Подготовка позиций к публикации"', '"Подготовка товара к витрине"')
text = text.replace('                    positions = int(published["positions"] or 0)\n', '')
text = text.replace('parts.append(f"витрина {published_units} ед. / {positions} поз.")', 'parts.append(f"витрина {published_units} ед.")')
text = text.replace('f"Средняя: <b>{average:.1f} поз. / игровые сутки</b>"', 'f"Средняя: <b>{average:.1f} фасовок / игровые сутки</b>"')
text = text.replace('f"Последние 24 игровых ч: {last} поз."', 'f"Последние 24 игровых ч: {last} фасовок"')
write(insights, text)

ui = APP / "ui_staff.py"
once(ui, "from .ui_common import clean, money, nav_row, notice, pct, present, rating", "from .ui_common import claim_tip, clean, money, nav_row, notice, pct, present, rating")
section(ui, "def _team_keyboard(", "async def render_team(", r'''def _team_keyboard(game, player_id: int, employees) -> InlineKeyboardMarkup:
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
    return InlineKeyboardMarkup(inline_keyboard=rows)''')
section(ui, "async def render_team(", "def _courier_profile_text(", r'''async def render_team(target: Message, game, simulation, player_id: int, *, flash: str | None = None) -> None:
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
    await present(target, notice(flash, body), _team_keyboard(game, player_id, employees))''')
section(ui, "def _courier_profile_text(", "def _warehouse_profile_text(", r'''def _courier_profile_text(game, player_id: int, employee_id: int) -> str | None:
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
    return text''')
section(ui, "def _warehouse_profile_text(", "def _profile_keyboard(", r'''def _warehouse_profile_text(game, player_id: int, employee_id: int) -> str | None:
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
    )''')
once(ui, 'InlineKeyboardButton(text="Партии", callback_data=f"team:batches:{employee_id}")', 'InlineKeyboardButton(text="Товар", callback_data=f"team:batches:{employee_id}")')
section(ui, "async def render_development(", "def deposit_keyboard(", r'''async def render_development(target: Message, game, player_id: int, employee_id: int, *, flash: str | None = None) -> None:
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
    await present(target, notice(flash, text), development_keyboard(game, player_id, employee_id))''')
section(ui, "def batches_keyboard(", "async def render_batches(", r'''def batches_keyboard(rows, back_callback: str = "menu:procurement", back_text: str = "← Товар") -> InlineKeyboardMarkup:
    buttons = []
    for batch in rows:
        state = "получает" if batch["status"] == "receiving" else "готово"
        buttons.append([InlineKeyboardButton(
            text=f"{batch['product_title']} · {batch['remaining']} ед. · {batch['employee_alias']} · {state}",
            callback_data=f"team:batch:{batch['id']}",
        )])
    buttons.append(nav_row(back_callback, back_text))
    return InlineKeyboardMarkup(inline_keyboard=buttons)''')
section(ui, "async def render_batches(", "def _recipient_label(", r'''async def render_batches(target: Message, game, player_id: int, employee_id: int | None = None, *, flash: str | None = None) -> None:
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
    body = f"<b>📦 Склад · {len(rows)} партий</b>"
    if not rows:
        body += "\n\nНа складе нет активных партий."
    keyboard = batches_keyboard(rows) if employee_id is None else batches_keyboard(rows, f"team:employee:{employee_id}", "← Профиль")
    await present(target, notice(flash, body), keyboard)''')
text = read(ui)
text = text.replace('f"После передачи: ответственность {money(after)} · депозит {money(employee[\'deposit\'])}"', 'f"После передачи: товар на руках {money(after)} · депозит {money(employee[\'deposit\'])}"')
text = text.replace('f"\\n🔴 Без покрытия: {money(unsecured)}"', 'f"\\n🔴 Не покрыто депозитом: {money(unsecured)}"')
text = text.replace('"\\nТовар полностью покрыт."', '"\\n🟢 Полностью покрыто депозитом."')
text = text.replace('f"<b>Сменить ответственного</b>', 'f"<b>Сменить складмена</b>')
write(ui, text)
once(ui,
     '            InlineKeyboardButton(text="Розница", callback_data="team:terms:courier"),\n            InlineKeyboardButton(text="Опт", callback_data="team:terms:warehouse"),',
     '            InlineKeyboardButton(text="Закладчики", callback_data="team:terms:courier"),\n            InlineKeyboardButton(text="Складмены", callback_data="team:terms:warehouse"),')
section(ui, "async def render_terms_root(", "def terms_editor_keyboard(", r'''async def render_terms_root(target: Message, game, player_id: int, *, flash: str | None = None) -> None:
    retail = game.compensation_policy(player_id, "courier")
    wholesale = game.compensation_policy(player_id, "warehouse")
    text = (
        "<b>Оплата команды</b>\n\n"
        f"Закладчики\n{_policy_line('courier', retail)}\n\n"
        f"Складмены\n{_policy_line('warehouse', wholesale)}"
    )
    await present(target, notice(flash, text), terms_root_keyboard())''')
section(ui, "async def render_terms_editor(", "def recruitment_root_keyboard(", r'''async def render_terms_editor(target: Message, game, player_id: int, state: FSMContext, role: str, *, reset: bool = False) -> None:
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
    await present(target, text, terms_editor_keyboard(role))''')
section(ui, "def channels_keyboard(", "def recruitment_draft_keyboard(", r'''def channels_keyboard() -> InlineKeyboardMarkup:
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
    await present(target, text, channels_keyboard())''')
section(ui, "def recruitment_draft_keyboard(", "async def render_recruitment_draft(", r'''def recruitment_draft_keyboard(draft, quote) -> InlineKeyboardMarkup:
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
    return InlineKeyboardMarkup(inline_keyboard=rows)''')
section(ui, "async def render_recruitment_draft(", "def candidates_keyboard(", r'''async def render_recruitment_draft(target: Message, recruitment, player_id: int) -> None:
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
    await present(target, text, recruitment_draft_keyboard(draft, quote))''')
# Old candidate/router implementation is dead; canonical candidate handling is in ui_staff_handlers.py.
tail(ui, "def candidates_keyboard(")

handlers = APP / "ui_staff_handlers.py"
section(handlers, "async def render_batch(", "async def render_candidate(", r'''async def render_batch(target: Message, game, player_id: int, batch_id: int, *, flash: str | None = None) -> None:
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
        rows.append([InlineKeyboardButton(text="Назначить складмена", callback_data=f"team:reassign:{batch_id}")]) if warehouse_count else [InlineKeyboardButton(text="Нанять сотрудника", callback_data="team:recruit")]
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
    await present(target, notice(flash, text), InlineKeyboardMarkup(inline_keyboard=rows))''')
section(handlers, "async def render_candidate(", "def candidates_keyboard(", r'''async def render_candidate(target: Message, game, player_id: int, candidate_id: int) -> None:
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
    await present(target, "\n".join(lines), keyboard)''')
text = read(handlers)
text = text.replace('current = "опт" if employee["role"] == "warehouse" else "розница"', 'current = "складмен" if employee["role"] == "warehouse" else "закладчик"')
text = text.replace('new = "розница" if employee["role"] == "warehouse" else "опт"', 'new = "закладчик" if employee["role"] == "warehouse" else "складмен"')
write(handlers, text)
section(handlers, '    @router.callback_query(F.data.startswith("recruit:set:"))', '    @router.callback_query(F.data == "recruit:run")', r'''    @router.callback_query(F.data.startswith("recruit:set:"))
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
        await render_recruitment_draft(callback.message, recruitment, callback.from_user.id)''')

print("staff UX transform ok")
