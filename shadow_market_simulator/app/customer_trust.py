from __future__ import annotations

import math

from .compensation import _deposit_part, _money_from_bps, _policy_conn
from .global_packaging import GlobalPackagingGameService, GlobalPackagingSimulationEngine
from .simulation import clamp, iso
from .staff_relationships import SALES_ACTIVITY_MULTIPLIER


CUSTOMER_TRUST_SCHEMA = """
CREATE TABLE IF NOT EXISTS order_ratings (
    order_id INTEGER PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_rating INTEGER NOT NULL CHECK(product_rating BETWEEN 1 AND 5),
    courier_rating INTEGER NOT NULL CHECK(courier_rating BETWEEN 1 AND 5),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_order_ratings_product
    ON order_ratings(player_id, product_id, created_at);
CREATE INDEX IF NOT EXISTS idx_order_ratings_employee
    ON order_ratings(player_id, employee_id, created_at);
CREATE INDEX IF NOT EXISTS idx_order_ratings_client
    ON order_ratings(player_id, client_id, created_at);

CREATE TABLE IF NOT EXISTS client_relationships (
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    purchases INTEGER NOT NULL DEFAULT 0,
    lifetime_value INTEGER NOT NULL DEFAULT 0,
    trust REAL NOT NULL DEFAULT 0.48,
    last_product_rating INTEGER,
    last_courier_rating INTEGER,
    last_purchase_at TEXT,
    PRIMARY KEY(player_id, client_id)
);

CREATE INDEX IF NOT EXISTS idx_client_relationships_value
    ON client_relationships(player_id, purchases, trust);

CREATE TABLE IF NOT EXISTS shop_trust_state (
    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
    trust_score REAL NOT NULL DEFAULT 64.0,
    availability_ema REAL NOT NULL DEFAULT 0.60,
    fairness_ema REAL NOT NULL DEFAULT 0.65,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _bayesian_rating(conn, player_id: int, field: str, where: str = "", params=()) -> tuple[float, int]:
    if field not in {"product_rating", "courier_rating"}:
        raise ValueError("Unsupported rating field")
    row = conn.execute(
        f"""SELECT COUNT(*) n, COALESCE(SUM({field}),0) total
            FROM order_ratings WHERE player_id=? {where}""",
        (player_id, *params),
    ).fetchone()
    count = int(row["n"] or 0)
    # Eight neutral-good prior observations keep the first few orders from swinging
    # the whole shop wildly while still allowing sustained performance to dominate.
    prior_count = 8
    prior_rating = 3.5
    rating = (float(row["total"] or 0) + prior_count * prior_rating) / (count + prior_count)
    return rating, count


def trust_band(score: float) -> str:
    if score >= 88:
        return "очень высокое"
    if score >= 76:
        return "высокое"
    if score >= 62:
        return "стабильное"
    if score >= 48:
        return "слабое"
    return "низкое"


def premium_allowance(score: float, regular_share: float = 0.0) -> float:
    base = max(0.0, (float(score) - 55.0) / 45.0) * 0.25
    return clamp(base + max(0.0, float(regular_share)) * 0.05, 0.0, 0.30)


class CustomerTrustSimulationEngine(GlobalPackagingSimulationEngine):
    """Final live economy: structured ratings, repeat buyers and long-term trust."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(CUSTOMER_TRUST_SCHEMA)
            self._ensure_all_relationships_conn(conn)

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        with self.db.connect() as conn:
            conn.executescript(CUSTOMER_TRUST_SCHEMA)
            self._ensure_all_relationships_conn(conn, player_id)
            conn.execute(
                "INSERT OR IGNORE INTO shop_trust_state(player_id) VALUES (?)",
                (player_id,),
            )
            self._refresh_trust_conn(conn, player_id, 0.0)
        return created

    def _ensure_all_relationships_conn(self, conn, player_id: int | None = None) -> None:
        if player_id is None:
            rows = conn.execute("SELECT player_id, id FROM clients").fetchall()
        else:
            rows = conn.execute(
                "SELECT player_id, id FROM clients WHERE player_id=?", (player_id,)
            ).fetchall()
        conn.executemany(
            """INSERT OR IGNORE INTO client_relationships(player_id, client_id)
               VALUES (?, ?)""",
            [(int(row["player_id"]), int(row["id"])) for row in rows],
        )

    def _relationship_conn(self, conn, player_id: int, client_id: int):
        conn.execute(
            """INSERT OR IGNORE INTO client_relationships(player_id, client_id)
               VALUES (?, ?)""",
            (player_id, client_id),
        )
        return conn.execute(
            """SELECT * FROM client_relationships
               WHERE player_id=? AND client_id=?""",
            (player_id, client_id),
        ).fetchone()

    def _availability_now_conn(self, conn, player_id: int) -> float:
        total = int(conn.execute(
            """SELECT COUNT(*) FROM products p
               WHERE p.active=1 AND EXISTS(
                   SELECT 1 FROM listings l
                   WHERE l.player_id=? AND l.product_id=p.id AND l.active=1
               )""",
            (player_id,),
        ).fetchone()[0])
        if total <= 0:
            return 1.0
        stocked = int(conn.execute(
            """SELECT COUNT(DISTINCT rp.product_id)
               FROM retail_positions rp
               JOIN employees e ON e.id=rp.employee_id
               WHERE rp.player_id=? AND rp.position_count>0
                 AND e.active=1 AND e.available=1 AND e.role='courier'""",
            (player_id,),
        ).fetchone()[0])
        return clamp(stocked / total, 0.0, 1.0)

    def _refresh_trust_conn(self, conn, player_id: int, sim_hours: float) -> dict[str, float]:
        conn.execute(
            "INSERT OR IGNORE INTO shop_trust_state(player_id) VALUES (?)", (player_id,)
        )
        state = conn.execute(
            "SELECT * FROM shop_trust_state WHERE player_id=?", (player_id,)
        ).fetchone()
        availability_now = self._availability_now_conn(conn, player_id)
        old_availability = float(state["availability_ema"])
        if sim_hours > 0:
            alpha = 1.0 - math.exp(-min(72.0, float(sim_hours)) / 18.0)
            availability = old_availability * (1.0 - alpha) + availability_now * alpha
        else:
            availability = old_availability

        product_rating, _ = _bayesian_rating(conn, player_id, "product_rating")
        courier_rating, _ = _bayesian_rating(conn, player_id, "courier_rating")
        fairness = float(state["fairness_ema"])
        trust = 100.0 * (
            0.36 * (product_rating / 5.0)
            + 0.24 * (courier_rating / 5.0)
            + 0.24 * availability
            + 0.16 * fairness
        )
        trust = clamp(trust, 20.0, 98.0)
        conn.execute(
            """UPDATE shop_trust_state
               SET trust_score=?, availability_ema=?, updated_at=CURRENT_TIMESTAMP
               WHERE player_id=?""",
            (trust, availability, player_id),
        )
        # Keep the old technical field coherent for lower layers that still read it.
        conn.execute(
            "UPDATE shops SET rating=? WHERE player_id=?",
            (clamp(trust / 20.0, 1.0, 5.0), player_id),
        )
        return {
            "trust_score": trust,
            "availability": availability,
            "fairness": fairness,
            "product_rating": product_rating,
            "courier_rating": courier_rating,
        }

    def _customer_counts_conn(self, conn, player_id: int) -> dict[str, float]:
        row = conn.execute(
            """SELECT
                   COUNT(*) total,
                   SUM(CASE WHEN purchases>=1 THEN 1 ELSE 0 END) buyers,
                   SUM(CASE WHEN purchases>=2 THEN 1 ELSE 0 END) repeat_clients,
                   SUM(CASE WHEN purchases>=4 AND trust>=0.72 THEN 1 ELSE 0 END) regulars,
                   COALESCE(AVG(CASE WHEN purchases>0 THEN trust END),0.48) avg_trust
               FROM client_relationships WHERE player_id=?""",
            (player_id,),
        ).fetchone()
        buyers = int(row["buyers"] or 0)
        repeat_clients = int(row["repeat_clients"] or 0)
        return {
            "total": int(row["total"] or 0),
            "buyers": buyers,
            "repeat_clients": repeat_clients,
            "regulars": int(row["regulars"] or 0),
            "avg_trust": float(row["avg_trust"] or 0.48),
            "repeat_share": repeat_clients / buyers if buyers else 0.0,
        }

    def _select_client_conn(self, conn, player_id: int):
        rows = conn.execute(
            """SELECT c.*, cr.purchases relationship_purchases,
                      cr.trust relationship_trust
               FROM clients c
               JOIN client_relationships cr
                 ON cr.player_id=c.player_id AND cr.client_id=c.id
               WHERE c.player_id=?""",
            (player_id,),
        ).fetchall()
        if not rows:
            return None
        weights = []
        for row in rows:
            purchases = int(row["relationship_purchases"])
            trust = float(row["relationship_trust"])
            if purchases <= 0:
                repeat_weight = 1.0
            elif purchases == 1:
                repeat_weight = 1.20 + trust * 0.55
            else:
                repeat_weight = 1.35 + purchases * 0.24 + trust * 0.95
            honesty_weight = clamp(1.08 - float(row["fraud_propensity"]) * 1.6, 0.48, 1.08)
            weights.append(repeat_weight * honesty_weight)
        return self.rng.choices(list(rows), weights=weights, k=1)[0]

    @staticmethod
    def _product_rating(quality: float) -> int:
        if quality >= 90:
            return 5
        if quality >= 80:
            return 4
        if quality >= 68:
            return 3
        if quality >= 55:
            return 2
        return 1

    def _courier_rating(self, employee) -> int:
        service = (
            float(employee["attention"]) * 0.55
            + float(employee["reliability"]) * 0.30
            + float(employee["loyalty"]) * 0.15
            - max(0.0, float(employee["stress"]) - 35.0) / 180.0
            + self.rng.uniform(-0.055, 0.055)
        )
        if service >= 0.88:
            return 5
        if service >= 0.75:
            return 4
        if service >= 0.61:
            return 3
        if service >= 0.47:
            return 2
        return 1

    def _record_rating_conn(self, conn, order_id: int, employee) -> int:
        existing = conn.execute(
            "SELECT order_id FROM order_ratings WHERE order_id=?", (order_id,)
        ).fetchone()
        if existing:
            return int(order_id)
        order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            return int(order_id)
        product_rating = self._product_rating(float(order["quality"]))
        courier_rating = self._courier_rating(employee)
        conn.execute(
            """INSERT INTO order_ratings(
                   order_id, player_id, client_id, employee_id, product_id,
                   product_rating, courier_rating
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                order["player_id"],
                order["client_id"],
                order["employee_id"],
                order["product_id"],
                product_rating,
                courier_rating,
            ),
        )
        relationship = self._relationship_conn(
            conn, int(order["player_id"]), int(order["client_id"])
        )
        product_norm = (product_rating - 1) / 4.0
        courier_norm = (courier_rating - 1) / 4.0
        experience = product_norm * 0.62 + courier_norm * 0.38
        trust_delta = (experience - 0.58) * 0.16
        conn.execute(
            """UPDATE client_relationships
               SET purchases=purchases+1,
                   lifetime_value=lifetime_value+?,
                   trust=MIN(1.0, MAX(0.0, trust+?)),
                   last_product_rating=?, last_courier_rating=?,
                   last_purchase_at=CURRENT_TIMESTAMP
               WHERE player_id=? AND client_id=?""",
            (
                int(order["revenue"]),
                trust_delta,
                product_rating,
                courier_rating,
                int(order["player_id"]),
                int(order["client_id"]),
            ),
        )
        # Preserve the generic client field for old risk calculations, but make the
        # shop-specific relationship the canonical loyalty source.
        updated = clamp(float(relationship["trust"]) + trust_delta, 0.0, 1.0)
        conn.execute("UPDATE clients SET loyalty=? WHERE id=?", (updated, order["client_id"]))
        return int(order_id)

    def _create_retail_order(self, conn, player_id: int, listing, now) -> bool | None:
        position = conn.execute(
            """SELECT rp.id position_id, rp.allocation_id, rp.batch_id,
                      rp.employee_id retail_employee_id, rp.product_id,
                      rp.pack_size, rp.position_count,
                      rp.unit_cost position_unit_cost, rp.quality position_quality,
                      e.id employee_id, e.attention, e.reliability, e.stress,
                      e.honesty, e.loyalty
               FROM retail_positions rp
               JOIN employees e ON e.id=rp.employee_id
               WHERE rp.player_id=? AND rp.product_id=? AND rp.pack_size=?
                 AND rp.position_count>0 AND e.active=1 AND e.available=1
                 AND e.role='courier'
               ORDER BY rp.created_at, rp.id LIMIT 1""",
            (player_id, listing["product_id"], listing["pack_size"]),
        ).fetchone()
        client = self._select_client_conn(conn, player_id)
        if not position or not client:
            return None

        relationship = self._relationship_conn(conn, player_id, int(client["id"]))
        purchase_number = int(relationship["purchases"]) + 1
        policy = _policy_conn(conn, player_id, "courier")
        qty = int(listing["pack_size"])
        revenue = int(listing["price"])
        cost = int(position["position_unit_cost"] * qty)
        employee_cost = int(policy["fixed_fee"]) + _money_from_bps(
            revenue, int(policy["base_rate_bps"])
        )
        deposit_part = _deposit_part(
            employee_cost, int(policy["deposit_contribution_pct"])
        )
        quality = float(position["position_quality"])

        conn.execute(
            "UPDATE retail_positions SET position_count=position_count-1 WHERE id=?",
            (position["position_id"],),
        )
        conn.execute(
            """UPDATE employees
               SET jobs_done=jobs_done+1,
                   wages_accrued=wages_accrued+?, deposit_accrued=deposit_accrued+?,
                   stress=MIN(100, stress+?), last_contact_at=?
               WHERE id=?""",
            (
                employee_cost,
                deposit_part,
                self.rng.uniform(0.05, 0.35),
                iso(now),
                position["employee_id"],
            ),
        )
        conn.execute(
            """UPDATE clients
               SET shop_orders=shop_orders+1, marketplace_orders=marketplace_orders+1,
                   total_spend=total_spend+?
               WHERE id=?""",
            (revenue, client["id"]),
        )
        cur = conn.execute(
            """INSERT INTO orders(
                   player_id, client_id, employee_id, batch_id, product_id, quantity,
                   revenue, cost, employee_cost, employee_deposit_contribution, quality,
                   customer_purchase_number, customer_was_repeat
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                player_id,
                client["id"],
                position["employee_id"],
                position["batch_id"],
                listing["product_id"],
                qty,
                revenue,
                cost,
                employee_cost,
                deposit_part,
                quality,
                purchase_number,
                int(purchase_number > 1),
            ),
        )
        order_id = int(cur.lastrowid)
        profit = revenue - cost - employee_cost
        conn.execute(
            """UPDATE shops
               SET balance=balance+?, total_revenue=total_revenue+?,
                   total_profit=total_profit+?, total_orders=total_orders+1
               WHERE player_id=?""",
            (revenue, revenue, profit, player_id),
        )
        conn.execute(
            """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
               VALUES (?, ?, 'sale', 'order', ?, ?)""",
            (
                player_id,
                revenue,
                order_id,
                f"Заказ #{order_id} · комиссия розницы {employee_cost:,} ₽ начислена",
            ),
        )

        self._record_rating_conn(conn, order_id, position)
        employee_view = {
            "id": int(position["employee_id"]),
            "attention": float(position["attention"]),
            "stress": float(position["stress"]),
            "honesty": float(position["honesty"]),
            "loyalty": float(position["loyalty"]),
        }
        probability = self._dispute_probability(
            client,
            employee_view,
            quality,
            float(listing["complaint_modifier"]),
        )
        if self.rng.random() < probability:
            self._open_dispute(
                conn,
                player_id,
                order_id,
                client,
                employee_view,
                quality,
                revenue,
                now,
            )
            return True
        return False

    def _simulate_sales(self, conn, player_id: int, shop, sim_hours: float, now):
        self._process_tasks(conn, player_id, now)
        effective_hours = max(0.0, float(sim_hours)) * SALES_ACTIVITY_MULTIPLIER
        metrics = self._refresh_trust_conn(conn, player_id, sim_hours)
        customers = self._customer_counts_conn(conn, player_id)
        regular_share = customers["regulars"] / customers["buyers"] if customers["buyers"] else 0.0
        allowance = premium_allowance(metrics["trust_score"], regular_share)

        trust_effect = 0.55 + (metrics["trust_score"] / 100.0) * 1.05
        regular_effect = 1.0 + min(
            0.85,
            customers["regulars"] * 0.035 + customers["repeat_share"] * 0.45,
        )
        availability_effect = 0.55 + metrics["availability"] * 0.75

        listings = conn.execute(
            """SELECT l.*, p.base_market_price, p.base_demand, p.complaint_modifier
               FROM listings l JOIN products p ON p.id=l.product_id
               WHERE l.player_id=? AND l.active=1""",
            (player_id,),
        ).fetchall()
        orders_created = 0
        disputes_created = 0
        for listing in listings:
            available_positions = int(conn.execute(
                """SELECT COALESCE(SUM(rp.position_count),0)
                   FROM retail_positions rp JOIN employees e ON e.id=rp.employee_id
                   WHERE rp.player_id=? AND rp.product_id=? AND rp.pack_size=?
                     AND rp.position_count>0 AND e.active=1 AND e.available=1
                     AND e.role='courier'""",
                (player_id, listing["product_id"], listing["pack_size"]),
            ).fetchone()[0])
            if available_positions <= 0:
                continue

            product_rating, _ = _bayesian_rating(
                conn,
                player_id,
                "product_rating",
                "AND product_id=?",
                (int(listing["product_id"]),),
            )
            quality_effect = 0.70 + (product_rating / 5.0) * 0.65
            unit_price = float(listing["price"]) / max(1, int(listing["pack_size"]))
            trusted_market_price = float(listing["base_market_price"]) * (1.0 + allowance)
            price_ratio = unit_price / max(1.0, trusted_market_price)
            price_effect = clamp(math.exp(-1.45 * (price_ratio - 1.0)), 0.45, 1.40)
            pack_effect = {1: 1.0, 2: 0.68, 5: 0.28}.get(int(listing["pack_size"]), 0.2)
            expected = (
                float(listing["base_demand"]) / 24.0
                * effective_hours
                * trust_effect
                * regular_effect
                * availability_effect
                * quality_effect
                * price_effect
                * pack_effect
            )
            count = min(available_positions, self._poisson(expected))
            for _ in range(count):
                disputed = self._create_retail_order(conn, player_id, listing, now)
                if disputed is None:
                    break
                orders_created += 1
                disputes_created += int(disputed)

        self._refresh_trust_conn(conn, player_id, 0.0)
        return orders_created, disputes_created

    def _simulate_management_events(self, conn, player_id: int, sim_hours: float, now) -> int:
        before_id = int(conn.execute(
            "SELECT COALESCE(MAX(id),0) FROM inbox WHERE player_id=?", (player_id,)
        ).fetchone()[0])
        created = super()._simulate_management_events(conn, player_id, sim_hours, now)
        rows = conn.execute(
            """SELECT id, payload_json FROM inbox
               WHERE player_id=? AND id>? AND kind='discount_request'""",
            (player_id, before_id),
        ).fetchall()
        import json
        removed = 0
        for row in rows:
            try:
                client_id = int(json.loads(row["payload_json"] or "{}").get("client_id", 0))
            except (TypeError, ValueError):
                client_id = 0
            relationship = self._relationship_conn(conn, player_id, client_id) if client_id else None
            if not relationship or int(relationship["purchases"]) < 2 or float(relationship["trust"]) < 0.58:
                conn.execute("DELETE FROM inbox WHERE id=?", (row["id"],))
                removed += 1
        return max(0, int(created) - removed)


class CustomerTrustGameService(GlobalPackagingGameService):
    """UI facade for trust, customers, split ratings and supplier history."""

    def customer_metrics(self, player_id: int) -> dict:
        with self.db.connect() as conn:
            self.simulation._ensure_all_relationships_conn(conn, player_id)
            metrics = self.simulation._refresh_trust_conn(conn, player_id, 0.0)
            counts = self.simulation._customer_counts_conn(conn, player_id)
            orders = conn.execute(
                """SELECT COUNT(*) total,
                          SUM(CASE WHEN customer_was_repeat=1 THEN 1 ELSE 0 END) repeated
                   FROM orders WHERE player_id=?""",
                (player_id,),
            ).fetchone()
            ltv = conn.execute(
                """SELECT COALESCE(AVG(CASE WHEN purchases>0 THEN lifetime_value END),0) avg_ltv,
                          COALESCE(MAX(lifetime_value),0) max_ltv
                   FROM client_relationships WHERE player_id=?""",
                (player_id,),
            ).fetchone()
        total_orders = int(orders["total"] or 0)
        repeat_orders = int(orders["repeated"] or 0)
        regular_share = counts["regulars"] / counts["buyers"] if counts["buyers"] else 0.0
        return {
            **metrics,
            **counts,
            "orders": total_orders,
            "repeat_orders": repeat_orders,
            "repeat_order_share": repeat_orders / total_orders if total_orders else 0.0,
            "avg_ltv": float(ltv["avg_ltv"] or 0),
            "max_ltv": int(ltv["max_ltv"] or 0),
            "premium_allowance": premium_allowance(metrics["trust_score"], regular_share),
        }

    def product_quality_metrics(self, player_id: int, product_id: int) -> dict:
        with self.db.connect() as conn:
            rating, count = _bayesian_rating(
                conn, player_id, "product_rating", "AND product_id=?", (product_id,)
            )
            raw = conn.execute(
                """SELECT COUNT(*) n, COALESCE(AVG(product_rating),0) avg
                   FROM order_ratings WHERE player_id=? AND product_id=?""",
                (player_id, product_id),
            ).fetchone()
        return {
            "rating": float(raw["avg"] or rating),
            "count": int(raw["n"] or count),
            "demand_rating": rating,
        }

    def employee_service_metrics(self, player_id: int, employee_id: int) -> dict:
        with self.db.connect() as conn:
            raw = conn.execute(
                """SELECT COUNT(*) n, COALESCE(AVG(courier_rating),0) avg
                   FROM order_ratings WHERE player_id=? AND employee_id=?""",
                (player_id, employee_id),
            ).fetchone()
        return {"rating": float(raw["avg"] or 0.0), "count": int(raw["n"] or 0)}

    def supplier_performance(self, player_id: int, supplier_id: int, product_id: int | None = None) -> dict:
        params = [player_id, supplier_id]
        product_filter = ""
        if product_id is not None:
            product_filter = " AND o.product_id=?"
            params.append(int(product_id))
        with self.db.connect() as conn:
            row = conn.execute(
                f"""SELECT COUNT(*) orders,
                           COALESCE(AVG(r.product_rating),0) product_rating,
                           COALESCE(AVG(o.quality),0) internal_quality,
                           COUNT(DISTINCT o.batch_id) batches
                    FROM orders o
                    JOIN batches b ON b.id=o.batch_id
                    LEFT JOIN order_ratings r ON r.order_id=o.id
                    WHERE o.player_id=? AND b.supplier_id=? {product_filter}""",
                tuple(params),
            ).fetchone()
        return {
            "orders": int(row["orders"] or 0),
            "batches": int(row["batches"] or 0),
            "product_rating": float(row["product_rating"] or 0.0),
            "internal_quality": float(row["internal_quality"] or 0.0),
        }

    def procurement_offer(self, player_id: int, offer_id: int):
        row = super().procurement_offer(player_id, offer_id)
        if not row:
            return None
        data = dict(row)
        history = self.supplier_performance(
            player_id, int(row["supplier_id"]), int(row["product_id"])
        )
        if history["orders"]:
            data["supplier_title"] = (
                f"{row['supplier_title']} · 🧪 {history['product_rating']:.2f}/5 "
                f"({history['orders']} покуп.)"
            )
        else:
            data["supplier_title"] = f"{row['supplier_title']} · истории пока нет"
        data["supplier_history"] = history
        return data

    def employee_details(self, player_id: int, employee_id: int) -> str | None:
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=?",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                return None
        exposure = self._employee_exposure(player_id, employee_id)
        unsecured = max(0, exposure - int(employee["deposit"]))
        dispute_rate = employee["disputes"] / employee["jobs_done"] * 100.0 if employee["jobs_done"] else 0.0
        role = str(employee["role"])
        policy = self.compensation_policy(player_id, role)
        role_title = "Оптовый сотрудник" if role == "warehouse" else "Розничный сотрудник"
        role_icon = "🚚" if role == "warehouse" else "👤"
        activity = "\n".join(self._activity_details(player_id, employee_id))
        inventory = self._inventory_lines(player_id, employee_id, role)
        inventory_text = "\n".join(inventory) if inventory else "Нет товара под ответственностью."
        if role == "courier":
            terms = (
                f"За успешный заказ: {policy['fixed_fee']:,} ₽\n"
                f"Комиссия с продажи: {policy['base_rate_bps'] / 100:.1f}%\n"
                f"В депозит: {policy['deposit_contribution_pct']}%"
            )
        else:
            terms = (
                f"От стоимости передачи: {policy['base_rate_bps'] / 100:.1f}%\n"
                f"За непокрытый риск: +{policy['risk_rate_bps'] / 100:.1f}%\n"
                f"В депозит: {policy['deposit_contribution_pct']}%"
            )
        accrued_cash = int(employee["wages_accrued"]) - int(employee["deposit_accrued"])
        text = (
            f"<b>{role_icon} {employee['alias']} · {role_title}</b>\n\n"
            f"<b>Сейчас</b>\n{activity}\n\n"
            f"<b>Товар</b>\n{inventory_text}\n\n"
            f"<b>Ответственность</b>\n"
            f"Стоимость товара: {exposure:,} ₽\n"
            f"Депозит: <b>{employee['deposit']:,} ₽</b>\n"
            f"Не покрыто: <b>{unsecured:,} ₽</b>\n\n"
            f"<b>Условия команды</b>\n{terms}\n"
            f"Начислено: <b>{employee['wages_accrued']:,} ₽</b>\n"
            f"Из них деньгами: {accrued_cash:,} ₽\n"
            f"В депозит при выплате: {employee['deposit_accrued']:,} ₽\n\n"
        )
        if role == "courier":
            service = self.employee_service_metrics(player_id, employee_id)
            text += "<b>Качество работы</b>\n"
            if service["count"]:
                text += f"Оценка покупателей: <b>{service['rating']:.2f}/5</b> · {service['count']} заказов\n"
            else:
                text += "Оценок покупателей пока нет.\n"
            text += "\n<b>Продуктивность</b>\n" + "\n".join(
                self._productivity_lines(player_id, employee_id)
            ) + "\n\n"
        text += (
            f"<b>Статистика</b>\n"
            f"Операций: {employee['jobs_done']}\n"
            f"Диспутов: {employee['disputes']} ({dispute_rate:.1f}%)\n"
            f"Потери: {employee['losses']:,} ₽\n"
            f"Всего заработано: {employee['total_wages_paid'] + employee['wages_accrued']:,} ₽\n"
            f"Из заработка в депозит: {employee['deposit_from_wages']:,} ₽"
        )
        if unsecured > 0:
            text += "\n\n🔴 Часть товара не покрыта депозитом. Это осознанный дополнительный риск."
        return text

    def dispute_details(self, player_id: int, dispute_id: int) -> str | None:
        text = super().dispute_details(player_id, dispute_id)
        if not text:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT o.client_id, cr.purchases, cr.trust
                   FROM disputes d JOIN orders o ON o.id=d.order_id
                   LEFT JOIN client_relationships cr
                     ON cr.player_id=d.player_id AND cr.client_id=o.client_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
        if row:
            purchases = int(row["purchases"] or 0)
            trust = float(row["trust"] or 0.48)
            status = "постоянный" if purchases >= 4 and trust >= 0.72 else "повторный" if purchases >= 2 else "новый"
            text += (
                "\n\n<b>Отношения с клиентом</b>\n"
                f"Статус: <b>{status}</b>\n"
                f"Покупок: {purchases}\n"
                f"Доверие к магазину: {trust * 100:.0f}/100"
            )
        return text

    def _apply_customer_case_result(
        self, player_id: int, dispute_id: int, cause: str, decision: str, client_id: int
    ) -> None:
        quality = self._decision_quality(cause, decision)
        with self.db.connect() as conn:
            self.simulation._relationship_conn(conn, player_id, client_id)
            if cause == "CLIENT_FRAUD":
                client_delta = -0.08 if decision == "reject" else -0.14
            elif quality > 0:
                client_delta = 0.08
            elif quality < 0:
                client_delta = -0.18
            else:
                client_delta = 0.01
            conn.execute(
                """UPDATE client_relationships
                   SET trust=MIN(1.0, MAX(0.0, trust+?))
                   WHERE player_id=? AND client_id=?""",
                (client_delta, player_id, client_id),
            )
            state = conn.execute(
                "SELECT fairness_ema FROM shop_trust_state WHERE player_id=?",
                (player_id,),
            ).fetchone()
            old = float(state["fairness_ema"] if state else 0.65)
            target = 1.0 if quality > 0 else 0.55 if quality == 0 else 0.0
            fairness = old * 0.86 + target * 0.14
            conn.execute(
                """INSERT OR IGNORE INTO shop_trust_state(player_id) VALUES (?)""",
                (player_id,),
            )
            conn.execute(
                "UPDATE shop_trust_state SET fairness_ema=? WHERE player_id=?",
                (fairness, player_id),
            )
            self.simulation._refresh_trust_conn(conn, player_id, 0.0)

    def resolve_dispute_with_source(
        self, player_id: int, dispute_id: int, decision: str, source: str
    ) -> str:
        with self.db.connect() as conn:
            before = conn.execute(
                """SELECT d.status, d.true_cause, o.client_id
                   FROM disputes d JOIN orders o ON o.id=d.order_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
        result = super().resolve_dispute_with_source(player_id, dispute_id, decision, source)
        if not before or before["status"] != "open":
            return result
        with self.db.connect() as conn:
            after = conn.execute(
                "SELECT status FROM disputes WHERE id=? AND player_id=?",
                (dispute_id, player_id),
            ).fetchone()
        if after and after["status"] == "resolved":
            self._apply_customer_case_result(
                player_id,
                dispute_id,
                str(before["true_cause"]),
                decision,
                int(before["client_id"]),
            )
        return result

    def handle_inbox_action(self, player_id: int, item_id: int, action: str) -> str:
        with self.db.connect() as conn:
            item = conn.execute(
                "SELECT kind, payload_json FROM inbox WHERE id=? AND player_id=? AND status='open'",
                (item_id, player_id),
            ).fetchone()
        client_id = None
        if item and item["kind"] == "discount_request":
            import json
            try:
                client_id = int(json.loads(item["payload_json"] or "{}").get("client_id", 0))
            except (TypeError, ValueError):
                client_id = None
        result = super().handle_inbox_action(player_id, item_id, action)
        if client_id:
            with self.db.connect() as conn:
                relationship = self.simulation._relationship_conn(conn, player_id, client_id)
                delta = 0.045 if action == "approve" else -0.018
                # Established customers react more strongly because the relationship
                # is already valuable; this turns service decisions into retention.
                if int(relationship["purchases"]) >= 4:
                    delta *= 1.25
                conn.execute(
                    """UPDATE client_relationships
                       SET trust=MIN(1.0, MAX(0.0, trust+?))
                       WHERE player_id=? AND client_id=?""",
                    (delta, player_id, client_id),
                )
                self.simulation._refresh_trust_conn(conn, player_id, 0.0)
        return result
