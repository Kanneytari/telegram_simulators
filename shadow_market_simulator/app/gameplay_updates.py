from __future__ import annotations

from datetime import timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import procurement_market, simulation, ui_commerce, ui_staff_handlers, workflow
from .ui_common import clean, money, nav_row, notice, present, tutorial_hint


UPDATED_PRODUCTS = (
    (1, "AMPHETAMINE", "Amphetamine", 6000, 18.0, 0.95),
    (2, "MDMA", "MDMA", 8000, 10.0, 1.10),
    (3, "COCAINE", "Cocaine", 11000, 6.0, 0.90),
    (4, "MEPHEDRONE", "Mephedrone", 7000, 15.0, 1.00),
    (6, "LSD", "LSD", 9000, 7.0, 0.85),
    (7, "HASH", "Hash", 5000, 14.0, 0.90),
    (8, "WEED", "Weed", 4000, 20.0, 0.85),
)

PROCUREMENT_BATCH_SIZES = (50, 100, 250, 500, 1000)
VOLUME_DISCOUNTS = {
    50: 1.00,
    100: 0.93,
    250: 0.84,
    500: 0.76,
    1000: 0.68,
}


def _install_catalog_update() -> None:
    simulation.PRODUCTS = UPDATED_PRODUCTS
    original = simulation.SimulationEngine.seed_catalog
    if getattr(original, "_nightshift_updated", False):
        return

    def seed_catalog(self) -> None:
        original(self)
        with self.db.connect() as conn:
            conn.execute("UPDATE products SET active=0 WHERE code='KETAMINE'")
            conn.executemany(
                """INSERT INTO products(
                       id, code, title, base_market_price, base_demand,
                       complaint_modifier, active
                   ) VALUES (?, ?, ?, ?, ?, ?, 1)
                   ON CONFLICT(id) DO UPDATE SET
                       code=excluded.code,
                       title=excluded.title,
                       base_market_price=excluded.base_market_price,
                       base_demand=excluded.base_demand,
                       complaint_modifier=excluded.complaint_modifier,
                       active=1""",
                UPDATED_PRODUCTS,
            )
            ketamine = conn.execute(
                "SELECT id FROM products WHERE code='KETAMINE'"
            ).fetchone()
            if ketamine:
                conn.execute(
                    """UPDATE supplier_offers
                       SET status='rotated'
                       WHERE product_id=? AND status='open'""",
                    (int(ketamine["id"]),),
                )

            players = [
                int(row["player_id"])
                for row in conn.execute("SELECT player_id FROM shops").fetchall()
            ]
            for player_id in players:
                for product_id, _, _, base_price, _, _ in UPDATED_PRODUCTS:
                    for pack_size, multiplier in ((1, 1.05), (2, 1.95), (5, 4.55)):
                        price = int(round(base_price * multiplier / 100.0) * 100)
                        conn.execute(
                            """INSERT OR IGNORE INTO listings(
                                   player_id, product_id, pack_size, price
                               ) VALUES (?, ?, ?, ?)""",
                            (player_id, product_id, pack_size, price),
                        )

    seed_catalog._nightshift_updated = True
    simulation.SimulationEngine.seed_catalog = seed_catalog


def _seed_market_conn(self, conn, player_id: int, now) -> None:
    products = [
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM products WHERE active=1 ORDER BY id"
        ).fetchall()
    ]
    for product_id in products:
        for _ in range(5):
            _create_market_offer_conn(
                self,
                conn,
                player_id,
                product_id,
                self.rng.choice(PROCUREMENT_BATCH_SIZES),
                now,
            )


def _ensure_market_bounds_conn(self, conn, player_id: int, now) -> None:
    placeholders = ",".join("?" for _ in PROCUREMENT_BATCH_SIZES)
    conn.execute(
        f"""UPDATE supplier_offers
            SET status='rotated'
            WHERE player_id=? AND status='open'
              AND quantity NOT IN ({placeholders})""",
        (player_id, *PROCUREMENT_BATCH_SIZES),
    )
    conn.execute(
        """UPDATE supplier_offers
           SET status='rotated'
           WHERE player_id=? AND status='open'
             AND product_id NOT IN (SELECT id FROM products WHERE active=1)""",
        (player_id,),
    )

    products = [
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM products WHERE active=1 ORDER BY id"
        ).fetchall()
    ]
    for product_id in products:
        rows = list(
            conn.execute(
                """SELECT id FROM supplier_offers
                   WHERE player_id=? AND product_id=? AND status='open'
                   ORDER BY id""",
                (player_id, product_id),
            ).fetchall()
        )
        if len(rows) > 5:
            for row in rows[5:]:
                conn.execute(
                    "UPDATE supplier_offers SET status='rotated' WHERE id=?",
                    (int(row["id"]),),
                )
            rows = rows[:5]
        while len(rows) < 5:
            offer_id = _create_market_offer_conn(
                self,
                conn,
                player_id,
                product_id,
                self.rng.choice(PROCUREMENT_BATCH_SIZES),
                now,
            )
            rows.append({"id": offer_id})


def _rotate_market_once_conn(self, conn, player_id: int, now) -> int:
    rows = list(
        conn.execute(
            """SELECT o.id, o.product_id
               FROM supplier_offers o
               JOIN products p ON p.id=o.product_id
               WHERE o.player_id=? AND o.status='open' AND p.active=1""",
            (player_id,),
        ).fetchall()
    )
    if not rows:
        return 0

    count = min(len(rows), self.rng.randint(1, 2))
    selected = self.rng.sample(rows, k=count)
    for row in selected:
        conn.execute(
            "UPDATE supplier_offers SET status='rotated' WHERE id=?",
            (int(row["id"]),),
        )
        _create_market_offer_conn(
            self,
            conn,
            player_id,
            int(row["product_id"]),
            self.rng.choice(PROCUREMENT_BATCH_SIZES),
            now,
        )
    return count * 2


def _create_market_offer_conn(
    self,
    conn,
    player_id: int,
    product_id: int,
    quantity: int,
    now,
) -> int:
    product = conn.execute(
        "SELECT * FROM products WHERE id=? AND active=1",
        (product_id,),
    ).fetchone()
    suppliers = conn.execute("SELECT * FROM suppliers ORDER BY id").fetchall()
    if not product or not suppliers:
        raise ValueError("Product or suppliers are unavailable")

    supplier = self.rng.choice(list(suppliers))
    volume_discount = VOLUME_DISCOUNTS[int(quantity)]
    typical = float(product["base_market_price"]) * 0.56 * volume_discount
    supplier_baseline = typical * float(supplier["price_modifier"])

    roll = self.rng.random()
    if roll < 0.81:
        profile = "normal"
        price_factor = procurement_market.clamp(
            self.rng.gauss(1.0, 0.075), 0.82, 1.18
        )
        quality_mean = float(supplier["quality_mean"]) + self.rng.gauss(0.0, 3.5)
        quality_sigma = float(supplier["quality_sigma"]) * self.rng.uniform(0.75, 1.10)
        reliability = float(supplier["reliability"]) + self.rng.uniform(-0.025, 0.025)
    elif roll < 0.87:
        profile = "bargain"
        price_factor = self.rng.uniform(0.62, 0.78)
        quality_mean = max(
            84.0,
            float(supplier["quality_mean"]) + self.rng.uniform(4.0, 10.0),
        )
        quality_sigma = self.rng.uniform(2.5, 5.5)
        reliability = max(
            0.90,
            float(supplier["reliability"]) + self.rng.uniform(0.02, 0.08),
        )
    elif roll < 0.95:
        profile = "dubious"
        price_factor = self.rng.uniform(0.72, 1.28)
        quality_mean = self.rng.uniform(48.0, 69.0)
        quality_sigma = self.rng.uniform(10.0, 18.0)
        reliability = self.rng.uniform(0.55, 0.79)
    else:
        profile = "premium"
        price_factor = self.rng.uniform(1.12, 1.34)
        quality_mean = self.rng.uniform(91.0, 97.0)
        quality_sigma = self.rng.uniform(2.0, 4.0)
        reliability = self.rng.uniform(0.95, 0.995)

    unit_cost = max(
        100,
        int(round(supplier_baseline * price_factor / 50.0) * 50),
    )
    quality_mean = procurement_market.clamp(quality_mean, 40.0, 98.0)
    quality_sigma = procurement_market.clamp(quality_sigma, 2.0, 20.0)
    reliability = procurement_market.clamp(reliability, 0.50, 0.995)
    stability = (
        "стабильно"
        if quality_sigma <= 4.5
        else "обычный разброс"
        if quality_sigma <= 8
        else "сильный разброс"
    )
    quality_hint = f"~{quality_mean:.0f}/100 · {stability}"

    cur = conn.execute(
        """INSERT INTO supplier_offers(
               player_id, supplier_id, product_id, quantity, unit_cost,
               quality_hint, offer_quality_mean, offer_quality_sigma,
               offer_reliability, market_profile, expires_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            player_id,
            supplier["id"],
            product_id,
            quantity,
            unit_cost,
            quality_hint,
            quality_mean,
            quality_sigma,
            reliability,
            profile,
            procurement_market.iso(now + timedelta(days=7)),
        ),
    )
    return int(cur.lastrowid)


def _offer_typical_unit_cost(offer) -> float:
    volume_discount = VOLUME_DISCOUNTS.get(int(offer["quantity"]), 1.0)
    return float(offer["base_market_price"]) * 0.56 * volume_discount


def _install_procurement_update() -> None:
    procurement_market.PROCUREMENT_BATCH_SIZES = PROCUREMENT_BATCH_SIZES
    procurement_market.ProcurementMarketSimulationEngine._seed_market_conn = _seed_market_conn
    procurement_market.ProcurementMarketSimulationEngine._ensure_bounds_conn = _ensure_market_bounds_conn
    procurement_market.ProcurementMarketSimulationEngine._rotate_once_conn = _rotate_market_once_conn
    procurement_market.ProcurementMarketSimulationEngine._create_market_offer_conn = _create_market_offer_conn
    procurement_market.ProcurementMarketGameService.offer_typical_unit_cost = staticmethod(
        _offer_typical_unit_cost
    )


def _procurement_products_keyboard(db, player_id: int, products) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=(
                    f"{product['title']} · 🚚 "
                    f"{ui_commerce._stock_status(db, player_id, int(product['id']))}"
                ),
                callback_data=f"proc:product:{product['id']}",
            )
        ]
        for product in products
    ]
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
                text=f"🚚 Склад · {batch_count}",
                callback_data="team:batches",
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home")]
    )
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
        employees = {
            int(row["id"]): row
            for row in game.employees(player_id)
        }
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
                f" · 🔴 уже не покрыто {money(unsecured)}"
                if unsecured
                else ""
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
    _install_catalog_update()
    _install_procurement_update()
    _install_handoff_update()
    _install_ui_update()
