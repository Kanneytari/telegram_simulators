from __future__ import annotations

from ..tutorial import hooks as tutorial_hooks

from collections import defaultdict
from datetime import timedelta

from .simulation import clamp, iso, parse_dt, utcnow
from .staff_insights import StaffInsightGameService, StaffInsightSimulationEngine


PROCUREMENT_BATCH_SIZES = (50, 100, 250, 500, 1000)
MINIMUM_BATCH_SIZE = 50
ROTATION_MINUTES = 15
VOLUME_DISCOUNTS = {
    50: 1.00,
    100: 0.93,
    250: 0.84,
    500: 0.76,
    1000: 0.68,
}


class ProcurementMarketSimulationEngine(StaffInsightSimulationEngine):
    """Real-time rotating procurement market."""

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        now = utcnow()
        with self.db.connect() as conn:
            state = conn.execute(
                "SELECT 1 FROM procurement_market_state WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if not state:
                conn.execute(
                    """UPDATE supplier_offers SET status='expired'
                       WHERE player_id=? AND status='open'""",
                    (player_id,),
                )
                self._seed_market_conn(conn, player_id, now)
                conn.execute(
                    """INSERT INTO procurement_market_state(
                           player_id, last_rotation_at
                       ) VALUES (?, ?)""",
                    (player_id, iso(now)),
                )
            else:
                self._ensure_bounds_conn(conn, player_id, now)
        return created

    def advance(self, player_id: int, now=None):
        now = now or utcnow()
        result = super().advance(player_id, now)
        self.refresh_procurement_market(player_id, now)
        return result

    def _maybe_refresh_offer(self, conn, player_id: int, now) -> None:
        return None

    def refresh_procurement_market(self, player_id: int, now=None) -> int:
        now = now or utcnow()
        with self.db.connect() as conn:
            state = conn.execute(
                "SELECT last_rotation_at FROM procurement_market_state WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if not state:
                conn.execute(
                    """UPDATE supplier_offers SET status='expired'
                       WHERE player_id=? AND status='open'""",
                    (player_id,),
                )
                self._seed_market_conn(conn, player_id, now)
                conn.execute(
                    """INSERT INTO procurement_market_state(
                           player_id, last_rotation_at
                       ) VALUES (?, ?)""",
                    (player_id, iso(now)),
                )
                return 0

            self._ensure_bounds_conn(conn, player_id, now)
            last = parse_dt(state["last_rotation_at"])
            intervals = int(
                max(0.0, (now - last).total_seconds()) // (ROTATION_MINUTES * 60)
            )
            if intervals <= 0:
                return 0

            cycles = min(intervals, 16)
            changed = 0
            for _ in range(cycles):
                changed += self._rotate_once_conn(conn, player_id, now)
            self._ensure_bounds_conn(conn, player_id, now)
            advanced = last + timedelta(minutes=ROTATION_MINUTES * intervals)
            conn.execute(
                """UPDATE procurement_market_state
                   SET last_rotation_at=? WHERE player_id=?""",
                (iso(advanced), player_id),
            )
            return changed

    def ensure_procurement_bounds(self, player_id: int, now=None) -> None:
        now = now or utcnow()
        with self.db.connect() as conn:
            self._ensure_bounds_conn(conn, player_id, now)

    def _seed_market_conn(self, conn, player_id: int, now) -> None:
        products = [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM products WHERE active=1 ORDER BY id"
            ).fetchall()
        ]
        for product_id in products:
            self._create_market_offer_conn(
                conn,
                player_id,
                product_id,
                MINIMUM_BATCH_SIZE,
                now,
            )
            for _ in range(4):
                self._create_market_offer_conn(
                    conn,
                    player_id,
                    product_id,
                    self.rng.choice(PROCUREMENT_BATCH_SIZES),
                    now,
                )

    def _ensure_bounds_conn(self, conn, player_id: int, now) -> None:
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
                 AND product_id NOT IN (
                     SELECT id FROM products WHERE active=1
                 )""",
            (player_id,),
        )

        products = [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM products WHERE active=1 ORDER BY id"
            ).fetchall()
        ]
        for product_id in products:
            rows = [
                dict(row)
                for row in conn.execute(
                    """SELECT id, quantity FROM supplier_offers
                       WHERE player_id=? AND product_id=? AND status='open'
                       ORDER BY id""",
                    (player_id, product_id),
                ).fetchall()
            ]
            if len(rows) > 5:
                for row in rows[5:]:
                    conn.execute(
                        "UPDATE supplier_offers SET status='rotated' WHERE id=?",
                        (int(row["id"]),),
                    )
                rows = rows[:5]

            while len(rows) < 5:
                quantity = self.rng.choice(PROCUREMENT_BATCH_SIZES)
                offer_id = self._create_market_offer_conn(
                    conn,
                    player_id,
                    product_id,
                    quantity,
                    now,
                )
                rows.append({"id": offer_id, "quantity": quantity})

            if not any(
                int(row["quantity"]) == MINIMUM_BATCH_SIZE for row in rows
            ):
                victim = rows[-1]
                conn.execute(
                    "UPDATE supplier_offers SET status='rotated' WHERE id=?",
                    (int(victim["id"]),),
                )
                offer_id = self._create_market_offer_conn(
                    conn,
                    player_id,
                    product_id,
                    MINIMUM_BATCH_SIZE,
                    now,
                )
                rows[-1] = {"id": offer_id, "quantity": MINIMUM_BATCH_SIZE}

    def _rotate_once_conn(self, conn, player_id: int, now) -> int:
        rows = list(
            conn.execute(
                """SELECT o.id, o.product_id, o.quantity
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
            product_id = int(row["product_id"])
            minimum_count = int(
                conn.execute(
                    """SELECT COUNT(*) FROM supplier_offers
                       WHERE player_id=? AND product_id=? AND status='open'
                         AND quantity=?""",
                    (player_id, product_id, MINIMUM_BATCH_SIZE),
                ).fetchone()[0]
            )
            replacement_quantity = (
                MINIMUM_BATCH_SIZE
                if int(row["quantity"]) == MINIMUM_BATCH_SIZE
                and minimum_count <= 1
                else self.rng.choice(PROCUREMENT_BATCH_SIZES)
            )
            conn.execute(
                "UPDATE supplier_offers SET status='rotated' WHERE id=?",
                (int(row["id"]),),
            )
            self._create_market_offer_conn(
                conn,
                player_id,
                product_id,
                replacement_quantity,
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
            price_factor = clamp(self.rng.gauss(1.0, 0.075), 0.82, 1.18)
            quality_mean = float(supplier["quality_mean"]) + self.rng.gauss(
                0.0, 3.5
            )
            quality_sigma = float(supplier["quality_sigma"]) * self.rng.uniform(
                0.75, 1.10
            )
            reliability = float(supplier["reliability"]) + self.rng.uniform(
                -0.025, 0.025
            )
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
        quality_mean = clamp(quality_mean, 40.0, 98.0)
        quality_sigma = clamp(quality_sigma, 2.0, 20.0)
        reliability = clamp(reliability, 0.50, 0.995)
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
                iso(now + timedelta(days=7)),
            ),
        )
        return int(cur.lastrowid)


class ProcurementMarketGameService(StaffInsightGameService):
    def _free_cash_conn(self, conn, player_id: int) -> int:
        shop = conn.execute(
            "SELECT balance, reserve_target FROM shops WHERE player_id=?",
            (player_id,),
        ).fetchone()
        if not shop:
            return 0
        deposits = int(
            conn.execute(
                """SELECT COALESCE(SUM(deposit),0) FROM employees
                   WHERE player_id=? AND active=1""",
                (player_id,),
            ).fetchone()[0]
        )
        wages = int(
            conn.execute(
                """SELECT COALESCE(SUM(wages_accrued),0) FROM employees
                   WHERE player_id=? AND active=1""",
                (player_id,),
            ).fetchone()[0]
        )
        return max(
            0,
            int(shop["balance"])
            - int(shop["reserve_target"])
            - deposits
            - wages,
        )

    def offers(self, player_id: int, product_id: int | None = None):
        self.simulation.refresh_procurement_market(player_id)
        with self.db.connect() as conn:
            free_cash = self._free_cash_conn(conn, player_id)
            params: list[int] = [player_id, free_cash]
            product_filter = ""
            if product_id is not None:
                product_filter = " AND o.product_id=?"
                params.append(int(product_id))
            return conn.execute(
                f"""SELECT o.*, s.title supplier_title, p.title product_title,
                           p.base_market_price,
                           COALESCE(o.offer_quality_mean, s.quality_mean) resolved_quality_mean,
                           COALESCE(o.offer_quality_sigma, s.quality_sigma) resolved_quality_sigma,
                           COALESCE(o.offer_reliability, s.reliability) resolved_reliability
                    FROM supplier_offers o
                    JOIN suppliers s ON s.id=o.supplier_id
                    JOIN products p ON p.id=o.product_id
                    WHERE o.player_id=? AND o.status='open'
                      AND o.quantity * o.unit_cost <= ?{product_filter}
                    ORDER BY o.quantity, o.unit_cost, o.id""",
                tuple(params),
            ).fetchall()

    def procurement_products(self, player_id: int):
        self.simulation.refresh_procurement_market(player_id)
        with self.db.connect() as conn:
            free_cash = self._free_cash_conn(conn, player_id)
            products = conn.execute(
                "SELECT id, title FROM products WHERE active=1 ORDER BY id"
            ).fetchall()
            counts = conn.execute(
                """SELECT product_id, quantity, COUNT(*) count
                   FROM supplier_offers
                   WHERE player_id=? AND status='open'
                     AND quantity * unit_cost <= ?
                   GROUP BY product_id, quantity""",
                (player_id, free_cash),
            ).fetchall()
        by_product: dict[int, dict[int, int]] = defaultdict(dict)
        for row in counts:
            by_product[int(row["product_id"])][int(row["quantity"])] = int(
                row["count"]
            )
        result = []
        for product in products:
            packs = {
                quantity: by_product[int(product["id"])].get(quantity, 0)
                for quantity in PROCUREMENT_BATCH_SIZES
            }
            result.append(
                {
                    "id": int(product["id"]),
                    "title": product["title"],
                    "counts": packs,
                    "total": sum(packs.values()),
                }
            )
        return result

    def procurement_offer(self, player_id: int, offer_id: int):
        return next(
            (row for row in self.offers(player_id) if int(row["id"]) == int(offer_id)),
            None,
        )

    @staticmethod
    def offer_typical_unit_cost(offer) -> float:
        volume_discount = VOLUME_DISCOUNTS.get(int(offer["quantity"]), 1.0)
        return float(offer["base_market_price"]) * 0.56 * volume_discount

    @tutorial_hooks.first_batch_quality_protection
    @tutorial_hooks.first_purchase_protection
    def buy_offer_for_employee(
        self, player_id: int, offer_id: int, employee_id: int
    ) -> str:
        now = utcnow()
        with self.db.connect() as conn:
            offer = conn.execute(
                """SELECT o.*, s.title supplier_title, p.title product_title,
                          COALESCE(o.offer_quality_mean, s.quality_mean) resolved_quality_mean,
                          COALESCE(o.offer_quality_sigma, s.quality_sigma) resolved_quality_sigma,
                          COALESCE(o.offer_reliability, s.reliability) resolved_reliability
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

            total = int(offer["quantity"] * offer["unit_cost"])
            free_cash = self._free_cash_conn(conn, player_id)
            if free_cash < total:
                return (
                    f"Недостаточно свободных денег. Нужно {total:,} ₽. "
                    f"Свободно {free_cash:,} ₽."
                )

            exposure_before = self._employee_exposure(player_id, employee_id)
            claim = conn.execute(
                """UPDATE supplier_offers
                   SET status='processing'
                   WHERE id=? AND player_id=? AND status='open'""",
                (offer_id, player_id),
            )
            if claim.rowcount != 1:
                return "Предложение уже недоступно."

            free_cash = self._free_cash_conn(conn, player_id)
            if free_cash < total:
                conn.execute(
                    """UPDATE supplier_offers SET status='open'
                       WHERE id=? AND player_id=? AND status='processing'""",
                    (offer_id, player_id),
                )
                return (
                    f"Недостаточно свободных денег. Нужно {total:,} ₽. "
                    f"Свободно {free_cash:,} ₽."
                )

            delivered = self.rng.random() < float(offer["resolved_reliability"])
            quality = clamp(
                self.rng.gauss(
                    float(offer["resolved_quality_mean"]),
                    float(offer["resolved_quality_sigma"]),
                ),
                35.0,
                99.0,
            )
            conn.execute(
                "UPDATE shops SET balance=balance-? WHERE player_id=?",
                (total, player_id),
            )
            if delivered:
                cur = conn.execute(
                    """INSERT INTO batches(
                           player_id, supplier_id, product_id,
                           responsible_employee_id, quantity, remaining,
                           unit_cost, quality, status
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
                game_hours = (
                    1.5
                    + int(offer["quantity"]) / 100.0 * 0.8
                    + self.rng.uniform(0.2, 1.0)
                )
                conn.execute(
                    """INSERT INTO employee_tasks(
                           player_id, employee_id, kind, batch_id, product_id,
                           quantity, completes_at, note
                       ) VALUES (?, ?, 'receive_batch', ?, ?, ?, ?, ?)""",
                    (
                        player_id,
                        employee_id,
                        batch_id,
                        offer["product_id"],
                        offer["quantity"],
                        iso(
                            now
                            + timedelta(
                                hours=game_hours
                                / self.simulation.effective_speed(player_id)
                            )
                        ),
                        f"Получение партии {offer['product_title']}",
                    ),
                )
                conn.execute(
                    """UPDATE employees
                       SET stress=MIN(100, stress+1.2), last_contact_at=?
                       WHERE id=?""",
                    (iso(now), employee_id),
                )
                note = (
                    f"Партия #{batch_id}: {offer['product_title']} · "
                    f"ответственный {employee['alias']}"
                )
            else:
                note = f"Срыв сделки с {offer['supplier_title']}"
                conn.execute(
                    """UPDATE shops
                       SET supplier_reputation=MAX(0, supplier_reputation-1)
                       WHERE player_id=?""",
                    (player_id,),
                )
            conn.execute(
                """INSERT INTO ledger(
                       player_id, amount, kind, reference_type, reference_id, note
                   ) VALUES (?, ?, 'procurement', 'offer', ?, ?)""",
                (player_id, -total, offer_id, note),
            )
            conn.execute(
                """UPDATE supplier_offers SET status='bought'
                   WHERE id=? AND player_id=? AND status='processing'""",
                (offer_id, player_id),
            )

        self.simulation.ensure_procurement_bounds(player_id, now)

        if not delivered:
            return f"Сделка сорвалась. Потеря: {total:,} ₽."
        exposure_after = exposure_before + total
        unsecured = max(0, exposure_after - int(employee["deposit"]))
        risk = (
            f"\n\n🔴 Не покрыто депозитом после закупки: <b>{unsecured:,} ₽</b>."
            if unsecured
            else "\n\nПартия полностью покрыта депозитом сотрудника."
        )
        return (
            f"✅ Куплено: {offer['product_title']} · {offer['quantity']} ед. "
            f"за <b>{total:,} ₽</b>.\n\n"
            f"Складмен {employee['alias']} получает партию.\n"
            "После получения её можно будет передать закладчикам.\n"
            "Оплата складмену будет начислена после успешной передачи товара."
            f"{risk}"
        )
