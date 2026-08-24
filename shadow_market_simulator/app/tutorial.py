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
    workflow,
)
from .simulation import iso, utcnow
from .ui_common import clean, money, present, rating, tutorial_hint


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

WAIT_STAGES = {
    STAGE_PICKUP_WAIT,
    STAGE_HANDOFF_WAIT,
    STAGE_PREP_WAIT,
    STAGE_SALE_WAIT,
}


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


def _instruction(state: dict) -> str:
    stage = state["stage"]
    data = state["data"]
    if stage == STAGE_PROCUREMENT:
        return (
            "Склад пуст. Нажми 📦 Товар и выбери, что купить. Сравни цену, качество и надёжность поставки. "
            "В дальнейшем любая закупка может оказаться неудачной."
        )
    if stage == STAGE_PICKUP_WAIT:
        return (
            "Складмен забирает товар. Обычно это занимает игровое время. Можешь заниматься другими делами, "
            "дождаться окончания или нажать ⏩ Пропустить ожидание."
        )
    if stage == STAGE_HANDOFF:
        return (
            "Вернись в меню, нажми 📦 Товар → 📦 Склад, открой партию и выбери закладчика, которому передашь стафф."
        )
    if stage == STAGE_HANDOFF_WAIT:
        return (
            "Складмен передаёт товар закладчику. Можешь продолжать заниматься магазином, дождаться окончания "
            "или нажать ⏩ Пропустить ожидание."
        )
    if stage == STAGE_PREP_WAIT:
        return (
            "Закладчик готовит товар к витрине. Можешь дождаться окончания или нажать ⏩ Пропустить ожидание."
        )
    if stage == STAGE_PRICE:
        return (
            "Вернись в меню, нажми 🏷 Витрина, выбери товар, затем выбери фасовку и измени цену. "
            "Цена влияет на спрос и ожидания покупателей."
        )
    if stage == STAGE_SALE_WAIT:
        return (
            "Теперь дождись первой продажи. Можешь продолжать играть как обычно или нажать ⏩ Пропустить ожидание."
        )
    if stage == STAGE_REVIEW:
        order_id = data.get("order_id")
        suffix = f" #{order_id}" if order_id else ""
        return (
            f"Первый заказ{suffix} прошёл. Выручка ещё не равна чистой прибыли: есть себестоимость и выплаты команде. "
            "После продаж появляются оценки товара и закладчика. Нажми «Продолжить обучение», чтобы познакомиться с диспутами."
        )
    if stage == STAGE_DISPUTE:
        return (
            "Открой 📨 Входящие и разбери диспут. Можно запросить пояснение сотрудника, изучить контекст и решить, "
            "компенсировать заказ или отказать."
        )
    if stage == STAGE_TEAM:
        return (
            "Теперь посмотри 👥 Команду, найм и условия оплаты, а также 🏷 Фасовки, 📊 Аналитику и 📨 Входящие. "
            "Все обычные разделы доступны. Когда закончишь — заверши обучение."
        )
    return "Обучение завершено."


def _append_tutorial_action(markup: InlineKeyboardMarkup, state: dict) -> InlineKeyboardMarkup:
    rows = [list(row) for row in markup.inline_keyboard]
    stage = state["stage"]
    extra: list[InlineKeyboardButton] = []
    if stage in WAIT_STAGES:
        extra.append(
            InlineKeyboardButton(
                text="⏩ Пропустить ожидание",
                callback_data="tutorial:skip",
            )
        )
    elif stage == STAGE_REVIEW:
        extra.append(
            InlineKeyboardButton(
                text="Продолжить обучение",
                callback_data="tutorial:continue",
            )
        )
    elif stage == STAGE_TEAM:
        extra.append(
            InlineKeyboardButton(
                text="✅ Завершить обучение",
                callback_data="tutorial:finish",
            )
        )
    if extra:
        rows.insert(0, extra)
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def sync_tutorial_state(db, player_id: int) -> dict | None:
    state = tutorial_state(db, player_id)
    if not state or not state["active"]:
        return state

    stage = state["stage"]
    data = state["data"]
    next_stage: str | None = None
    next_data: dict = {}

    with db.connect() as conn:
        if stage == STAGE_PICKUP_WAIT:
            batch = conn.execute(
                "SELECT status FROM batches WHERE id=? AND player_id=?",
                (int(data.get("batch_id", 0)), player_id),
            ).fetchone()
            if batch and batch["status"] == "warehouse":
                next_stage = STAGE_HANDOFF

        elif stage in {STAGE_HANDOFF_WAIT, STAGE_PREP_WAIT}:
            allocation = conn.execute(
                "SELECT status, product_id FROM retail_allocations WHERE id=? AND player_id=?",
                (int(data.get("allocation_id", 0)), player_id),
            ).fetchone()
            if allocation:
                if allocation["status"] == "published":
                    next_stage = STAGE_PRICE
                    next_data["product_id"] = int(allocation["product_id"])
                elif stage == STAGE_HANDOFF_WAIT and allocation["status"] == "preparing":
                    next_stage = STAGE_PREP_WAIT

        elif stage == STAGE_SALE_WAIT:
            floor = int(data.get("order_floor", 0) or 0)
            order = conn.execute(
                """SELECT id, product_id FROM orders
                   WHERE player_id=? AND id>?
                   ORDER BY id LIMIT 1""",
                (player_id, floor),
            ).fetchone()
            if order:
                next_stage = STAGE_REVIEW
                next_data.update(
                    order_id=int(order["id"]),
                    product_id=int(order["product_id"]),
                )

    if next_stage:
        _set_stage(db, player_id, next_stage, **next_data)
        return tutorial_state(db, player_id)
    return state


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
            conn.execute("DELETE FROM batches WHERE player_id=?", (player_id,))
            conn.execute(
                "UPDATE shops SET balance=?, reserve_target=? WHERE player_id=?",
                (STARTING_CAPITAL, STARTING_RESERVE, player_id),
            )
            conn.execute(
                """UPDATE ledger
                   SET amount=?, note='Стартовый капитал'
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


def _install_first_purchase_protection() -> None:
    original = procurement_market.ProcurementMarketGameService.buy_offer_for_employee
    if getattr(original, "_nightshift_tutorial", False):
        return

    def buy_offer_for_employee(
        self,
        player_id: int,
        offer_id: int,
        employee_id: int,
    ) -> str:
        state = tutorial_state(self.db, player_id)
        if not state or not state["active"] or state["stage"] != STAGE_PROCUREMENT:
            return original(self, player_id, offer_id, employee_id)

        with self.db.connect() as conn:
            offer = conn.execute(
                """SELECT product_id, offer_reliability
                   FROM supplier_offers
                   WHERE id=? AND player_id=? AND status='open'""",
                (offer_id, player_id),
            ).fetchone()
            if not offer:
                return original(self, player_id, offer_id, employee_id)
            old_reliability = offer["offer_reliability"]
            conn.execute(
                "UPDATE supplier_offers SET offer_reliability=1.0 WHERE id=?",
                (offer_id,),
            )

        try:
            result = original(self, player_id, offer_id, employee_id)
        finally:
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE supplier_offers SET offer_reliability=? WHERE id=?",
                    (old_reliability, offer_id),
                )

        if not result.startswith("✅ Куплено"):
            return result

        with self.db.connect() as conn:
            batch = conn.execute(
                """SELECT id, product_id FROM batches
                   WHERE player_id=? AND responsible_employee_id=? AND status='receiving'
                   ORDER BY id DESC LIMIT 1""",
                (player_id, employee_id),
            ).fetchone()
        if batch:
            _set_stage(
                self.db,
                player_id,
                STAGE_PICKUP_WAIT,
                batch_id=int(batch["id"]),
                product_id=int(batch["product_id"]),
                warehouse_employee_id=employee_id,
            )
            result += "\n\n" + tutorial_hint(
                "Складмен забирает товар. Обычно это занимает время. Можешь продолжать играть или вернуться в меню и нажать ⏩ Пропустить ожидание."
            )
        return result

    buy_offer_for_employee._nightshift_tutorial = True
    procurement_market.ProcurementMarketGameService.buy_offer_for_employee = buy_offer_for_employee


def _install_handoff_progress() -> None:
    original = workflow.WorkflowGameService.allocate_to_retail
    if getattr(original, "_nightshift_tutorial", False):
        return

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
        state = sync_tutorial_state(self.db, player_id)
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
            result += "\n\n" + tutorial_hint(
                "Передача занимает время. Можешь продолжать играть или вернуться в меню и нажать ⏩ Пропустить ожидание."
            )
        return result

    allocate_to_retail._nightshift_tutorial = True
    workflow.WorkflowGameService.allocate_to_retail = allocate_to_retail


def _install_price_progress() -> None:
    from . import game as game_module

    original = game_module.GameService.change_listing_price
    if getattr(original, "_nightshift_tutorial", False):
        return

    def change_listing_price(
        self,
        player_id: int,
        listing_id: int,
        percent: int,
    ) -> str:
        result = original(self, player_id, listing_id, percent)
        state = sync_tutorial_state(self.db, player_id)
        if (
            state
            and state["active"]
            and state["stage"] == STAGE_PRICE
            and result.startswith("Цена изменена")
        ):
            with self.db.connect() as conn:
                floor = int(
                    conn.execute(
                        "SELECT COALESCE(MAX(id),0) FROM orders WHERE player_id=?",
                        (player_id,),
                    ).fetchone()[0]
                )
            _set_stage(
                self.db,
                player_id,
                STAGE_SALE_WAIT,
                listing_id=listing_id,
                order_floor=floor,
            )
        return result

    change_listing_price._nightshift_tutorial = True
    game_module.GameService.change_listing_price = change_listing_price


def _install_random_event_protection() -> None:
    original_events = courier_core.CourierCoreSimulationEngine._simulate_management_events
    if not getattr(original_events, "_nightshift_tutorial", False):

        def protected_events(
            self,
            conn,
            player_id: int,
            sim_hours: float,
            now,
        ) -> int:
            if tutorial_active(self.db, player_id):
                self._ensure_courier_profiles_conn(conn, player_id)
                self._recover_courier_state_conn(conn, player_id, sim_hours)
                return 0
            return original_events(self, conn, player_id, sim_hours, now)

        protected_events._nightshift_tutorial = True
        courier_core.CourierCoreSimulationEngine._simulate_management_events = protected_events

    original_dispute = courier_core.CourierCoreSimulationEngine._dispute_probability
    if not getattr(original_dispute, "_nightshift_tutorial", False):

        def protected_dispute(
            self,
            client,
            employee,
            quality: float,
            modifier: float,
        ) -> float:
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

    def resolve_dispute_with_source(
        self,
        player_id: int,
        dispute_id: int,
        decision: str,
        source: str,
    ) -> str:
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
        state = sync_tutorial_state(self.db, player_id)
        if state and state["active"] and state["stage"] == STAGE_HANDOFF:
            return True
        return original(self, player_id)

    needs_first_handoff_tutorial._nightshift_tutorial = True
    workflow.WorkflowGameService.needs_first_handoff_tutorial = needs_first_handoff_tutorial


def _install_soft_guidance_renderers() -> None:
    original_home = ui_navigation.render_home
    if not getattr(original_home, "_nightshift_tutorial_soft", False):

        async def render_home(
            target,
            db,
            game,
            simulation_engine,
            admin_ids,
            player_id: int,
            *,
            edit: bool = True,
        ) -> None:
            text, opened, urgent = ui_navigation._home_snapshot(
                db,
                game,
                simulation_engine,
                player_id,
            )
            state = sync_tutorial_state(db, player_id)
            markup = ui_navigation.home_keyboard(
                opened,
                urgent,
                is_admin=player_id in admin_ids,
            )
            if state and state["active"]:
                text += "\n\n" + tutorial_hint(_instruction(state))
                markup = _append_tutorial_action(markup, state)
            await present(target, text, markup, edit=edit)

        render_home._nightshift_tutorial_soft = True
        ui_navigation.render_home = render_home

    original_product_root = ui_commerce.render_product_root
    if not getattr(original_product_root, "_nightshift_tutorial_soft", False):

        async def render_product_root(
            target,
            db,
            game,
            player_id: int,
            *,
            flash: str | None = None,
        ) -> None:
            state = sync_tutorial_state(db, player_id)
            if not state or not state["active"] or state["stage"] != STAGE_PROCUREMENT:
                await original_product_root(target, db, game, player_id, flash=flash)
                return
            products = game.procurement_products(player_id)
            body = (
                f"<b>📦 Товар</b>\n\nСвободно: <b>{money(_free_cash(game, player_id))}</b>\n\n"
                + tutorial_hint("Выбери товар для первой закупки.")
            )
            if flash:
                body = f"{flash}\n\n{body}"
            await present(
                target,
                body,
                ui_commerce._procurement_products_keyboard(db, player_id, products),
            )

        render_product_root._nightshift_tutorial_soft = True
        ui_commerce.render_product_root = render_product_root

    original_procurement_product = ui_commerce.render_procurement_product
    if not getattr(original_procurement_product, "_nightshift_tutorial_soft", False):

        async def render_procurement_product(
            target,
            game,
            player_id: int,
            product_id: int,
            *,
            flash: str | None = None,
        ) -> None:
            state = sync_tutorial_state(game.db, player_id)
            if not state or not state["active"] or state["stage"] != STAGE_PROCUREMENT:
                await original_procurement_product(
                    target,
                    game,
                    player_id,
                    product_id,
                    flash=flash,
                )
                return
            offers = game.offers(player_id, product_id)
            with game.db.connect() as conn:
                product = conn.execute(
                    "SELECT title FROM products WHERE id=? AND active=1",
                    (product_id,),
                ).fetchone()
            if not product:
                await render_product_root(target, game.db, game, player_id, flash=flash)
                return
            body = (
                f"<b>📦 {clean(product['title'])}</b>\n\n"
                f"Доступно: {len(offers)} предложений.\n\n"
                + tutorial_hint("Выбери предложение.")
            )
            if flash:
                body = f"{flash}\n\n{body}"
            await present(target, body, ui_commerce._offers_keyboard(product_id, offers))

        render_procurement_product._nightshift_tutorial_soft = True
        ui_commerce.render_procurement_product = render_procurement_product

    original_storefront = ui_commerce.render_storefront_root
    if not getattr(original_storefront, "_nightshift_tutorial_soft", False):

        async def render_storefront_root(
            target,
            db,
            game,
            simulation_engine,
            player_id: int,
        ) -> None:
            state = sync_tutorial_state(db, player_id)
            if not state or not state["active"] or state["stage"] not in {STAGE_PRICE, STAGE_SALE_WAIT}:
                await original_storefront(
                    target,
                    db,
                    game,
                    simulation_engine,
                    player_id,
                )
                return
            simulation_engine.advance(player_id)
            state = sync_tutorial_state(db, player_id)
            rows = ui_commerce._sales_products(db, player_id)
            trust = game.customer_metrics(player_id)
            text = (
                "<b>🏷 Витрина</b>\n\n"
                f"Доверие: {trust['trust_score']:.0f}/100\n"
                f"Наценка до ~+{trust['premium_allowance'] * 100:.0f}% обычно не снижает спрос."
            )
            if state and state["active"] and state["stage"] == STAGE_PRICE:
                text += "\n\n" + tutorial_hint("Выбери товар.")
            elif state and state["active"] and state["stage"] == STAGE_SALE_WAIT:
                text += "\n\n" + tutorial_hint(
                    "Теперь дождись первой продажи. Можешь продолжать играть как обычно или вернуться в меню и нажать ⏩ Пропустить ожидание."
                )
            markup = ui_commerce._sales_root_keyboard(rows)
            if state and state["active"]:
                markup = _append_tutorial_action(markup, state)
            await present(target, text, markup)

        render_storefront_root._nightshift_tutorial_soft = True
        ui_commerce.render_storefront_root = render_storefront_root

    original_sales_product = ui_commerce.render_sales_product
    if not getattr(original_sales_product, "_nightshift_tutorial_soft", False):

        async def render_sales_product(
            target,
            db,
            player_id: int,
            product_id: int,
        ) -> None:
            state = sync_tutorial_state(db, player_id)
            if not state or not state["active"] or state["stage"] != STAGE_PRICE:
                await original_sales_product(target, db, player_id, product_id)
                return
            product, listings, published, avg, n = ui_commerce._product_listings(
                db,
                player_id,
                product_id,
            )
            if not product:
                return
            rows = [
                [
                    InlineKeyboardButton(
                        text=f"×{listing['pack_size']} · {money(listing['price'])} · доступно {int(listing['positions'])}",
                        callback_data=f"sales:listing:{listing['id']}",
                    )
                ]
                for listing in listings
            ]
            rows.append(
                [
                    InlineKeyboardButton(
                        text="← Витрина",
                        callback_data="menu:storefront",
                    )
                ]
            )
            text = (
                f"<b>{clean(product['title'])}</b>\n\n"
                f"{published} ед. готовы к продаже · оценка {rating(avg, n)}\n\n"
                + tutorial_hint("Выбери фасовку.")
            )
            await present(
                target,
                text,
                InlineKeyboardMarkup(inline_keyboard=rows),
            )

        render_sales_product._nightshift_tutorial_soft = True
        ui_commerce.render_sales_product = render_sales_product

    original_listing = ui_commerce.render_listing
    if not getattr(original_listing, "_nightshift_tutorial_soft", False):

        async def render_listing(
            target,
            db,
            game,
            player_id: int,
            listing_id: int,
        ) -> None:
            state = sync_tutorial_state(db, player_id)
            if not state or not state["active"] or state["stage"] not in {STAGE_PRICE, STAGE_SALE_WAIT}:
                await original_listing(target, db, game, player_id, listing_id)
                return
            row = ui_commerce._listing_context(db, player_id, listing_id)
            if not row:
                return
            trust = game.customer_metrics(player_id)
            unit_price = float(row["price"]) / max(1, int(row["pack_size"]))
            delta = (unit_price / float(row["base_market_price"]) - 1.0) * 100.0
            allowance = float(trust["premium_allowance"]) * 100.0
            status = "нормально" if delta <= allowance + 0.01 else "спрос будет снижаться"
            text = (
                f"<b>{clean(row['title'])} · ×{row['pack_size']}</b>\n\n"
                f"Цена: <b>{money(row['price'])}</b> · рынок ~{money(row['base_market_price'] * row['pack_size'])}\n"
                f"Наценка: {delta:+.0f}%\n\n"
                f"При текущем доверии до ~+{allowance:.0f}% переносится нормально · <b>{status}</b>.\n\n"
                f"Доступно: {int(row['positions'])}"
            )
            if state["stage"] == STAGE_PRICE:
                text += "\n\n" + tutorial_hint("Измени цену на −5% или +5%.")
            else:
                text += "\n\n" + tutorial_hint(
                    "Цена выставлена. Теперь дождись первой продажи или нажми ⏩ Пропустить ожидание."
                )
            rows = [
                [
                    InlineKeyboardButton(
                        text="−5%",
                        callback_data=f"sales:price:{listing_id}:-5",
                    ),
                    InlineKeyboardButton(
                        text="+5%",
                        callback_data=f"sales:price:{listing_id}:5",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=f"← {str(row['title'])[:18]}",
                        callback_data=f"sales:product:{row['product_id']}",
                    )
                ],
            ]
            markup = InlineKeyboardMarkup(inline_keyboard=rows)
            markup = _append_tutorial_action(markup, state)
            await present(target, text, markup)

        render_listing._nightshift_tutorial_soft = True
        ui_commerce.render_listing = render_listing


def skip_tutorial_wait(game, simulation_engine, player_id: int) -> str:
    state = sync_tutorial_state(game.db, player_id)
    if not state or not state["active"]:
        return "Обучение уже завершено."

    if state["stage"] in {
        STAGE_PICKUP_WAIT,
        STAGE_HANDOFF_WAIT,
        STAGE_PREP_WAIT,
    }:
        now = utcnow()
        with game.db.connect() as conn:
            task = _active_task_for_stage(conn, player_id, state)
            if task:
                conn.execute(
                    "UPDATE employee_tasks SET completes_at=? WHERE id=?",
                    (iso(now - timedelta(seconds=1)), int(task["id"])),
                )
                simulation_engine._process_tasks(conn, player_id, now)
        updated = sync_tutorial_state(game.db, player_id)
        if updated and updated["stage"] != state["stage"]:
            return "Ожидание пропущено."
        return "Задача ещё не готова к следующему этапу."

    if state["stage"] == STAGE_SALE_WAIT:
        listing_id = int(state["data"].get("listing_id", 0) or 0)
        with game.db.connect() as conn:
            listing = None
            if listing_id:
                listing = conn.execute(
                    """SELECT l.*, p.base_market_price, p.base_demand, p.complaint_modifier
                       FROM listings l JOIN products p ON p.id=l.product_id
                       WHERE l.id=? AND l.player_id=? AND l.active=1""",
                    (listing_id, player_id),
                ).fetchone()
            if not listing:
                listing = conn.execute(
                    """SELECT l.*, p.base_market_price, p.base_demand, p.complaint_modifier
                       FROM listings l JOIN products p ON p.id=l.product_id
                       WHERE l.player_id=? AND l.active=1
                         AND EXISTS (
                             SELECT 1
                             FROM retail_positions rp
                             JOIN employees e ON e.id=rp.employee_id
                             WHERE rp.player_id=l.player_id
                               AND rp.product_id=l.product_id
                               AND rp.pack_size=l.pack_size
                               AND rp.position_count>0
                               AND e.active=1 AND e.available=1 AND e.role='courier'
                         )
                       ORDER BY l.id LIMIT 1""",
                    (player_id,),
                ).fetchone()
            if not listing:
                return "На витрине пока нет товара для продажи."
            before = int(
                conn.execute(
                    "SELECT COALESCE(MAX(id),0) FROM orders WHERE player_id=?",
                    (player_id,),
                ).fetchone()[0]
            )
            result = simulation_engine._create_retail_order(
                conn,
                player_id,
                listing,
                utcnow(),
            )
            if result is None:
                return "Пока не удалось создать первый заказ."
            order = conn.execute(
                """SELECT id, product_id FROM orders
                   WHERE player_id=? AND id>?
                   ORDER BY id DESC LIMIT 1""",
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
            return "Первая продажа завершена."

    return "Сейчас нечего проматывать."


def create_tutorial_dispute(
    game,
    simulation_engine,
    player_id: int,
) -> tuple[int, int] | None:
    state = sync_tutorial_state(game.db, player_id)
    if not state or not state["active"] or state["stage"] != STAGE_REVIEW:
        return None
    order_id = int(state["data"].get("order_id", 0) or 0)
    if not order_id:
        return None

    now = utcnow()
    with game.db.connect() as conn:
        existing = conn.execute(
            """SELECT id FROM disputes
               WHERE player_id=? AND order_id=? AND status='open'
               LIMIT 1""",
            (player_id, order_id),
        ).fetchone()
        if existing:
            dispute_id = int(existing["id"])
            inbox = conn.execute(
                """SELECT id FROM inbox
                   WHERE player_id=? AND status='open' AND kind='dispute'
                     AND json_extract(payload_json, '$.dispute_id')=?
                   ORDER BY id DESC LIMIT 1""",
                (player_id, dispute_id),
            ).fetchone()
            inbox_id = int(inbox["id"]) if inbox else 0
        else:
            order = conn.execute(
                """SELECT o.*, c.alias client_alias
                   FROM orders o
                   JOIN clients c ON c.id=o.client_id
                   WHERE o.id=? AND o.player_id=?""",
                (order_id, player_id),
            ).fetchone()
            if not order:
                return None

            message = (
                "Описание оказалось недостаточно понятным. Не могу уверенно найти заказ и хочу решить вопрос."
            )
            evidence = {
                "description_present": True,
                "extra_material_present": False,
                "client_tone": "спокойный",
                "order_value": int(order["revenue"]),
                "tutorial": True,
            }
            deadline = now + timedelta(
                hours=2 / max(0.1, simulation_engine.effective_speed(player_id))
            )
            cur = conn.execute(
                """INSERT INTO disputes(
                       player_id, order_id, true_cause, message, evidence_json, deadline_at
                   ) VALUES (?, ?, 'DESCRIPTION_ERROR', ?, ?, ?)""",
                (
                    player_id,
                    order_id,
                    message,
                    json.dumps(evidence, ensure_ascii=False),
                    iso(deadline),
                ),
            )
            dispute_id = int(cur.lastrowid)
            conn.execute(
                "UPDATE orders SET status='disputed' WHERE id=?",
                (order_id,),
            )
            conn.execute(
                "UPDATE employees SET disputes=disputes+1 WHERE id=?",
                (order["employee_id"],),
            )
            conn.execute(
                "UPDATE clients SET disputes_total=disputes_total+1 WHERE id=?",
                (order["client_id"],),
            )
            inbox_cur = conn.execute(
                """INSERT INTO inbox(
                       player_id, kind, priority, title, body,
                       payload_json, expires_at, notified_at
                   ) VALUES (?, 'dispute', 'important', ?, ?, ?, ?, ?)""",
                (
                    player_id,
                    f"Диспут #{dispute_id}",
                    f"Клиент {order['client_alias']}: {message}",
                    json.dumps(
                        {"dispute_id": dispute_id, "tutorial": True},
                        ensure_ascii=False,
                    ),
                    iso(deadline),
                    iso(now),
                ),
            )
            inbox_id = int(inbox_cur.lastrowid)

    _set_stage(
        game.db,
        player_id,
        STAGE_DISPUTE,
        dispute_id=dispute_id,
        inbox_id=inbox_id,
    )
    return dispute_id, inbox_id


def apply_tutorial_updates() -> None:
    _install_new_player_setup()
    _install_first_purchase_protection()
    _install_handoff_progress()
    _install_price_progress()
    _install_random_event_protection()
    _install_dispute_progress()
    _install_handoff_tutorial_flag()
    _install_soft_guidance_renderers()


def build_tutorial_router(db, game, simulation_engine) -> Router:
    router = Router(name="guided-first-cycle")

    @router.callback_query(F.data == "tutorial:skip")
    async def skip(callback: CallbackQuery) -> None:
        result = skip_tutorial_wait(
            game,
            simulation_engine,
            callback.from_user.id,
        )
        await callback.answer(result[:180])
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
        created = create_tutorial_dispute(
            game,
            simulation_engine,
            callback.from_user.id,
        )
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
                callback.message,
                db,
                game,
                simulation_engine,
                frozenset(),
                callback.from_user.id,
            )
            return
        from .ui_disputes import render_dispute

        dispute_id = int(state["data"].get("dispute_id", 0) or 0)
        if not dispute_id or not await render_dispute(
            callback.message,
            game,
            callback.from_user.id,
            dispute_id,
        ):
            await ui_navigation.render_home(
                callback.message,
                db,
                game,
                simulation_engine,
                frozenset(),
                callback.from_user.id,
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
