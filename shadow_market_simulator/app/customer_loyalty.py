from __future__ import annotations

import math

from .compensation import CompensationSimulationEngine, CompensationGameService


CUSTOMER_LOYALTY_SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_experience (
    order_id INTEGER PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_rating INTEGER NOT NULL CHECK(product_rating BETWEEN 1 AND 5),
    courier_rating INTEGER NOT NULL CHECK(courier_rating BETWEEN 1 AND 5),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_customer_experience_product
    ON customer_experience(player_id, product_id, created_at);
CREATE INDEX IF NOT EXISTS idx_customer_experience_employee
    ON customer_experience(player_id, employee_id, created_at);
CREATE INDEX IF NOT EXISTS idx_customer_experience_client
    ON customer_experience(player_id, client_id, created_at);

CREATE TABLE IF NOT EXISTS client_shop_relationships (
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    purchases INTEGER NOT NULL DEFAULT 0,
    lifetime_value INTEGER NOT NULL DEFAULT 0,
    trust REAL NOT NULL DEFAULT 0.45,
    satisfaction REAL NOT NULL DEFAULT 0.50,
    last_purchase_at TEXT,
    PRIMARY KEY(player_id, client_id)
);
"""


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def price_tolerance_multiplier(trust: float) -> float:
    # A trusted shop can charge materially above market without losing all demand.
    return 1.0 + clamp((trust - 0.45) * 0.55, -0.12, 0.28)


def repeat_purchase_multiplier(purchases: int, trust: float) -> float:
    return clamp(0.78 + purchases * 0.10 + trust * 0.55, 0.70, 1.75)


class CustomerLoyaltySimulationEngine(CompensationSimulationEngine):
    """Split product/courier ratings and make repeat buyers a core demand driver."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(CUSTOMER_LOYALTY_SCHEMA)

    def _ensure_relationship_conn(self, conn, player_id: int, client_id: int) -> None:
        conn.execute(
            """INSERT OR IGNORE INTO client_shop_relationships(player_id, client_id)
               VALUES (?, ?)""",
            (player_id, client_id),
        )

    def _experience_scores(self, quality: float, delivery_bad: bool) -> tuple[int, int]:
        product = 5 if quality >= 90 else 4 if quality >= 80 else 3 if quality >= 68 else 2 if quality >= 55 else 1
        courier = 2 if delivery_bad else 5
        if not delivery_bad and self.rng.random() < 0.18:
            courier = 4
        return product, courier

    def _record_experience_conn(self, conn, order, product_rating: int, courier_rating: int) -> None:
        conn.execute(
            """INSERT OR IGNORE INTO customer_experience(
                   order_id, player_id, client_id, employee_id, product_id,
                   product_rating, courier_rating
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                int(order["id"]), int(order["player_id"]), int(order["client_id"]),
                int(order["employee_id"]), int(order["product_id"]),
                product_rating, courier_rating,
            ),
        )
        self._ensure_relationship_conn(conn, int(order["player_id"]), int(order["client_id"]))
        product_norm = (product_rating - 1) / 4.0
        courier_norm = (courier_rating - 1) / 4.0
        experience = product_norm * 0.62 + courier_norm * 0.38
        trust_delta = (experience - 0.58) * 0.11
        satisfaction_delta = (experience - 0.50) * 0.18
        conn.execute(
            """UPDATE client_shop_relationships
               SET purchases=purchases+1,
                   lifetime_value=lifetime_value+?,
                   trust=MIN(1.0, MAX(0.0, trust+?)),
                   satisfaction=MIN(1.0, MAX(0.0, satisfaction+?)),
                   last_purchase_at=CURRENT_TIMESTAMP
               WHERE player_id=? AND client_id=?""",
            (
                int(order["revenue"]), trust_delta, satisfaction_delta,
                int(order["player_id"]), int(order["client_id"]),
            ),
        )

    def create_review_for_order(self, player_id: int, order_id: int, force: bool = False):
        # Legacy public method now materializes structured ratings instead of text reviews.
        with self.db.connect() as conn:
            order = conn.execute(
                """SELECT * FROM orders WHERE id=? AND player_id=?""",
                (order_id, player_id),
            ).fetchone()
            if not order:
                return None
            existing = conn.execute(
                "SELECT order_id FROM customer_experience WHERE order_id=?",
                (order_id,),
            ).fetchone()
            if existing:
                return order_id
            delivery_bad = self.rng.random() < 0.08
            product_rating, courier_rating = self._experience_scores(float(order["quality"]), delivery_bad)
            self._record_experience_conn(conn, order, product_rating, courier_rating)
        return order_id

    def _choose_client(self, conn, player_id: int):
        clients = conn.execute(
            "SELECT * FROM clients WHERE player_id=?",
            (player_id,),
        ).fetchall()
        if not clients:
            return None
        weights = []
        for client in clients:
            self._ensure_relationship_conn(conn, player_id, int(client["id"]))
            rel = conn.execute(
                """SELECT purchases, trust FROM client_shop_relationships
                   WHERE player_id=? AND client_id=?""",
                (player_id, int(client["id"])),
            ).fetchone()
            weights.append(repeat_purchase_multiplier(int(rel["purchases"]), float(rel["trust"])))
        return self.rng.choices(clients, weights=weights, k=1)[0]

    def _shop_trust_conn(self, conn, player_id: int) -> float:
        row = conn.execute(
            """SELECT AVG(trust) trust FROM client_shop_relationships
               WHERE player_id=? AND purchases>0""",
            (player_id,),
        ).fetchone()
        return float(row["trust"] or 0.45)

    def _product_quality_score_conn(self, conn, player_id: int, product_id: int) -> float:
        row = conn.execute(
            """SELECT AVG(product_rating) avg_rating FROM customer_experience
               WHERE player_id=? AND product_id=?""",
            (player_id, product_id),
        ).fetchone()
        return float(row["avg_rating"] or 4.0)

    def _courier_service_score_conn(self, conn, player_id: int) -> float:
        row = conn.execute(
            """SELECT AVG(courier_rating) avg_rating FROM customer_experience
               WHERE player_id=?""",
            (player_id,),
        ).fetchone()
        return float(row["avg_rating"] or 4.0)

    def _availability_score_conn(self, conn, player_id: int) -> float:
        total = int(conn.execute("SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0])
        if total <= 0:
            return 1.0
        stocked = int(conn.execute(
            """SELECT COUNT(DISTINCT product_id) FROM retail_positions
               WHERE player_id=? AND position_count>0""",
            (player_id,),
        ).fetchone()[0])
        return clamp(stocked / total, 0.25, 1.0)

    def _simulate_sales(self, conn, player_id: int, shop, sim_hours: float, now):
        # Re-implements only demand weighting: operational sales flow stays unchanged
        # in the parent classes, but reputation and availability dominate price.
        trust = self._shop_trust_conn(conn, player_id)
        service = self._courier_service_score_conn(conn, player_id) / 5.0
        availability = self._availability_score_conn(conn, player_id)
        shop_rating = float(shop["rating"] if "rating" in shop.keys() else 4.0)
        reputation_effect = clamp(0.55 + trust * 0.75 + service * 0.35 + (shop_rating - 4.0) * 0.12, 0.55, 1.75)
        availability_effect = 0.55 + availability * 0.65

        positions = conn.execute(
            """SELECT rp.*, p.base_demand, l.price, p.base_market_price
               FROM retail_positions rp
               JOIN products p ON p.id=rp.product_id
               JOIN listings l ON l.player_id=rp.player_id AND l.product_id=rp.product_id AND l.pack_size=rp.pack_size
               WHERE rp.player_id=? AND rp.position_count>0""",
            (player_id,),
        ).fetchall()
        sales = 0
        revenue = 0
        for pos in positions:
            quality_score = self._product_quality_score_conn(conn, player_id, int(pos["product_id"])) / 5.0
            quality_effect = clamp(0.62 + quality_score * 0.68, 0.65, 1.30)
            tolerance = price_tolerance_multiplier(trust)
            price_ratio = float(pos["price"]) / max(1.0, float(pos["base_market_price"]) * tolerance)
            price_effect = clamp(math.exp(-1.35 * (price_ratio - 1.0)), 0.48, 1.38)
            pack_effect = {1: 1.0, 2: 0.68, 5: 0.28}.get(int(pos["pack_size"]), 0.2)
            expected = (
                float(pos["base_demand"]) / 24.0 * max(0.0, sim_hours)
                * reputation_effect * availability_effect * quality_effect * price_effect * pack_effect
            )
            count = min(int(pos["position_count"]), self.poisson(expected))
            for _ in range(count):
                client = self._choose_client(conn, player_id)
                if client is None:
                    break
                order_id = self._complete_position_sale_conn(conn, player_id, pos, client, now)
                if order_id:
                    sales += 1
                    revenue += int(pos["price"])
                    self.create_review_for_order(player_id, int(order_id), force=True)
        return sales, revenue


class CustomerLoyaltyGameService(CompensationGameService):
    def customer_metrics(self, player_id: int) -> dict:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) clients,
                          SUM(CASE WHEN purchases>=2 THEN 1 ELSE 0 END) repeat_clients,
                          SUM(CASE WHEN purchases>=4 AND trust>=0.70 THEN 1 ELSE 0 END) regulars,
                          COALESCE(AVG(CASE WHEN purchases>0 THEN trust END), 0.45) trust,
                          COALESCE(SUM(lifetime_value),0) lifetime_value
                   FROM client_shop_relationships WHERE player_id=?""",
                (player_id,),
            ).fetchone()
            product = conn.execute(
                "SELECT AVG(product_rating) r FROM customer_experience WHERE player_id=?",
                (player_id,),
            ).fetchone()
            courier = conn.execute(
                "SELECT AVG(courier_rating) r FROM customer_experience WHERE player_id=?",
                (player_id,),
            ).fetchone()
        return {
            "clients": int(row["clients"] or 0),
            "repeat_clients": int(row["repeat_clients"] or 0),
            "regulars": int(row["regulars"] or 0),
            "trust": float(row["trust"] or 0.45),
            "lifetime_value": int(row["lifetime_value"] or 0),
            "product_rating": float(product["r"] or 0.0),
            "courier_rating": float(courier["r"] or 0.0),
        }

    def employee_service_rating(self, player_id: int, employee_id: int) -> tuple[float, int]:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT AVG(courier_rating) r, COUNT(*) n FROM customer_experience
                   WHERE player_id=? AND employee_id=?""",
                (player_id, employee_id),
            ).fetchone()
        return float(row["r"] or 0.0), int(row["n"] or 0)

    def product_quality_rating(self, player_id: int, product_id: int) -> tuple[float, int]:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT AVG(product_rating) r, COUNT(*) n FROM customer_experience
                   WHERE player_id=? AND product_id=?""",
                (player_id, product_id),
            ).fetchone()
        return float(row["r"] or 0.0), int(row["n"] or 0)
