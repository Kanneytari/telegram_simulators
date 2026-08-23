from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .db import Database


PRODUCTS = (
    (1, "NEON", "Neon", 1450, 18.0, 0.9),
    (2, "AMBER", "Amber", 2050, 10.0, 1.1),
    (3, "ECHO", "Echo", 3100, 6.0, 1.3),
)

SUPPLIERS = (
    (1, "NORTH", "Northline", 1.10, 88.0, 3.5, 0.96),
    (2, "DOCK", "Dock 17", 0.88, 72.0, 11.0, 0.82),
    (3, "ORBIT", "Orbit", 0.97, 80.0, 6.5, 0.90),
)

ALIASES = ["Крот", "Сова", "Лис", "Маяк", "Ворон", "Тень", "Мята", "Риф", "Пульс", "Шум"]
CLIENT_ALIASES = ["raven_91", "voidrunner", "pluto", "redfox", "greycat", "northwind", "mono", "spark", "dust", "quiet"]


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
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class SimulationEngine:
    """State-driven simulation. Hidden traits create observable statistics; the player never sees them directly."""

    def __init__(self, db: Database, speed: float = 1.0, rng: random.Random | None = None):
        self.db = db
        self.speed = speed
        self.rng = rng or random.Random()

    def seed_catalog(self) -> None:
        with self.db.connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO products(id, code, title, base_market_price, base_demand, complaint_modifier) VALUES (?, ?, ?, ?, ?, ?)",
                PRODUCTS,
            )
            conn.executemany(
                "INSERT OR IGNORE INTO suppliers(id, code, title, price_modifier, quality_mean, quality_sigma, reliability) VALUES (?, ?, ?, ?, ?, ?, ?)",
                SUPPLIERS,
            )

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        """Create a new shop and starter state. Returns True only on first creation."""
        self.seed_catalog()
        now = utcnow()
        with self.db.connect() as conn:
            exists = conn.execute("SELECT 1 FROM shops WHERE player_id = ?", (player_id,)).fetchone()
            if exists:
                conn.execute(
                    "UPDATE shops SET username = ?, last_seen_at = ? WHERE player_id = ?",
                    (username, iso(now), player_id),
                )
                return False

            conn.execute(
                "INSERT INTO shops(player_id, username, last_simulated_at) VALUES (?, ?, ?)",
                (player_id, username, iso(now)),
            )
            conn.execute("INSERT INTO settings(player_id) VALUES (?)", (player_id,))

            employees = [
                ("Крот", "courier", 170, 35000, 0, 0.91, 0.88, 0.90, 0.72, 14.0),
                ("Сова", "courier", 205, 60000, 1, 0.84, 0.94, 0.86, 0.81, 8.0),
            ]
            for row in employees:
                conn.execute(
                    """INSERT INTO employees(
                        player_id, alias, role, pay_per_job, deposit, has_car,
                        reliability, attention, honesty, loyalty, stress
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (player_id, *row),
                )

            for index in range(24):
                account_age = self.rng.randint(12, 1500)
                marketplace_orders = self.rng.randint(1, 180)
                conn.execute(
                    """INSERT INTO clients(
                        player_id, alias, account_age_days, marketplace_orders,
                        fraud_propensity, patience, loyalty, review_tendency
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        player_id,
                        f"{self.rng.choice(CLIENT_ALIASES)}_{index + 1}",
                        account_age,
                        marketplace_orders,
                        self.rng.uniform(0.01, 0.18),
                        self.rng.uniform(0.35, 0.95),
                        self.rng.uniform(0.25, 0.90),
                        self.rng.uniform(0.25, 0.85),
                    ),
                )

            for product_id, _, _, base_price, _, _ in PRODUCTS:
                conn.execute(
                    "INSERT INTO listings(player_id, product_id, pack_size, price) VALUES (?, ?, 1, ?)",
                    (player_id, product_id, int(base_price * 1.05)),
                )
                conn.execute(
                    "INSERT INTO listings(player_id, product_id, pack_size, price) VALUES (?, ?, 2, ?)",
                    (player_id, product_id, int(base_price * 1.95)),
                )
                conn.execute(
                    "INSERT INTO listings(player_id, product_id, pack_size, price) VALUES (?, ?, 5, ?)",
                    (player_id, product_id, int(base_price * 4.55)),
                )

            starter_batches = [
                (1, 1, 80, 80, 770, 84.0),
                (3, 2, 45, 45, 1180, 79.0),
                (1, 3, 25, 25, 1880, 90.0),
            ]
            for supplier_id, product_id, qty, remaining, unit_cost, quality in starter_batches:
                conn.execute(
                    """INSERT INTO batches(
                        player_id, supplier_id, product_id, quantity, remaining, unit_cost, quality
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (player_id, supplier_id, product_id, qty, remaining, unit_cost, quality),
                )

            conn.execute(
                "INSERT INTO ledger(player_id, amount, kind, note) VALUES (?, 150000, 'capital', 'Стартовый капитал')",
                (player_id,),
            )
            self._create_offer(conn, player_id, now)
            self._create_candidate(conn, player_id, now)
            conn.execute(
                """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
                   VALUES (?, 'tutorial', 'normal', 'Смена началась',
                   'Магазин работает сам по себе. Продажи, обращения и проблемы будут возникать даже когда ты офлайн. Начни с разделов «Входящие», «Команда» и «Закупки».', '{}', ?)""",
                (player_id, iso(now + timedelta(hours=12))),
            )
            return True

    def advance(self, player_id: int, now: datetime | None = None) -> TickResult:
        now = now or utcnow()
        with self.db.connect() as conn:
            shop = conn.execute("SELECT * FROM shops WHERE player_id = ?", (player_id,)).fetchone()
            if not shop:
                return TickResult()
            last = parse_dt(shop["last_simulated_at"])
            real_hours = max(0.0, (now - last).total_seconds() / 3600.0)
            # Prevent one long absence from exploding into thousands of rows.
            sim_hours = min(real_hours * self.speed, 72.0)
            if sim_hours < 0.015:
                return TickResult()

            orders, disputes = self._simulate_sales(conn, player_id, shop, sim_hours, now)
            messages = self._simulate_management_events(conn, player_id, sim_hours, now)
            self._reactivate_employees(conn, player_id, now)
            self._expire_items(conn, player_id, now)
            self._maybe_refresh_offer(conn, player_id, now)
            self._maybe_refresh_candidate(conn, player_id, now)
            conn.execute(
                "UPDATE shops SET last_simulated_at = ?, last_seen_at = ? WHERE player_id = ?",
                (iso(now), iso(now), player_id),
            )
            return TickResult(orders, disputes, messages)

    def advance_all(self, now: datetime | None = None) -> list[int]:
        now = now or utcnow()
        with self.db.connect() as conn:
            player_ids = [row[0] for row in conn.execute("SELECT player_id FROM shops").fetchall()]
        changed: list[int] = []
        for player_id in player_ids:
            result = self.advance(player_id, now)
            if result.orders_created or result.disputes_created or result.messages_created:
                changed.append(player_id)
        return changed

    def _simulate_sales(self, conn, player_id: int, shop, sim_hours: float, now: datetime) -> tuple[int, int]:
        listings = conn.execute(
            """SELECT l.*, p.base_market_price, p.base_demand, p.complaint_modifier
               FROM listings l JOIN products p ON p.id = l.product_id
               WHERE l.player_id = ? AND l.active = 1""",
            (player_id,),
        ).fetchall()
        employees = conn.execute(
            "SELECT * FROM employees WHERE player_id = ? AND active = 1 AND available = 1 AND role = 'courier'",
            (player_id,),
        ).fetchall()
        if not employees:
            return 0, 0

        rating_effect = clamp(0.70 + (float(shop["rating"]) - 4.0) * 0.55, 0.55, 1.25)
        orders_created = 0
        disputes_created = 0

        for listing in listings:
            available = conn.execute(
                "SELECT COALESCE(SUM(remaining), 0) FROM batches WHERE player_id = ? AND product_id = ? AND status = 'warehouse'",
                (player_id, listing["product_id"]),
            ).fetchone()[0]
            if available < listing["pack_size"]:
                continue
            unit_price = listing["price"] / listing["pack_size"]
            price_ratio = unit_price / listing["base_market_price"]
            price_effect = clamp(math.exp(-2.2 * (price_ratio - 1.0)), 0.35, 1.55)
            pack_effect = {1: 1.0, 2: 0.68, 5: 0.28}.get(listing["pack_size"], 0.2)
            expected = (listing["base_demand"] / 24.0) * sim_hours * rating_effect * price_effect * pack_effect
            count = self._poisson(expected)
            for _ in range(count):
                if not self._has_stock(conn, player_id, listing["product_id"], listing["pack_size"]):
                    break
                employee = self.rng.choice(employees)
                dispute = self._create_order(conn, player_id, listing, employee, now)
                orders_created += 1
                disputes_created += int(dispute)
        return orders_created, disputes_created

    def _create_order(self, conn, player_id: int, listing, employee, now: datetime) -> bool:
        client = conn.execute(
            "SELECT * FROM clients WHERE player_id = ? ORDER BY RANDOM() LIMIT 1", (player_id,)
        ).fetchone()
        batch = conn.execute(
            """SELECT * FROM batches WHERE player_id = ? AND product_id = ? AND status = 'warehouse'
               AND remaining >= ? ORDER BY acquired_at LIMIT 1""",
            (player_id, listing["product_id"], listing["pack_size"]),
        ).fetchone()
        if not client or not batch:
            return False

        qty = int(listing["pack_size"])
        revenue = int(listing["price"])
        cost = int(batch["unit_cost"] * qty)
        employee_cost = int(employee["pay_per_job"])
        quality = float(batch["quality"])
        conn.execute("UPDATE batches SET remaining = remaining - ? WHERE id = ?", (qty, batch["id"]))
        conn.execute(
            """UPDATE employees SET jobs_done = jobs_done + 1,
               stress = MIN(100, stress + ?), last_contact_at = ? WHERE id = ?""",
            (self.rng.uniform(0.05, 0.35), iso(now), employee["id"]),
        )
        conn.execute(
            """UPDATE clients SET shop_orders = shop_orders + 1, marketplace_orders = marketplace_orders + 1,
               total_spend = total_spend + ? WHERE id = ?""",
            (revenue, client["id"]),
        )
        cur = conn.execute(
            """INSERT INTO orders(player_id, client_id, employee_id, batch_id, product_id, quantity,
               revenue, cost, employee_cost, quality) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (player_id, client["id"], employee["id"], batch["id"], listing["product_id"], qty, revenue, cost, employee_cost, quality),
        )
        order_id = cur.lastrowid
        profit = revenue - cost - employee_cost
        conn.execute(
            """UPDATE shops SET balance = balance + ?, total_revenue = total_revenue + ?,
               total_profit = total_profit + ?, total_orders = total_orders + 1 WHERE player_id = ?""",
            (revenue - employee_cost, revenue, profit, player_id),
        )
        conn.execute(
            "INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note) VALUES (?, ?, 'sale', 'order', ?, ?)",
            (player_id, revenue - employee_cost, order_id, f"Заказ #{order_id}"),
        )

        dispute_probability = self._dispute_probability(client, employee, quality, float(listing["complaint_modifier"]))
        if self.rng.random() < dispute_probability:
            self._open_dispute(conn, player_id, order_id, client, employee, quality, revenue, now)
            return True
        return False

    def _dispute_probability(self, client, employee, quality: float, modifier: float) -> float:
        employee_error = (1.0 - float(employee["attention"])) * 0.20
        stress_error = max(0.0, float(employee["stress"]) - 45.0) / 100.0 * 0.08
        quality_error = max(0.0, 78.0 - quality) / 100.0 * 0.14
        fraud = float(client["fraud_propensity"]) * 0.10
        return clamp((0.018 + employee_error + stress_error + quality_error + fraud) * modifier, 0.01, 0.32)

    def _open_dispute(self, conn, player_id: int, order_id: int, client, employee, quality: float, revenue: int, now: datetime) -> None:
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
            "description_present": self.rng.random() > (0.45 if true_cause == "DESCRIPTION_ERROR" else 0.08),
            "extra_material_present": self.rng.random() > 0.35,
            "client_tone": self.rng.choice(["спокойный", "раздражённый", "настойчивый"]),
            "order_value": revenue,
        }
        deadline_minutes = 15 if conn.execute("SELECT hardcore FROM settings WHERE player_id = ?", (player_id,)).fetchone()[0] else 120
        deadline = now + timedelta(minutes=deadline_minutes)
        cur = conn.execute(
            """INSERT INTO disputes(player_id, order_id, true_cause, message, evidence_json, deadline_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (player_id, order_id, true_cause, messages[true_cause], json.dumps(evidence, ensure_ascii=False), iso(deadline)),
        )
        dispute_id = cur.lastrowid
        conn.execute("UPDATE orders SET status = 'disputed' WHERE id = ?", (order_id,))
        conn.execute("UPDATE employees SET disputes = disputes + 1 WHERE id = ?", (employee["id"],))
        conn.execute("UPDATE clients SET disputes_total = disputes_total + 1 WHERE id = ?", (client["id"],))
        conn.execute(
            """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
               VALUES (?, 'dispute', 'important', ?, ?, ?, ?)""",
            (
                player_id,
                f"Диспут #{dispute_id}",
                f"Клиент {client['alias']}: {messages[true_cause]}",
                json.dumps({"dispute_id": dispute_id}, ensure_ascii=False),
                iso(deadline),
            ),
        )

    def _simulate_management_events(self, conn, player_id: int, sim_hours: float, now: datetime) -> int:
        created = 0
        # A small chance per simulated hour, capped so returning after a long break does not flood the inbox.
        chances = min(sim_hours, 12.0)
        if self.rng.random() < 1 - math.exp(-0.055 * chances):
            employee = conn.execute(
                "SELECT * FROM employees WHERE player_id = ? AND active = 1 ORDER BY RANDOM() LIMIT 1", (player_id,)
            ).fetchone()
            if employee:
                kind = self.rng.choice(["raise_request", "leave_request", "advance_request"])
                payload = {"employee_id": employee["id"]}
                if kind == "raise_request":
                    body = f"{employee['alias']}: работаю уже не первую смену на старых условиях. Можно пересмотреть ставку?"
                    title = "Разговор об оплате"
                elif kind == "leave_request":
                    body = f"{employee['alias']}: нужно несколько дней без нагрузки по личным причинам."
                    title = "Просьба о паузе"
                else:
                    amount = min(12000, max(2000, int(employee["deposit"] * 0.12)))
                    payload["amount"] = amount
                    body = f"{employee['alias']}: можно временно высвободить {amount:,} ₽ из моего обеспечения?"
                    title = "Запрос сотрудника"
                expires = now + timedelta(hours=4)
                conn.execute(
                    """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
                       VALUES (?, ?, 'normal', ?, ?, ?, ?)""",
                    (player_id, kind, title, body, json.dumps(payload, ensure_ascii=False), iso(expires)),
                )
                created += 1

        if self.rng.random() < 1 - math.exp(-0.035 * chances):
            client = conn.execute(
                "SELECT * FROM clients WHERE player_id = ? AND shop_orders > 0 ORDER BY RANDOM() LIMIT 1", (player_id,)
            ).fetchone()
            if client:
                percent = self.rng.choice([2, 3, 4, 5])
                conn.execute(
                    """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
                       VALUES (?, 'discount_request', 'important', 'Просьба постоянного клиента', ?, ?, ?)""",
                    (
                        player_id,
                        f"{client['alias']}: из-за изменения курса не хватает совсем немного. Можешь дать скидку {percent}%?",
                        json.dumps({"client_id": client["id"], "percent": percent}, ensure_ascii=False),
                        iso(now + timedelta(minutes=45)),
                    ),
                )
                created += 1
        # Low loyalty and high stress can end employment without waiting for a scripted quest.
        employees = conn.execute(
            "SELECT * FROM employees WHERE player_id=? AND active=1", (player_id,)
        ).fetchall()
        for employee in employees:
            loyalty_risk = max(0.0, 0.62 - float(employee["loyalty"])) * 0.028 * min(sim_hours, 12.0)
            stress_risk = max(0.0, float(employee["stress"]) - 70.0) / 100.0 * 0.025 * min(sim_hours, 12.0)
            if self.rng.random() >= loyalty_risk + stress_risk:
                continue
            dishonest_exit = self.rng.random() > float(employee["honesty"])
            if dishonest_exit:
                gross_loss = self.rng.randint(12000, 65000)
                covered = min(int(employee["deposit"]), gross_loss)
                net_loss = gross_loss - covered
                conn.execute(
                    "UPDATE employees SET active=0, available=0, losses=losses+?, deposit=0 WHERE id=?",
                    (gross_loss, employee["id"]),
                )
                if net_loss:
                    conn.execute("UPDATE shops SET balance=balance-?, total_profit=total_profit-? WHERE player_id=?", (net_loss, net_loss, player_id))
                    conn.execute(
                        "INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note) VALUES (?, ?, 'employee_loss', 'employee', ?, ?)",
                        (player_id, -net_loss, employee["id"], f"Потери после ухода {employee['alias']}"),
                    )
                body = (
                    f"{employee['alias']} перестал выходить на связь. Зафиксирован риск на {gross_loss:,} ₽; "
                    f"обеспечение закрыло {covered:,} ₽. Чистая потеря магазина: {net_loss:,} ₽."
                )
                title = "Сотрудник пропал со связи"
                priority = "urgent"
            else:
                deposit = int(employee["deposit"])
                conn.execute(
                    "UPDATE employees SET active=0, available=0, deposit=0 WHERE id=?", (employee["id"],)
                )
                conn.execute("UPDATE shops SET balance=balance-? WHERE player_id=?", (deposit, player_id))
                conn.execute(
                    "INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note) VALUES (?, ?, 'deposit_out', 'employee', ?, ?)",
                    (player_id, -deposit, employee["id"], f"Возврат обеспечения при уходе {employee['alias']}"),
                )
                body = f"{employee['alias']} сообщил об уходе. Обеспечение {deposit:,} ₽ возвращено, производственная мощность снизилась."
                title = "Сотрудник ушёл"
                priority = "important"
            conn.execute(
                "INSERT INTO inbox(player_id, kind, priority, title, body, payload_json) VALUES (?, 'employee_exit', ?, ?, ?, '{}')",
                (player_id, priority, title, body),
            )
            created += 1
            break
        return created

    def _reactivate_employees(self, conn, player_id: int, now: datetime) -> None:
        conn.execute(
            """UPDATE employees SET available = 1, unavailable_until = NULL
               WHERE player_id = ? AND active = 1 AND available = 0
               AND unavailable_until IS NOT NULL AND unavailable_until <= ?""",
            (player_id, iso(now)),
        )

    def _expire_items(self, conn, player_id: int, now: datetime) -> None:
        expired = conn.execute(
            "SELECT * FROM inbox WHERE player_id = ? AND status = 'open' AND expires_at IS NOT NULL AND expires_at < ?",
            (player_id, iso(now)),
        ).fetchall()
        for item in expired:
            if item["kind"] == "dispute":
                payload = json.loads(item["payload_json"])
                dispute = conn.execute("SELECT * FROM disputes WHERE id = ?", (payload["dispute_id"],)).fetchone()
                if dispute and dispute["status"] == "open":
                    # Platform default: partial refund. Missing a message has a measurable cost, but does not end the run.
                    order = conn.execute("SELECT * FROM orders WHERE id = ?", (dispute["order_id"],)).fetchone()
                    refund = int(order["revenue"] * 0.5)
                    self._apply_refund(conn, player_id, order, refund, "auto_partial")
                    conn.execute(
                        "UPDATE disputes SET status = 'resolved', decision = 'auto_partial', resolved_at = ? WHERE id = ?",
                        (iso(now), dispute["id"]),
                    )
            conn.execute("UPDATE inbox SET status = 'expired' WHERE id = ?", (item["id"],))

        conn.execute(
            "UPDATE supplier_offers SET status = 'expired' WHERE player_id = ? AND status = 'open' AND expires_at < ?",
            (player_id, iso(now)),
        )
        conn.execute(
            "UPDATE candidates SET status = 'expired' WHERE player_id = ? AND status = 'open' AND expires_at < ?",
            (player_id, iso(now)),
        )

    def _maybe_refresh_offer(self, conn, player_id: int, now: datetime) -> None:
        count = conn.execute(
            "SELECT COUNT(*) FROM supplier_offers WHERE player_id = ? AND status = 'open'", (player_id,)
        ).fetchone()[0]
        if count < 2:
            self._create_offer(conn, player_id, now)

    def _create_offer(self, conn, player_id: int, now: datetime) -> None:
        supplier = conn.execute("SELECT * FROM suppliers ORDER BY RANDOM() LIMIT 1").fetchone()
        product = conn.execute("SELECT * FROM products ORDER BY RANDOM() LIMIT 1").fetchone()
        qty = self.rng.choice([50, 100, 200, 400])
        volume_discount = {50: 1.00, 100: 0.93, 200: 0.86, 400: 0.78}[qty]
        wholesale_base = product["base_market_price"] * 0.56
        unit_cost = int(wholesale_base * supplier["price_modifier"] * volume_discount)
        quality_hint = "стабильное" if supplier["quality_sigma"] < 5 else "с переменным качеством" if supplier["quality_sigma"] > 9 else "обычное"
        conn.execute(
            """INSERT INTO supplier_offers(player_id, supplier_id, product_id, quantity, unit_cost, quality_hint, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (player_id, supplier["id"], product["id"], qty, unit_cost, quality_hint, iso(now + timedelta(hours=8))),
        )

    def _maybe_refresh_candidate(self, conn, player_id: int, now: datetime) -> None:
        count = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE player_id = ? AND status = 'open'", (player_id,)
        ).fetchone()[0]
        if count < 2:
            self._create_candidate(conn, player_id, now)

    def _create_candidate(self, conn, player_id: int, now: datetime) -> None:
        alias = self.rng.choice(ALIASES) + str(self.rng.randint(2, 99))
        role = "courier"
        reliability = self.rng.uniform(0.60, 0.97)
        attention = self.rng.uniform(0.58, 0.98)
        honesty = self.rng.uniform(0.55, 0.99)
        loyalty = self.rng.uniform(0.45, 0.90)
        desired = int(145 + (reliability + attention) * 55 + self.rng.randint(-20, 30))
        deposit = self.rng.choice([15000, 25000, 40000, 60000, 90000])
        has_car = int(self.rng.random() < 0.42)
        experience = self.rng.choice(["без опыта", "есть небольшой опыт", "говорит, что работал раньше"])
        summary = f"{experience}; {'есть автомобиль' if has_car else 'без автомобиля'}; готовое обеспечение {deposit:,} ₽"
        conn.execute(
            """INSERT INTO candidates(player_id, alias, role, desired_pay, deposit, has_car,
               reliability, attention, honesty, loyalty, summary, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (player_id, alias, role, desired, deposit, has_car, reliability, attention, honesty, loyalty, summary, iso(now + timedelta(hours=10))),
        )

    def _has_stock(self, conn, player_id: int, product_id: int, qty: int) -> bool:
        available = conn.execute(
            "SELECT COALESCE(SUM(remaining), 0) FROM batches WHERE player_id = ? AND product_id = ? AND status = 'warehouse'",
            (player_id, product_id),
        ).fetchone()[0]
        return available >= qty

    def _apply_refund(self, conn, player_id: int, order, refund: int, decision: str) -> None:
        refund = min(refund, order["revenue"])
        conn.execute("UPDATE shops SET balance = balance - ?, total_profit = total_profit - ? WHERE player_id = ?", (refund, refund, player_id))
        conn.execute(
            "INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note) VALUES (?, ?, 'refund', 'order', ?, ?)",
            (player_id, -refund, order["id"], f"Компенсация по заказу #{order['id']} ({decision})"),
        )

    def _poisson(self, lam: float) -> int:
        if lam <= 0:
            return 0
        if lam > 20:
            # Normal approximation is enough for aggregate simulation.
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
