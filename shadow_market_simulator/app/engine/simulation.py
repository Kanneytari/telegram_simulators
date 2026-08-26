from __future__ import annotations

from ..tutorial import hooks as tutorial_hooks

import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .core.database import Database


PRODUCTS = (
    (1, "AMPHETAMINE", "Amphetamine", 6000, 18.0, 0.95),
    (2, "MDMA", "MDMA", 8000, 10.0, 1.10),
    (3, "COCAINE", "Cocaine", 11000, 6.0, 0.90),
    (4, "MEPHEDRONE", "Mephedrone", 7000, 15.0, 1.00),
    (6, "LSD", "LSD", 9000, 7.0, 0.85),
    (7, "HASH", "Hash", 5000, 14.0, 0.90),
    (8, "WEED", "Weed", 4000, 20.0, 0.85),
)

SUPPLIERS = (
    (1, "NORTH", "Northline", 1.10, 88.0, 3.5, 0.96),
    (2, "DOCK", "Dock 17", 0.88, 72.0, 11.0, 0.82),
    (3, "ORBIT", "Orbit", 0.97, 80.0, 6.5, 0.90),
)

CLIENT_ALIASES = [
    "raven_91",
    "voidrunner",
    "pluto",
    "redfox",
    "greycat",
    "northwind",
    "mono",
    "spark",
    "dust",
    "quiet",
]


@dataclass(frozen=True)
class TickResult:
    orders_created: int = 0
    disputes_created: int = 0
    messages_created: int = 0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_dt(value: str | None) -> datetime:
    if not value:
        return utcnow()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class SimulationEngine:
    """State-driven simulation with hidden traits and observable consequences."""

    def __init__(
        self,
        db: Database,
        speed: float = 1.0,
        rng: random.Random | None = None,
    ):
        self.db = db
        self.speed = speed
        self.rng = rng or random.Random()

    def seed_catalog(self) -> None:
        """Synchronize the canonical product/supplier catalog idempotently."""
        with self.db.connect() as conn:
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
                PRODUCTS,
            )
            conn.executemany(
                """INSERT INTO suppliers(
                       id, code, title, price_modifier, quality_mean,
                       quality_sigma, reliability
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       code=excluded.code,
                       title=excluded.title,
                       price_modifier=excluded.price_modifier,
                       quality_mean=excluded.quality_mean,
                       quality_sigma=excluded.quality_sigma,
                       reliability=excluded.reliability""",
                SUPPLIERS,
            )

            # Ketamine belonged to an older catalog. Existing databases keep the row
            # for referential integrity, but it must never appear in the live market.
            conn.execute("UPDATE products SET active=0 WHERE code='KETAMINE'")
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

            # Catalog sync is also safe for databases that already contain players.
            player_ids = [
                int(row["player_id"])
                for row in conn.execute("SELECT player_id FROM shops").fetchall()
            ]
            for player_id in player_ids:
                for product_id, _, _, base_price, _, _ in PRODUCTS:
                    for pack_size, multiplier in ((1, 1.05), (2, 1.95), (5, 4.55)):
                        price = int(round(base_price * multiplier / 100.0) * 100)
                        conn.execute(
                            """INSERT OR IGNORE INTO listings(
                                   player_id, product_id, pack_size, price
                               ) VALUES (?, ?, ?, ?)""",
                            (player_id, product_id, pack_size, price),
                        )

    @tutorial_hooks.new_player_setup
    def ensure_player(self, player_id: int, username: str | None) -> bool:
        self.seed_catalog()
        now = utcnow()
        with self.db.connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM shops WHERE player_id=?", (player_id,)
            ).fetchone()
            if exists:
                conn.execute(
                    "UPDATE shops SET username=?, last_seen_at=? WHERE player_id=?",
                    (username, iso(now), player_id),
                )
                return False

            conn.execute(
                "INSERT INTO shops(player_id, username, last_simulated_at) VALUES (?, ?, ?)",
                (player_id, username, iso(now)),
            )
            conn.execute("INSERT INTO settings(player_id) VALUES (?)", (player_id,))

            employees = [
                ("Крот", "courier", 35_000, 0, 0.91, 0.88, 0.90, 0.72, 14.0),
                ("Сова", "courier", 60_000, 1, 0.84, 0.94, 0.86, 0.81, 8.0),
            ]
            for row in employees:
                conn.execute(
                    """INSERT INTO employees(
                           player_id, alias, role, deposit, has_car,
                           reliability, attention, honesty, loyalty, stress
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (player_id, *row),
                )

            for index in range(24):
                conn.execute(
                    """INSERT INTO clients(
                           player_id, alias, account_age_days, marketplace_orders,
                           fraud_propensity, patience, review_tendency
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        player_id,
                        f"{self.rng.choice(CLIENT_ALIASES)}_{index + 1}",
                        self.rng.randint(12, 1500),
                        self.rng.randint(1, 180),
                        self.rng.uniform(0.01, 0.18),
                        self.rng.uniform(0.35, 0.95),
                        self.rng.uniform(0.25, 0.85),
                    ),
                )

            for product_id, _, _, base_price, _, _ in PRODUCTS:
                for pack_size, multiplier in ((1, 1.05), (2, 1.95), (5, 4.55)):
                    price = int(round(base_price * multiplier / 100.0) * 100)
                    conn.execute(
                        "INSERT INTO listings(player_id, product_id, pack_size, price) VALUES (?, ?, ?, ?)",
                        (player_id, product_id, pack_size, price),
                    )

            starter_batches = [
                (1, 1, 80, 80, 3000, 84.0),
                (3, 2, 45, 45, 3900, 79.0),
                (1, 3, 25, 25, 5200, 90.0),
            ]
            for supplier_id, product_id, qty, remaining, unit_cost, quality in starter_batches:
                conn.execute(
                    """INSERT INTO batches(
                           player_id, supplier_id, product_id, quantity, remaining,
                           unit_cost, quality
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        player_id,
                        supplier_id,
                        product_id,
                        qty,
                        remaining,
                        unit_cost,
                        quality,
                    ),
                )

            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, note)
                   VALUES (?, 150000, 'capital', 'Стартовый капитал')""",
                (player_id,),
            )
            conn.execute(
                """INSERT INTO inbox(
                       player_id, kind, priority, title, body, payload_json, expires_at
                   ) VALUES (?, 'tutorial', 'normal', 'Смена началась',
                   'Магазин работает сам по себе. Продажи, обращения и проблемы будут возникать даже когда ты офлайн. Начни с разделов «Входящие», «Команда» и «Товар».', '{}', ?)""",
                (player_id, iso(now + timedelta(hours=12))),
            )
            return True

    def advance(self, player_id: int, now: datetime | None = None) -> TickResult:
        now = now or utcnow()
        with self.db.connect() as conn:
            shop = conn.execute(
                "SELECT * FROM shops WHERE player_id = ?", (player_id,)
            ).fetchone()
            if not shop:
                return TickResult()
            last = parse_dt(shop["last_simulated_at"])
            real_hours = max(0.0, (now - last).total_seconds() / 3600.0)
            sim_hours = min(real_hours * self.speed, 72.0)
            if sim_hours < 0.015:
                return TickResult()

            orders, disputes = self._simulate_sales(
                conn, player_id, shop, sim_hours, now
            )
            messages = self._simulate_management_events(
                conn, player_id, sim_hours, now
            )
            self._reactivate_employees(conn, player_id, now)
            self._expire_items(conn, player_id, now)
            conn.execute(
                "UPDATE shops SET last_simulated_at = ?, last_seen_at = ? WHERE player_id = ?",
                (iso(now), iso(now), player_id),
            )
            return TickResult(orders, disputes, messages)

    def advance_all(self, now: datetime | None = None) -> list[int]:
        now = now or utcnow()
        with self.db.connect() as conn:
            player_ids = [
                row[0]
                for row in conn.execute("SELECT player_id FROM shops").fetchall()
            ]
        changed: list[int] = []
        for player_id in player_ids:
            result = self.advance(player_id, now)
            if (
                result.orders_created
                or result.disputes_created
                or result.messages_created
            ):
                changed.append(player_id)
        return changed

    def _dispute_probability(
        self, client, employee, quality: float, modifier: float
    ) -> float:
        employee_error = (1.0 - float(employee["attention"])) * 0.20
        stress_error = (
            max(0.0, float(employee["stress"]) - 45.0) / 100.0 * 0.08
        )
        quality_error = max(0.0, 78.0 - quality) / 100.0 * 0.14
        fraud = float(client["fraud_propensity"]) * 0.10
        return clamp(
            (0.018 + employee_error + stress_error + quality_error + fraud) * modifier,
            0.01,
            0.32,
        )

    def _open_dispute(
        self,
        conn,
        player_id: int,
        order_id: int,
        client,
        employee,
        quality: float,
        revenue: int,
        now: datetime,
    ) -> None:
        weights = {
            "CLIENT_FRAUD": float(client["fraud_propensity"]) * 1.6 + 0.05,
            "EMPLOYEE_ERROR": (1.0 - float(employee["attention"])) * 2.0 + 0.05,
            "DESCRIPTION_ERROR": (1.0 - float(employee["attention"])) * 1.1 + 0.03,
            "QUALITY_COMPLAINT": max(0.02, (82.0 - quality) / 45.0),
            "CLIENT_ERROR": 0.12,
        }
        true_cause = self._weighted_choice(weights)
        messages = {
            "CLIENT_FRAUD": "Не нашёл заказ. Всё проверил несколько раз. Прошу вернуть оплату.",
            "EMPLOYEE_ERROR": "По описанию ничего нет. Похоже, в заказе ошибка.",
            "DESCRIPTION_ERROR": "Описание слишком неточное, разобраться на месте невозможно.",
            "QUALITY_COMPLAINT": "Заказ получен, но качество заметно хуже обычного. Хочу компенсацию.",
            "CLIENT_ERROR": "Не получается найти заказ по указанной информации. Нужна помощь.",
        }
        evidence = {
            "description_present": self.rng.random()
            > (0.45 if true_cause == "DESCRIPTION_ERROR" else 0.08),
            "extra_material_present": self.rng.random() > 0.35,
            "client_tone": self.rng.choice(
                ["спокойный", "раздражённый", "настойчивый"]
            ),
            "order_value": revenue,
        }
        hardcore = conn.execute(
            "SELECT hardcore FROM settings WHERE player_id = ?", (player_id,)
        ).fetchone()[0]
        deadline_minutes = 15 if hardcore else 120
        deadline = now + timedelta(minutes=deadline_minutes)
        cur = conn.execute(
            """INSERT INTO disputes(
                   player_id, order_id, true_cause, message, evidence_json, deadline_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                player_id,
                order_id,
                true_cause,
                messages[true_cause],
                json.dumps(evidence, ensure_ascii=False),
                iso(deadline),
            ),
        )
        dispute_id = cur.lastrowid
        conn.execute(
            "UPDATE orders SET status = 'disputed' WHERE id = ?", (order_id,)
        )
        conn.execute(
            "UPDATE employees SET disputes = disputes + 1 WHERE id = ?",
            (employee["id"],),
        )
        conn.execute(
            "UPDATE clients SET disputes_total = disputes_total + 1 WHERE id = ?",
            (client["id"],),
        )
        conn.execute(
            """INSERT INTO inbox(
                   player_id, kind, priority, title, body, payload_json, expires_at
               ) VALUES (?, 'dispute', 'important', ?, ?, ?, ?)""",
            (
                player_id,
                f"Диспут #{dispute_id}",
                f"Клиент {client['alias']}: {messages[true_cause]}",
                json.dumps({"dispute_id": dispute_id}, ensure_ascii=False),
                iso(deadline),
            ),
        )

    def _simulate_management_events(
        self, conn, player_id: int, sim_hours: float, now: datetime
    ) -> int:
        return 0

    def _reactivate_employees(self, conn, player_id: int, now: datetime) -> None:
        conn.execute(
            """UPDATE employees SET available = 1, unavailable_until = NULL
               WHERE player_id = ? AND active = 1 AND available = 0
               AND unavailable_until IS NOT NULL AND unavailable_until <= ?""",
            (player_id, iso(now)),
        )

    def _expire_items(self, conn, player_id: int, now: datetime) -> None:
        expired = conn.execute(
            """SELECT * FROM inbox
               WHERE player_id = ? AND status = 'open'
                 AND expires_at IS NOT NULL AND expires_at < ?""",
            (player_id, iso(now)),
        ).fetchall()
        for item in expired:
            if item["kind"] == "dispute":
                payload = json.loads(item["payload_json"])
                dispute = conn.execute(
                    "SELECT * FROM disputes WHERE id = ?", (payload["dispute_id"],)
                ).fetchone()
                if dispute and dispute["status"] == "open":
                    order = conn.execute(
                        "SELECT * FROM orders WHERE id = ?", (dispute["order_id"],)
                    ).fetchone()
                    refund = int(order["revenue"] * 0.5)
                    self._apply_refund(
                        conn, player_id, order, refund, "auto_partial"
                    )
                    conn.execute(
                        """UPDATE disputes
                           SET status = 'resolved', decision = 'auto_partial', resolved_at = ?
                           WHERE id = ?""",
                        (iso(now), dispute["id"]),
                    )
            conn.execute(
                "UPDATE inbox SET status = 'expired' WHERE id = ?", (item["id"],)
            )

        conn.execute(
            """UPDATE supplier_offers SET status = 'expired'
               WHERE player_id = ? AND status = 'open' AND expires_at < ?""",
            (player_id, iso(now)),
        )
        conn.execute(
            """UPDATE candidates SET status = 'expired'
               WHERE player_id = ? AND status = 'open' AND expires_at < ?""",
            (player_id, iso(now)),
        )

    def _has_stock(self, conn, player_id: int, product_id: int, qty: int) -> bool:
        available = conn.execute(
            """SELECT COALESCE(SUM(remaining), 0) FROM batches
               WHERE player_id = ? AND product_id = ? AND status = 'warehouse'""",
            (player_id, product_id),
        ).fetchone()[0]
        return available >= qty

    def _apply_refund(
        self, conn, player_id: int, order, refund: int, decision: str
    ) -> None:
        refund = min(refund, order["revenue"])
        conn.execute(
            """UPDATE shops
               SET balance = balance - ?, total_profit = total_profit - ?
               WHERE player_id = ?""",
            (refund, refund, player_id),
        )
        conn.execute(
            """INSERT INTO ledger(
                   player_id, amount, kind, reference_type, reference_id, note)
               ) VALUES (?, ?, 'refund', 'order', ?, ?)""",
            (
                player_id,
                -refund,
                order["id"],
                f"Компенсация по заказу #{order['id']} ({decision})",
            ),
        )

    def _poisson(self, lam: float) -> int:
        if lam <= 0:
            return 0
        if lam > 20:
            return max(0, int(round(self.rng.gauss(lam, math.sqrt(lam)))))
        threshold = math.exp(-lam)
        p = 1.0
        k = 0
        while p > threshold:
            k += 1
            p *= self.rng.random()
        return k - 1

    def _weighted_choice(self, weights: dict[str, float]) -> str:
        total = sum(max(0.0, value) for value in weights.values())
        pick = self.rng.random() * total
        upto = 0.0
        for key, value in weights.items():
            upto += max(0.0, value)
            if pick <= upto:
                return key
        return next(iter(weights))
