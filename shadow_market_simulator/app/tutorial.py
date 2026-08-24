from __future__ import annotations

import json
from datetime import timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from . import (
    courier_core,
    dispute_payments,
    procurement_market,
    simulation,
    ui_commerce,
    ui_navigation,
    ui_staff_handlers,
    workflow,
)
from .simulation import clamp, iso, utcnow
from .ui_common import clean, money, present, tutorial_hint


STARTING_FREE_CASH = 500_000
STARTING_RESERVE = 30_000
STARTING_CAPITAL = STARTING_FREE_CASH + STARTING_RESERVE

STAGE_PROCUREMENT = "procurement"
STAGE_PICKUP_WAIT = "pickup_wait"
STAGE_HANDOFF = "handoff"
STAGE_HANDOFF_WAIT = "handoff_wait"
STAGE_PREP_WAIT = "prep_wait"
STAGE_PRICE = "price"
STAGE_SALE_WAIT = "sale_wait"
STAGE_REVIEW = "review"
STAGE_DISPUTE = "dispute"
STAGE_TEAM = "team"
STAGE_COMPLETE = "complete"


def _ensure_schema_conn(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tutorial_state (
               player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
               stage TEXT NOT NULL DEFAULT 'procurement',
               data_json TEXT NOT NULL DEFAULT '{}',
               active INTEGER NOT NULL DEFAULT 1,
               created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
               updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
           )"""
    )


def tutorial_state(db, player_id: int) -> dict | None:
    with db.connect() as conn:
        _ensure_schema_conn(conn)
        row = conn.execute(
            "SELECT * FROM tutorial_state WHERE player_id=?",
            (player_id,),
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["data_json"] or "{}")
    except (TypeError, ValueError):
        data = {}
    return {
        "player_id": player_id,
        "stage": str(row["stage"]),
        "active": bool(row["active"]),
        "data": data,
    }


def tutorial_active(db, player_id: int) -> bool:
    state = tutorial_state(db, player_id)
    return bool(state and state["active"])


def _set_stage(db, player_id: int, stage: str, **data) -> None:
    current = tutorial_state(db, player_id)
    merged = dict(current["data"] if current else {})
    merged.update({key: value for key, value in data.items() if value is not None})
    with db.connect() as conn:
        _ensure_schema_conn(conn)
        conn.execute(
            """INSERT INTO tutorial_state(player_id, stage, data_json, active)
               VALUES (?, ?, ?, 1)
               ON CONFLICT(player_id) DO UPDATE SET
                   stage=excluded.stage,
                   data_json=excluded.data_json,
                   active=1,
                   updated_at=CURRENT_TIMESTAMP""",
            (player_id, stage, json.dumps(merged, ensure_ascii=False)),
        )


def _finish_tutorial(db, player_id: int) -> None:
    with db.connect() as conn:
        _ensure_schema_conn(conn)
        conn.execute(
            """UPDATE tutorial_state
               SET stage=?, active=0, updated_at=CURRENT_TIMESTAMP
               WHERE player_id=?""",
            (STAGE_COMPLETE, player_id),
        )


def _free_cash(game, player_id: int) -> int:
    if hasattr(game, "_free_cash_conn"):
        with game.db.connect() as conn:
            return int(game._free_cash_conn(conn, player_id))
    with game.db.connect() as conn:
        shop = conn.execute(
            "SELECT balance, reserve_target FROM shops WHERE player_id=?",
            (player_id,),
        ).fetchone()
        deposits = int(
            conn.execute(
                "SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1",
                (player_id,),
            ).fetchone()[0]
        )
    return int(shop["balance"]) - int(shop["reserve_target"]) - deposits


def _skip_markup(*, extra: list[InlineKeyboardButton] | None = None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="⏩ Пропустить ожидание", callback_data="tutorial:skip")]]
    if extra:
        rows.append(extra)
    rows.append([InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tutorial_home_markup(stage: str, data: dict) -> InlineKeyboardMarkup:
    if stage == STAGE_PROCUREMENT:
        rows = [[InlineKeyboardButton(text="📦 Выбрать товар", callback_data="menu:product")]]
    elif stage in {STAGE_PICKUP_WAIT, STAGE_HANDOFF_WAIT, STAGE_PREP_WAIT, STAGE_SALE_WAIT}:
        rows = [[InlineKeyboardButton(text="⏩ Пропустить ожидание", callback_data="tutorial:skip")]]
    elif stage == STAGE_HANDOFF:
        rows = [[InlineKeyboardButton(text="📦 Открыть склад", callback_data="team:batches")]]
    elif stage == STAGE_PRICE:
        rows = [[InlineKeyboardButton(text="🏷 Открыть витрину", callback_data="menu:storefront")]]
    elif stage == STAGE_REVIEW:
        rows = [[InlineKeyboardButton(text="Продолжить обучение", callback_data="tutorial:continue")]]
    elif stage == STAGE_DISPUTE:
        rows = [[InlineKeyboardButton(text="⚖️ Разобрать диспут", callback_data="tutorial:open_dispute")]]
    elif stage == STAGE_TEAM:
        rows = [
            [InlineKeyboardButton(text="👥 Открыть команду", callback_data="menu:team")],
            [InlineKeyboardButton(text="✅ Завершить обучение", callback_data="tutorial:finish")],
        ]
    else:
        rows = [[InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _home_text(game, player_id: int, state: dict) -> str:
    with game.db.connect() as conn:
        shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
    free = _free_cash(game, player_id)
    header = (
        f"<b>🌒 {clean(shop['name'])}</b>\n\n"
        f"Баланс: <b>{money(shop['balance'])}</b>\n"
        f"Свободно: <b>{money(free)}</b>"
    )
    stage = state["stage"]
    data = state["data"]
    if stage == STAGE_PROCUREMENT:
        quote = (
            "Начнём с нуля. Склад пустой, зато у тебя есть деньги на первую закупку. "
            "Выбери стафф сам. Цена, качество и надёжность поставки отличаются. "
            "В дальнейшем любая сделка может оказаться неудачной."
        )
    elif stage == STAGE_PICKUP_WAIT:
        quote = (
            "Складмен поехал за партией. Обычно получение товара занимает игровое время. "
            "Во время обучения ожидание можно пропускать кнопкой ниже."
        )
    elif stage == STAGE_HANDOFF:
        quote = (
            "Партия у складмена. Пока товар лежит у него, он не продаётся. "
            "Передай часть партии закладчику, который подготовит её к витрине."
        )
    elif stage == STAGE_HANDOFF_WAIT:
        quote = (
            "Складмен готовит передачу. В обычной игре это занимает время и держит сотрудника занятым."
        )
    elif stage == STAGE_PREP_WAIT:
        quote = (
            "Закладчик получил товар и готовит позиции к продаже. Его темп, состояние и оснащение влияют на работу."
        )
    elif stage == STAGE_PRICE:
        quote = (
            "Товар появился на витрине. Теперь реши, по какой цене продавать. "
            "Высокая цена увеличивает прибыль с заказа, но снижает спрос и повышает ожидания покупателей."
        )
    elif stage == STAGE_SALE_WAIT:
        quote = (
            "Цена выставлена. Продажи происходят со временем, а не сразу после публикации товара. "
            "Для обучения первую продажу можно промотать."
        )
    elif stage == STAGE_REVIEW:
        order_id = data.get("order_id")
        quote = (
            f"Первый заказ{f' #{order_id}' if order_id else ''} прошёл. "
            "Выручка ещё не равна чистой прибыли: есть себестоимость товара и выплаты сотрудникам. "
            "После заказов появляются оценки товара и закладчика, а их история влияет на дальнейший бизнес."
        )
    elif stage == STAGE_DISPUTE:
        quote = (
            "Не каждый заказ заканчивается отзывом. Иногда клиент открывает диспут. "
            "Можно запросить пояснение сотрудника, изучить контекст и решить, компенсировать заказ или отказать."
        )
    elif stage == STAGE_TEAM:
        quote = (
            "Последний важный блок — команда. У сотрудников накапливается реальная статистика: темп, оценки, "
            "нагрузка, отношения, депозит и потери. Здесь же находятся найм, условия оплаты, отдых, развитие и увольнение. "
            "Сравнивай людей по истории работы, а не по одной операции."
        )
    else:
        quote = "Обучение завершено."
    return header + "\n\n" + tutorial_hint(quote)


def _install_new_player_setup() -> None:
    original = simulation.SimulationEngine.ensure_player
    if getattr(original, "_nightshift_tutorial", False):
        return

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = original(self, player_id, username)
        if not created:
            return False
        with self.db.connect() as conn:
            _ensure_schema_conn(conn)
            # The first run now starts with money and an empty logistics chain.
            conn.execute("DELETE FROM batches WHERE player_id=?", (player_id,))
            conn.execute(
                "UPDATE shops SET balance=?, reserve_target=? WHERE player_id=?",
                (STARTING_CAPITAL, STARTING_RESERVE, player_id),
            )
            conn.execute(
                """UPDATE ledger SET amount=?, note='Стартовый капитал'
                   WHERE player_id=? AND kind='capital'""",
                (STARTING_CAPITAL, player_id),
            )
            conn.execute(
                """UPDATE inbox
                   SET title='Первая смена',
                       body='Склад пуст. Начни с первой закупки в разделе «Товар».'
                   WHERE player_id=? AND kind='tutorial'""",
                (player_id,),
            )
            conn.execute(
                """INSERT OR REPLACE INTO tutorial_state(player_id, stage, data_json, active)
                   VALUES (?, ?, '{}', 1)""",
                (player_id, STAGE_PROCUREMENT),
            )
        return True

    ensure_player._nightshift_tutorial = True
    simulation.SimulationEngine.ensure_player = ensure_player


def _install_tutorial_offer_filter() -> None:
    original = procurement_market.ProcurementMarketGameService.offers
    if getattr(original, "_nightshift_tutorial", False):
        return

    def offers(self, player_id: int, product_id: int | None = None):
        rows = list(original(self, player_id, product_id))
        state = tutorial_state(self.db, player_id)
        if not state or not state["active"] or state["stage"] != STAGE_PROCUREMENT:
            return rows
        free = _free_cash(self, player_id)
        affordable = [
            row for row in rows
            if int(row["quantity"]) * int(row["unit_cost"]) <= free
        ]
        return affordable

    offers._nightshift_tutorial = True
    procurement_market.ProcurementMarketGameService.offers = offers


def _install_first_purchase_protection() -> None:
    original = workflow.WorkflowGameService.buy_offer_for_employee
    if getattr(original, "_nightshift_tutorial", False):
        return

    def buy_offer_for_employee(self, player_id: int, offer_id: int, employee_id: int) -> str:
        state = tutorial_state(self.db, player_id)
        if not state or not state["active"] or state["stage"] != STAGE_PROCUREMENT:
            return original(self, player_id, offer_id, employee_id)

        now = utcnow()
        with self.db.connect() as conn:
            offer = conn.execute(
                """SELECT o.*, s.title supplier_title, p.title product_title,
                          COALESCE(o.offer_quality_mean, s.quality_mean) resolved_quality_mean,
                          COALESCE(o.offer_quality_sigma, s.quality_sigma) resolved_quality_sigma
                   FROM supplier_offers o
                   JOIN suppliers s ON s.id=o.supplier_id
                   JOIN products p ON p.id=o.product_id
                   WHERE o.id=? AND o.player_id=? AND o.status='open'""",
                (offer_id, player_id),
            ).fetchone()
            employee = conn.execute(
                """SELECT * FROM employees
                   WHERE id=? AND player_id=? AND active=1 AND role='warehouse'""",
                (employee_id, player_id),
            ).fetchone()
            if not offer:
                return "Предложение уже недоступно."
            if not employee:
                return "Складмен больше недоступен."
            total = int(offer["quantity"]) * int(offer["unit_cost"])
            if _free_cash(self, player_id) < total:
                return f"Недостаточно свободных денег. Нужно {total:,} ₽."

            quality = clamp(
                self.rng.gauss(
                    float(offer["resolved_quality_mean"]),
                    float(offer["resolved_quality_sigma"]),
                ),
                60.0,
                99.0,
            )
            conn.execute("UPDATE shops SET balance=balance-? WHERE player_id=?", (total, player_id))
            cur = conn.execute(
                """INSERT INTO batches(
                       player_id, supplier_id, product_id, responsible_employee_id,
                       quantity, remaining, unit_cost, quality, status
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'receiving')""",
                (
                    player_id,
                    offer["supplier_id"],
                    offer["product_id"],
                    employee_id,
                    offer["quantity"],
                    offer["quantity"],
                    offer["unit_cost"],
                    quality,
                ),
            )
            batch_id = int(cur.lastrowid)
            game_hours = 1.5 + int(offer["quantity"]) / 100.0 * 0.8 + self.rng.uniform(0.2, 1.0)
            conn.execute(
                """INSERT INTO employee_tasks(
                       player_id, employee_id, kind, batch_id, product_id, quantity,
                       completes_at, note
                   ) VALUES (?, ?, 'receive_batch', ?, ?, ?, ?, ?)""",
                (
                    player_id,
                    employee_id,
                    batch_id,
                    offer["product_id"],
                    offer["quantity"],
                    iso(now + timedelta(hours=game_hours / self.simulation.effective_speed(player_id))),
                    f"Приём партии {offer['product_title']}",
                ),
            )
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, ?, 'procurement', 'offer', ?, ?)""",
                (
                    player_id,
                    -total,
                    offer_id,
                    f"Партия #{batch_id}: {offer['product_title']} · ответственный {employee['alias']}",
                ),
            )
            conn.execute("UPDATE supplier_offers SET status='bought' WHERE id=?", (offer_id,))

        _set_stage(
            self.db,
            player_id,
            STAGE_PICKUP_WAIT,
            batch_id=batch_id,
            product_id=int(offer["product_id"]),
            warehouse_employee_id=employee_id,
        )
        return (
            "<b>✅ Куплено</b>\n\n"
            f"{clean(offer['product_title'])} · {int(offer['quantity'])} ед. · {money(total)}\n"
            f"🚚 {clean(employee['alias'])} поехал за партией.\n\n"
            + tutorial_hint(
                "На этот раз сделка точно дойдёт до следующего этапа. В обычной игре поставка — это риск, "
                "поэтому сравнивай цену, качество и надёжность поставщика."
            )
        )

    buy_offer_for_employee._nightshift_tutorial = True
    workflow.WorkflowGameService.buy_offer_for_employee = buy_offer_for_employee


def _install_handoff_progress() -> None:
    original = workflow.WorkflowGameService.allocate_to_retail
    if getattr(original, "_nightshift_tutorial", False):
        return

    def allocate_to_retail(self, player_id: int, batch_id: int, retail_employee_id: int, quantity: int) -> str:
        result = original(self, player_id, batch_id, retail_employee_id, quantity)
        state = tutorial_state(self.db, player_id)
        if not state or not state["active"] or state["stage"] != STAGE_HANDOFF:
            return result
        with self.db.connect() as conn:
            allocation = conn.execute(
                """SELECT id FROM retail_allocations
                   WHERE player_id=? AND batch_id=? AND retail_employee_id=?
                   ORDER BY id DESC LIMIT 1""",
                (player_id, batch_id, retail_employee_id),
            ).fetchone()
        if allocation:
            _set_stage(
                self.db,
                player_id,
                STAGE_HANDOFF_WAIT,
                batch_id=batch_id,
                allocation_id=int(allocation["id"]),
                retail_employee_id=retail_employee_id,
            )
        return result

    allocate_to_retail._nightshift_tutorial = True
    workflow.WorkflowGameService.allocate_to_retail = allocate_to_retail


def _install_price_progress() -> None:
    from . import game as game_module

    original = game_module.GameService.change_listing_price
    if getattr(original, "_nightshift_tutorial", False):
        return

    def change_listing_price(self, player_id: int, listing_id: int, percent: int) -> str:
        result = original(self, player_id, listing_id, percent)
        state = tutorial_state(self.db, player_id)
        if state and state["active"] and state["stage"] == STAGE_PRICE and result.startswith("Цена изменена"):
            _set_stage(self.db, player_id, STAGE_SALE_WAIT, listing_id=listing_id)
        return result

    change_listing_price._nightshift_tutorial = True
    game_module.GameService.change_listing_price = change_listing_price


def _install_random_event_protection() -> None:
    original_events = courier_core.CourierCoreSimulationEngine._simulate_management_events
    if not getattr(original_events, "_nightshift_tutorial", False):

        def protected_events(self, conn, player_id: int, sim_hours: float, now) -> int:
            if tutorial_active(self.db, player_id):
                self._ensure_courier_profiles_conn(conn, player_id)
                self._recover_courier_state_conn(conn, player_id, sim_hours)
                return 0
            return original_events(self, conn, player_id, sim_hours, now)

        protected_events._nightshift_tutorial = True
        courier_core.CourierCoreSimulationEngine._simulate_management_events = protected_events

    original_dispute = courier_core.CourierCoreSimulationEngine._dispute_probability
    if not getattr(original_dispute, "_nightshift_tutorial", False):

        def protected_dispute(self, client, employee, quality: float, modifier: float) -> float:
            employee_id = self._employee_id(employee)
            if employee_id:
                with self.db.connect() as conn:
                    owner = conn.execute(
                        "SELECT player_id FROM employees WHERE id=?",
                        (employee_id,),
                    ).fetchone()
                if owner:
                    state = tutorial_state(self.db, int(owner["player_id"]))
                    if state and state["active"] and state["stage"] == STAGE_SALE_WAIT:
                        return 0.0
            return original_dispute(self, client, employee, quality, modifier)

        protected_dispute._nightshift_tutorial = True
        courier_core.CourierCoreSimulationEngine._dispute_probability = protected_dispute


def _install_dispute_progress() -> None:
    original = dispute_payments.DisputePaymentGameService.resolve_dispute_with_source
    if getattr(original, "_nightshift_tutorial", False):
        return

    def resolve_dispute_with_source(self, player_id: int, dispute_id: int, decision: str, source: str) -> str:
        result = original(self, player_id, dispute_id, decision, source)
        state = tutorial_state(self.db, player_id)
        if not state or not state["active"] or state["stage"] != STAGE_DISPUTE:
            return result
        expected = int(state["data"].get("dispute_id", 0) or 0)
        if expected and expected != dispute_id:
            return result
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT status FROM disputes WHERE id=? AND player_id=?",
                (dispute_id, player_id),
            ).fetchone()
        if row and row["status"] == "resolved":
            _set_stage(self.db, player_id, STAGE_TEAM)
        return result

    resolve_dispute_with_source._nightshift_tutorial = True
    dispute_payments.DisputePaymentGameService.resolve_dispute_with_source = resolve_dispute_with_source


def _install_handoff_tutorial_flag() -> None:
    original = workflow.WorkflowGameService.needs_first_handoff_tutorial
    if getattr(original, "_nightshift_tutorial", False):
        return

    def needs_first_handoff_tutorial(self, player_id: int) -> bool:
        state = tutorial_state(self.db, player_id)
        if state and state["active"]:
            return state["stage"] == STAGE_HANDOFF
        return original(self, player_id)

    needs_first_handoff_tutorial._nightshift_tutorial = True
    workflow.WorkflowGameService.needs_first_handoff_tutorial = needs_first_handoff_tutorial


def _active_task_for_stage(conn, player_id: int, state: dict):
    data = state["data"]
    if state["stage"] == STAGE_PICKUP_WAIT:
        return conn.execute(
            """SELECT * FROM employee_tasks
               WHERE player_id=? AND kind='receive_batch' AND batch_id=? AND status='active'
               ORDER BY id DESC LIMIT 1""",
            (player_id, int(data.get("batch_id", 0))),
        ).fetchone()
    if state["stage"] == STAGE_HANDOFF_WAIT:
        return conn.execute(
            """SELECT * FROM employee_tasks
               WHERE player_id=? AND kind='handoff' AND allocation_id=? AND status='active'
               ORDER BY id DESC LIMIT 1""",
            (player_id, int(data.get("allocation_id", 0))),
        ).fetchone()
    if state["stage"] == STAGE_PREP_WAIT:
        return conn.execute(
            """SELECT * FROM employee_tasks
               WHERE player_id=? AND kind='place_stashes' AND allocation_id=? AND status='active'
               ORDER BY id DESC LIMIT 1""",
            (player_id, int(data.get("allocation_id", 0))),
        ).fetchone()
    return None


def skip_tutorial_wait(game, simulation_engine, player_id: int) -> str:
    state = tutorial_state(game.db, player_id)
    if not state or not state["active"]:
        return "Обучение уже завершено."

    if state["stage"] in {STAGE_PICKUP_WAIT, STAGE_HANDOFF_WAIT, STAGE_PREP_WAIT}:
        now = utcnow()
        with game.db.connect() as conn:
            task = _active_task_for_stage(conn, player_id, state)
            if task:
                conn.execute(
                    "UPDATE employee_tasks SET completes_at=? WHERE id=?",
                    (iso(now - timedelta(seconds=1)), int(task["id"])),
                )
                simulation_engine._process_tasks(conn, player_id, now)

            if state["stage"] == STAGE_PICKUP_WAIT:
                batch = conn.execute(
                    "SELECT status FROM batches WHERE id=? AND player_id=?",
                    (int(state["data"].get("batch_id", 0)), player_id),
                ).fetchone()
                if batch and batch["status"] == "warehouse":
                    _set_stage(game.db, player_id, STAGE_HANDOFF)
                    return "Партия получена."
            elif state["stage"] == STAGE_HANDOFF_WAIT:
                allocation = conn.execute(
                    "SELECT status FROM retail_allocations WHERE id=? AND player_id=?",
                    (int(state["data"].get("allocation_id", 0)), player_id),
                ).fetchone()
                if allocation and allocation["status"] == "preparing":
                    _set_stage(game.db, player_id, STAGE_PREP_WAIT)
                    return "Передача завершена. Закладчик начал подготовку."
            else:
                allocation = conn.execute(
                    "SELECT status, product_id FROM retail_allocations WHERE id=? AND player_id=?",
                    (int(state["data"].get("allocation_id", 0)), player_id),
                ).fetchone()
                if allocation and allocation["status"] == "published":
                    _set_stage(
                        game.db,
                        player_id,
                        STAGE_PRICE,
                        product_id=int(allocation["product_id"]),
                    )
                    return "Товар появился на витрине."
        return "Задача ещё не готова к следующему этапу."

    if state["stage"] == STAGE_SALE_WAIT:
        listing_id = int(state["data"].get("listing_id", 0) or 0)
        with game.db.connect() as conn:
            if listing_id:
                listing = conn.execute(
                    """SELECT l.*, p.base_market_price, p.base_demand, p.complaint_modifier
                       FROM listings l JOIN products p ON p.id=l.product_id
                       WHERE l.id=? AND l.player_id=? AND l.active=1""",
                    (listing_id, player_id),
                ).fetchone()
            else:
                listing = None
            if not listing:
                listing = conn.execute(
                    """SELECT l.*, p.base_market_price, p.base_demand, p.complaint_modifier
                       FROM listings l JOIN products p ON p.id=l.product_id
                       WHERE l.player_id=? AND l.active=1
                         AND EXISTS (
                             SELECT 1 FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
                             WHERE rp.player_id=l.player_id AND rp.product_id=l.product_id
                               AND rp.pack_size=l.pack_size AND rp.position_count>0
                               AND e.active=1 AND e.available=1 AND e.role='courier'
                         )
                       ORDER BY l.id LIMIT 1""",
                    (player_id,),
                ).fetchone()
            if not listing:
                return "На витрине пока нет доступной позиции для продажи."
            before = int(
                conn.execute(
                    "SELECT COALESCE(MAX(id),0) FROM orders WHERE player_id=?",
                    (player_id,),
                ).fetchone()[0]
            )
            result = simulation_engine._create_retail_order(conn, player_id, listing, utcnow())
            if result is None:
                return "Пока не удалось создать первый заказ."
            order = conn.execute(
                "SELECT * FROM orders WHERE player_id=? AND id>? ORDER BY id DESC LIMIT 1",
                (player_id, before),
            ).fetchone()
        if order:
            _set_stage(
                game.db,
                player_id,
                STAGE_REVIEW,
                order_id=int(order["id"]),
                product_id=int(order["product_id"]),
                listing_id=int(listing["id"]),
            )
            return "Первый заказ завершён."
    return "Сейчас нечего проматывать."


def create_tutorial_dispute(game, simulation_engine, player_id: int) -> tuple[int, int] | None:
    state = tutorial_state(game.db, player_id)
    if not state or not state["active"] or state["stage"] != STAGE_REVIEW:
        return None
    order_id = int(state["data"].get("order_id", 0) or 0)
    if not order_id:
        return None
    now = utcnow()
    with game.db.connect() as conn:
        existing = conn.execute(
            "SELECT id FROM disputes WHERE player_id=? AND order_id=? AND status='open' LIMIT 1",
            (player_id, order_id),
        ).fetchone()
        if existing:
            dispute_id = int(existing["id"])
            inbox = conn.execute(
                """SELECT id FROM inbox WHERE player_id=? AND status='open' AND kind='dispute'
                   AND json_extract(payload_json, '$.dispute_id')=? ORDER BY id DESC LIMIT 1""",
                (player_id, dispute_id),
            ).fetchone()
            inbox_id = int(inbox["id"]) if inbox else 0
        else:
            order = conn.execute(
                """SELECT o.*, c.alias client_alias
                   FROM orders o JOIN clients c ON c.id=o.client_id
                   WHERE o.id=? AND o.player_id=?""",
                (order_id, player_id),
            ).fetchone()
            if not order:
                return None
            message = "Описание оказалось недостаточно понятным. Не могу уверенно найти заказ и хочу решить вопрос."
            evidence = {
                "description_present": True,
                "extra_material_present": False,
                "client_tone": "спокойный",
                "order_value": int(order["revenue"]),
                "tutorial": True,
            }
            deadline = now + timedelta(hours=2 / max(0.1, simulation_engine.effective_speed(player_id)))
            cur = conn.execute(
                """INSERT INTO disputes(player_id, order_id, true_cause, message, evidence_json, deadline_at)
                   VALUES (?, ?, 'DESCRIPTION_ERROR', ?, ?, ?)""",
                (player_id, order_id, message, json.dumps(evidence, ensure_ascii=False), iso(deadline)),
            )
            dispute_id = int(cur.lastrowid)
            conn.execute("UPDATE orders SET status='disputed' WHERE id=?", (order_id,))
            conn.execute("UPDATE employees SET disputes=disputes+1 WHERE id=?", (order["employee_id"],))
            conn.execute("UPDATE clients SET disputes_total=disputes_total+1 WHERE id=?", (order["client_id"],))
            inbox_cur = conn.execute(
                """INSERT INTO inbox(
                       player_id, kind, priority, title, body, payload_json, expires_at, notified_at
                   ) VALUES (?, 'dispute', 'important', ?, ?, ?, ?, ?)""",
                (
                    player_id,
                    f"Диспут #{dispute_id}",
                    f"Клиент {order['client_alias']}: {message}",
                    json.dumps({"dispute_id": dispute_id, "tutorial": True}, ensure_ascii=False),
                    iso(deadline),
                    iso(now),
                ),
            )
            inbox_id = int(inbox_cur.lastrowid)
    _set_stage(game.db, player_id, STAGE_DISPUTE, dispute_id=dispute_id, inbox_id=inbox_id)
    return dispute_id, inbox_id


def _install_tutorial_renderers() -> None:
    original_home = ui_navigation.render_home
    if not getattr(original_home, "_nightshift_tutorial", False):

        async def render_home(target, db, game, simulation_engine, admin_ids, player_id: int, *, edit: bool = True):
            state = tutorial_state(db, player_id)
            if not state or not state["active"]:
                return await original_home(
                    target, db, game, simulation_engine, admin_ids, player_id, edit=edit
                )
            await present(
                target,
                _home_text(game, player_id, state),
                _tutorial_home_markup(state["stage"], state["data"]),
                edit=edit,
            )

        render_home._nightshift_tutorial = True
        ui_navigation.render_home = render_home

    original_product_root = ui_commerce.render_product_root
    if not getattr(original_product_root, "_nightshift_tutorial", False):

        async def render_product_root(target, db, game, player_id: int, *, flash: str | None = None):
            state = tutorial_state(db, player_id)
            if not state or not state["active"] or state["stage"] != STAGE_PROCUREMENT:
                return await original_product_root(target, db, game, player_id, flash=flash)
            products = game.procurement_products(player_id)
            body = (
                f"<b>📦 Товар</b>\n\nСвободно: <b>{money(_free_cash(game, player_id))}</b>\n\n"
                + tutorial_hint(
                    "Выбери стафф для первой закупки. Сравни предложения по цене, качеству и надёжности."
                )
            )
            if flash:
                body = f"{flash}\n\n{body}"
            await present(target, body, ui_commerce._procurement_products_keyboard(db, player_id, products))

        render_product_root._nightshift_tutorial = True
        ui_commerce.render_product_root = render_product_root

    original_proc_product = ui_commerce.render_procurement_product
    if not getattr(original_proc_product, "_nightshift_tutorial", False):

        async def render_procurement_product(target, game, player_id: int, product_id: int, *, flash: str | None = None):
            state = tutorial_state(game.db, player_id)
            if not state or not state["active"] or state["stage"] != STAGE_PICKUP_WAIT:
                return await original_proc_product(target, game, player_id, product_id, flash=flash)
            text = flash or "Партия куплена."
            text += "\n\n" + tutorial_hint(
                "Складмен получает товар. В обычной игре это занимает время. Сейчас промотай ожидание."
            )
            await present(target, text, _skip_markup())

        render_procurement_product._nightshift_tutorial = True
        ui_commerce.render_procurement_product = render_procurement_product

    original_batch = ui_staff_handlers.render_batch
    if not getattr(original_batch, "_nightshift_tutorial", False):

        async def render_batch(target, game, player_id: int, batch_id: int, *, flash: str | None = None):
            state = tutorial_state(game.db, player_id)
            if state and state["active"] and state["stage"] in {STAGE_HANDOFF_WAIT, STAGE_PREP_WAIT}:
                if state["stage"] == STAGE_HANDOFF_WAIT:
                    quote = "Складмен готовит передачу закладчику. Промотай ожидание, чтобы передача завершилась."
                else:
                    quote = "Закладчик готовит товар к витрине. Промотай этот этап, чтобы позиции появились в продаже."
                text = (flash + "\n\n" if flash else "") + tutorial_hint(quote)
                await present(target, text, _skip_markup())
                return
            await original_batch(target, game, player_id, batch_id, flash=flash)

        render_batch._nightshift_tutorial = True
        ui_staff_handlers.render_batch = render_batch

    original_storefront = ui_commerce.render_storefront_root
    if not getattr(original_storefront, "_nightshift_tutorial", False):

        async def render_storefront_root(target, db, game, simulation_engine, player_id: int):
            state = tutorial_state(db, player_id)
            if not state or not state["active"] or state["stage"] != STAGE_PRICE:
                return await original_storefront(target, db, game, simulation_engine, player_id)
            rows = ui_commerce._sales_products(db, player_id)
            trust = game.customer_metrics(player_id)
            text = (
                "<b>🏷 Витрина</b>\n\n"
                f"Доверие: {trust['trust_score']:.0f}/100\n\n"
                + tutorial_hint(
                    "Товар готов к продаже. Открой позицию и измени цену хотя бы на один шаг. "
                    "Чем выше цена, тем выше прибыль с заказа, но тем требовательнее покупатель."
                )
            )
            await present(target, text, ui_commerce._sales_root_keyboard(rows))

        render_storefront_root._nightshift_tutorial = True
        ui_commerce.render_storefront_root = render_storefront_root

    original_sales_product = ui_commerce.render_sales_product
    if not getattr(original_sales_product, "_nightshift_tutorial", False):

        async def render_sales_product(target, db, player_id: int, product_id: int):
            state = tutorial_state(db, player_id)
            if not state or not state["active"] or state["stage"] != STAGE_PRICE:
                return await original_sales_product(target, db, player_id, product_id)
            product, listings, published, avg, n = ui_commerce._product_listings(db, player_id, product_id)
            if not product:
                return
            rows = [[InlineKeyboardButton(
                text=f"×{listing['pack_size']} · {money(listing['price'])} · доступно {int(listing['positions'])}",
                callback_data=f"sales:listing:{listing['id']}",
            )] for listing in listings if int(listing["positions"]) > 0]
            rows.append([InlineKeyboardButton(text="← Витрина", callback_data="menu:storefront")])
            text = (
                f"<b>{clean(product['title'])}</b>\n\n{published} ед. готовы к продаже\n\n"
                + tutorial_hint("Выбери фасовку, у которой уже есть готовые позиции.")
            )
            await present(target, text, InlineKeyboardMarkup(inline_keyboard=rows))

        render_sales_product._nightshift_tutorial = True
        ui_commerce.render_sales_product = render_sales_product

    original_listing = ui_commerce.render_listing
    if not getattr(original_listing, "_nightshift_tutorial", False):

        async def render_listing(target, db, game, player_id: int, listing_id: int):
            state = tutorial_state(db, player_id)
            if state and state["active"] and state["stage"] == STAGE_SALE_WAIT:
                row = ui_commerce._listing_context(db, player_id, listing_id)
                price = money(row["price"]) if row else ""
                text = (
                    f"<b>Цена выставлена{f': {price}' if price else ''}</b>\n\n"
                    + tutorial_hint(
                        "Теперь нужно дождаться покупателя. Для первого заказа промотай ожидание."
                    )
                )
                await present(target, text, _skip_markup())
                return
            if not state or not state["active"] or state["stage"] != STAGE_PRICE:
                return await original_listing(target, db, game, player_id, listing_id)
            row = ui_commerce._listing_context(db, player_id, listing_id)
            if not row:
                return
            trust = game.customer_metrics(player_id)
            unit_price = float(row["price"]) / max(1, int(row["pack_size"]))
            delta = (unit_price / float(row["base_market_price"]) - 1.0) * 100.0
            allowance = float(trust["premium_allowance"]) * 100.0
            text = (
                f"<b>{clean(row['title'])} · ×{row['pack_size']}</b>\n\n"
                f"Цена: <b>{money(row['price'])}</b> · рынок ~{money(row['base_market_price'] * row['pack_size'])}\n"
                f"Наценка: {delta:+.0f}%\n\n"
                + tutorial_hint(
                    f"При текущем доверии около +{allowance:.0f}% к рынку переносится спокойнее. "
                    "Измени цену на −5% или +5% и посмотри, как это будет работать дальше."
                )
            )
            await present(target, text, InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="−5%", callback_data=f"sales:price:{listing_id}:-5"),
                    InlineKeyboardButton(text="+5%", callback_data=f"sales:price:{listing_id}:5"),
                ],
                [InlineKeyboardButton(text="← Назад", callback_data=f"sales:product:{row['product_id']}")],
            ]))

        render_listing._nightshift_tutorial = True
        ui_commerce.render_listing = render_listing


def apply_tutorial_updates() -> None:
    _install_new_player_setup()
    _install_tutorial_offer_filter()
    _install_first_purchase_protection()
    _install_handoff_progress()
    _install_price_progress()
    _install_random_event_protection()
    _install_dispute_progress()
    _install_handoff_tutorial_flag()
    _install_tutorial_renderers()


def build_tutorial_router(db, game, simulation_engine) -> Router:
    router = Router(name="guided-first-cycle")

    @router.callback_query(F.data == "tutorial:skip")
    async def skip(callback: CallbackQuery) -> None:
        result = skip_tutorial_wait(game, simulation_engine, callback.from_user.id)
        await callback.answer(result[:180])
        state = tutorial_state(db, callback.from_user.id)
        if not state or not state["active"]:
            return
        if state["stage"] == STAGE_HANDOFF:
            batch_id = int(state["data"].get("batch_id", 0) or 0)
            if batch_id:
                await ui_staff_handlers.render_batch(callback.message, game, callback.from_user.id, batch_id)
                return
        if state["stage"] == STAGE_PRICE:
            await ui_commerce.render_storefront_root(
                callback.message, db, game, simulation_engine, callback.from_user.id
            )
            return
        await ui_navigation.render_home(
            callback.message,
            db,
            game,
            simulation_engine,
            frozenset(),
            callback.from_user.id,
        )

    @router.callback_query(F.data == "tutorial:continue")
    async def continue_tutorial(callback: CallbackQuery) -> None:
        created = create_tutorial_dispute(game, simulation_engine, callback.from_user.id)
        await callback.answer("Следующий этап" if created else "Этап уже пройден")
        await ui_navigation.render_home(
            callback.message,
            db,
            game,
            simulation_engine,
            frozenset(),
            callback.from_user.id,
        )

    @router.callback_query(F.data == "tutorial:open_dispute")
    async def open_dispute(callback: CallbackQuery) -> None:
        await callback.answer()
        state = tutorial_state(db, callback.from_user.id)
        if not state or state["stage"] != STAGE_DISPUTE:
            await ui_navigation.render_home(
                callback.message, db, game, simulation_engine, frozenset(), callback.from_user.id
            )
            return
        from .ui_disputes import render_dispute

        dispute_id = int(state["data"].get("dispute_id", 0) or 0)
        if not dispute_id or not await render_dispute(
            callback.message, game, callback.from_user.id, dispute_id
        ):
            await ui_navigation.render_home(
                callback.message, db, game, simulation_engine, frozenset(), callback.from_user.id
            )

    @router.callback_query(F.data == "tutorial:finish")
    async def finish(callback: CallbackQuery) -> None:
        _finish_tutorial(db, callback.from_user.id)
        await callback.answer("Обучение завершено")
        await ui_navigation.render_home(
            callback.message,
            db,
            game,
            simulation_engine,
            frozenset(),
            callback.from_user.id,
        )

    return router
