from __future__ import annotations

import json
import math
from datetime import timedelta

from .operations import OperationsGameService, OperationsSimulationEngine
from .runtime import ROLE_MARKET_PAY
from .simulation import clamp, iso, parse_dt, utcnow


WORKFLOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS employee_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    batch_id INTEGER REFERENCES batches(id),
    allocation_id INTEGER,
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completes_at TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS retail_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    wholesale_employee_id INTEGER NOT NULL REFERENCES employees(id),
    retail_employee_id INTEGER NOT NULL REFERENCES employees(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_cost INTEGER NOT NULL,
    quality REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    received_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS retail_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    allocation_id INTEGER NOT NULL REFERENCES retail_allocations(id) ON DELETE CASCADE,
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    pack_size INTEGER NOT NULL,
    position_count INTEGER NOT NULL,
    unit_cost INTEGER NOT NULL,
    quality REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(allocation_id, pack_size)
);

CREATE TABLE IF NOT EXISTS shop_packaging_rules (
    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
    pct_1 INTEGER NOT NULL DEFAULT 60,
    pct_2 INTEGER NOT NULL DEFAULT 30,
    pct_5 INTEGER NOT NULL DEFAULT 10,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tasks_player_active ON employee_tasks(player_id, status, completes_at);
CREATE INDEX IF NOT EXISTS idx_tasks_employee_active ON employee_tasks(employee_id, status);
CREATE INDEX IF NOT EXISTS idx_allocations_retail_status ON retail_allocations(player_id, retail_employee_id, status);
CREATE INDEX IF NOT EXISTS idx_positions_product_pack ON retail_positions(player_id, product_id, pack_size, position_count);
CREATE INDEX IF NOT EXISTS idx_positions_employee ON retail_positions(player_id, employee_id, position_count);
"""


TASK_LABELS = {
    "receive_batch": "принимает партию",
    "handoff": "готовит передачу рознице",
    "prepare_positions": "готовит позиции",
}


class WorkflowSimulationEngine(OperationsSimulationEngine):
    """Stateful employee workflow with explicit inventory accountability."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(WORKFLOW_SCHEMA)

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        self._ensure_packaging_rules(player_id)
        if created:
            self._seed_retail_positions(player_id)
        return created

    def _ensure_packaging_rules(self, player_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO shop_packaging_rules(player_id) VALUES (?)",
                (player_id,),
            )

    def _seed_retail_positions(self, player_id: int) -> None:
        with self.db.connect() as conn:
            couriers = conn.execute(
                "SELECT * FROM employees WHERE player_id=? AND active=1 AND role='courier' ORDER BY id",
                (player_id,),
            ).fetchall()
            if not couriers:
                return
            batches = conn.execute(
                """SELECT * FROM batches
                   WHERE player_id=? AND status='warehouse' AND remaining>0
                   ORDER BY id""",
                (player_id,),
            ).fetchall()
            for index, batch in enumerate(batches):
                qty = min(18, max(0, int(batch["remaining"]) // 3))
                if qty <= 0:
                    continue
                courier = couriers[index % len(couriers)]
                conn.execute("UPDATE batches SET remaining=remaining-? WHERE id=?", (qty, batch["id"]))
                cur = conn.execute(
                    """INSERT INTO retail_allocations(
                           player_id, batch_id, wholesale_employee_id, retail_employee_id,
                           product_id, quantity, unit_cost, quality, status, received_at, completed_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    (
                        player_id,
                        batch["id"],
                        batch["responsible_employee_id"],
                        courier["id"],
                        batch["product_id"],
                        qty,
                        batch["unit_cost"],
                        batch["quality"],
                    ),
                )
                self._publish_allocation(conn, player_id, int(cur.lastrowid))

    def _publish_allocation(self, conn, player_id: int, allocation_id: int) -> None:
        allocation = conn.execute(
            "SELECT * FROM retail_allocations WHERE id=? AND player_id=?",
            (allocation_id, player_id),
        ).fetchone()
        if not allocation or allocation["quantity"] <= 0:
            return

        conn.execute(
            "INSERT OR IGNORE INTO shop_packaging_rules(player_id) VALUES (?)",
            (player_id,),
        )
        rule = conn.execute(
            "SELECT pct_1, pct_2, pct_5 FROM shop_packaging_rules WHERE player_id=?",
            (player_id,),
        ).fetchone()

        qty = int(allocation["quantity"])
        units5 = int(qty * int(rule["pct_5"]) / 100)
        count5 = units5 // 5
        remaining = qty - count5 * 5
        units2 = min(remaining, int(qty * int(rule["pct_2"]) / 100))
        count2 = units2 // 2
        remaining -= count2 * 2
        count1 = remaining
        for pack_size, count in ((1, count1), (2, count2), (5, count5)):
            if count <= 0:
                continue
            conn.execute(
                """INSERT INTO retail_positions(
                       player_id, allocation_id, batch_id, employee_id, product_id,
                       pack_size, position_count, unit_cost, quality
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(allocation_id, pack_size)
                   DO UPDATE SET position_count=excluded.position_count""",
                (
                    player_id,
                    allocation_id,
                    allocation["batch_id"],
                    allocation["retail_employee_id"],
                    allocation["product_id"],
                    pack_size,
                    count,
                    allocation["unit_cost"],
                    allocation["quality"],
                ),
            )
        conn.execute(
            "UPDATE retail_allocations SET status='published', completed_at=CURRENT_TIMESTAMP WHERE id=?",
            (allocation_id,),
        )

    def _game_hours_to_real(self, player_id: int, hours: float) -> timedelta:
        return timedelta(hours=max(0.05, hours) / self.effective_speed(player_id))

    def _process_tasks(self, conn, player_id: int, now) -> int:
        completed = 0
        tasks = conn.execute(
            """SELECT * FROM employee_tasks
               WHERE player_id=? AND status='active' AND completes_at<=?
               ORDER BY completes_at, id""",
            (player_id, iso(now)),
        ).fetchall()
        for task in tasks:
            employee = conn.execute("SELECT * FROM employees WHERE id=?", (task["employee_id"],)).fetchone()
            if not employee or not employee["active"]:
                conn.execute("UPDATE employee_tasks SET status='cancelled' WHERE id=?", (task["id"],))
                continue
            if task["kind"] == "receive_batch":
                conn.execute(
                    "UPDATE batches SET status='warehouse' WHERE id=? AND player_id=? AND status='receiving'",
                    (task["batch_id"], player_id),
                )
            elif task["kind"] == "handoff":
                allocation = conn.execute(
                    "SELECT * FROM retail_allocations WHERE id=? AND player_id=? AND status='waiting'",
                    (task["allocation_id"], player_id),
                ).fetchone()
                if allocation:
                    retail = conn.execute(
                        """SELECT * FROM employees
                           WHERE id=? AND player_id=? AND active=1 AND role='courier'""",
                        (allocation["retail_employee_id"], player_id),
                    ).fetchone()
                    if retail:
                        conn.execute(
                            "UPDATE retail_allocations SET status='preparing', received_at=? WHERE id=?",
                            (iso(now), allocation["id"]),
                        )
                        game_hours = 0.8 + int(allocation["quantity"]) / 18.0 * 0.7 + (1.0 - float(retail["reliability"])) * 2.0
                        conn.execute(
                            """INSERT INTO employee_tasks(
                                   player_id, employee_id, kind, batch_id, allocation_id,
                                   product_id, quantity, completes_at, note
                               ) VALUES (?, ?, 'prepare_positions', ?, ?, ?, ?, ?, ?)""",
                            (
                                player_id,
                                retail["id"],
                                allocation["batch_id"],
                                allocation["id"],
                                allocation["product_id"],
                                allocation["quantity"],
                                iso(now + self._game_hours_to_real(player_id, game_hours)),
                                "Подготовка розничных позиций",
                            ),
                        )
                    else:
                        conn.execute("UPDATE retail_allocations SET status='blocked' WHERE id=?", (allocation["id"],))
            elif task["kind"] == "prepare_positions":
                self._publish_allocation(conn, player_id, int(task["allocation_id"]))
            conn.execute("UPDATE employee_tasks SET status='completed' WHERE id=?", (task["id"],))
            completed += 1
        return completed

    def _simulate_sales(self, conn, player_id: int, shop, sim_hours: float, now) -> tuple[int, int]:
        self._process_tasks(conn, player_id, now)
        listings = conn.execute(
            """SELECT l.*, p.base_market_price, p.base_demand, p.complaint_modifier
               FROM listings l JOIN products p ON p.id=l.product_id
               WHERE l.player_id=? AND l.active=1""",
            (player_id,),
        ).fetchall()
        rating_effect = clamp(0.70 + (float(shop["rating"]) - 4.0) * 0.55, 0.55, 1.25)
        orders_created = 0
        disputes_created = 0
        for listing in listings:
            available_positions = int(conn.execute(
                """SELECT COALESCE(SUM(rp.position_count),0)
                   FROM retail_positions rp
                   JOIN employees e ON e.id=rp.employee_id
                   WHERE rp.player_id=? AND rp.product_id=? AND rp.pack_size=?
                     AND rp.position_count>0 AND e.active=1 AND e.available=1 AND e.role='courier'""",
                (player_id, listing["product_id"], listing["pack_size"]),
            ).fetchone()[0])
            if available_positions <= 0:
                continue
            unit_price = listing["price"] / listing["pack_size"]
            price_ratio = unit_price / listing["base_market_price"]
            price_effect = clamp(math.exp(-2.2 * (price_ratio - 1.0)), 0.35, 1.55)
            pack_effect = {1: 1.0, 2: 0.68, 5: 0.28}.get(listing["pack_size"], 0.2)
            expected = (listing["base_demand"] / 24.0) * sim_hours * rating_effect * price_effect * pack_effect
            count = min(available_positions, self._poisson(expected))
            for _ in range(count):
                disputed = self._create_retail_order(conn, player_id, listing, now)
                if disputed is None:
                    break
                orders_created += 1
                disputes_created += int(disputed)
        return orders_created, disputes_created

    def _create_retail_order(self, conn, player_id: int, listing, now) -> bool | None:
        position = conn.execute(
            """SELECT rp.*, e.*,
                      rp.id position_id, rp.employee_id retail_employee_id,
                      rp.unit_cost position_unit_cost, rp.quality position_quality
               FROM retail_positions rp
               JOIN employees e ON e.id=rp.employee_id
               WHERE rp.player_id=? AND rp.product_id=? AND rp.pack_size=?
                 AND rp.position_count>0 AND e.active=1 AND e.available=1 AND e.role='courier'
               ORDER BY rp.created_at, rp.id LIMIT 1""",
            (player_id, listing["product_id"], listing["pack_size"]),
        ).fetchone()
        client = conn.execute(
            "SELECT * FROM clients WHERE player_id=? ORDER BY RANDOM() LIMIT 1",
            (player_id,),
        ).fetchone()
        if not position or not client:
            return None
        qty = int(listing["pack_size"])
        revenue = int(listing["price"])
        cost = int(position["position_unit_cost"] * qty)
        employee_cost = int(position["pay_per_job"])
        contribution_pct = int(position["deposit_contribution_pct"] or 0)
        contribution_preview = int(round(employee_cost * contribution_pct / 100.0))
        quality = float(position["position_quality"])

        conn.execute("UPDATE retail_positions SET position_count=position_count-1 WHERE id=?", (position["position_id"],))
        conn.execute(
            """UPDATE employees SET jobs_done=jobs_done+1, wages_accrued=wages_accrued+?,
                   stress=MIN(100, stress+?), last_contact_at=? WHERE id=?""",
            (employee_cost, self.rng.uniform(0.05, 0.35), iso(now), position["retail_employee_id"]),
        )
        conn.execute(
            """UPDATE clients SET shop_orders=shop_orders+1, marketplace_orders=marketplace_orders+1,
                   total_spend=total_spend+? WHERE id=?""",
            (revenue, client["id"]),
        )
        cur = conn.execute(
            """INSERT INTO orders(
                   player_id, client_id, employee_id, batch_id, product_id, quantity,
                   revenue, cost, employee_cost, employee_deposit_contribution, quality
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                player_id,
                client["id"],
                position["retail_employee_id"],
                position["batch_id"],
                listing["product_id"],
                qty,
                revenue,
                cost,
                employee_cost,
                contribution_preview,
                quality,
            ),
        )
        order_id = int(cur.lastrowid)
        profit = revenue - cost - employee_cost
        conn.execute(
            """UPDATE shops SET balance=balance+?, total_revenue=total_revenue+?,
                   total_profit=total_profit+?, total_orders=total_orders+1 WHERE player_id=?""",
            (revenue, revenue, profit, player_id),
        )
        conn.execute(
            """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
               VALUES (?, ?, 'sale', 'order', ?, ?)""",
            (player_id, revenue, order_id, f"Заказ #{order_id} · зарплата {employee_cost:,} ₽ начислена"),
        )
        probability = self._dispute_probability(client, position, quality, float(listing["complaint_modifier"]))
        if self.rng.random() < probability:
            self._open_dispute(conn, player_id, order_id, client, position, quality, revenue, now)
            return True
        return False

    def _has_stock(self, conn, player_id: int, product_id: int, qty: int) -> bool:
        count = conn.execute(
            """SELECT COALESCE(SUM(position_count),0) FROM retail_positions
               WHERE player_id=? AND product_id=? AND pack_size=? AND position_count>0""",
            (player_id, product_id, qty),
        ).fetchone()[0]
        return int(count) > 0

    def employee_exposure(self, conn, player_id: int, employee_id: int) -> int:
        employee = conn.execute(
            "SELECT role FROM employees WHERE id=? AND player_id=?",
            (employee_id, player_id),
        ).fetchone()
        if not employee:
            return 0
        if employee["role"] == "warehouse":
            batch_value = int(conn.execute(
                """SELECT COALESCE(SUM(remaining*unit_cost),0) FROM batches
                   WHERE player_id=? AND responsible_employee_id=?
                     AND status IN ('receiving','warehouse')""",
                (player_id, employee_id),
            ).fetchone()[0])
            pending = int(conn.execute(
                """SELECT COALESCE(SUM(quantity*unit_cost),0) FROM retail_allocations
                   WHERE player_id=? AND wholesale_employee_id=? AND status='waiting'""",
                (player_id, employee_id),
            ).fetchone()[0])
            return batch_value + pending
        preparing = int(conn.execute(
            """SELECT COALESCE(SUM(quantity*unit_cost),0) FROM retail_allocations
               WHERE player_id=? AND retail_employee_id=? AND status='preparing'""",
            (player_id, employee_id),
        ).fetchone()[0])
        published = int(conn.execute(
            """SELECT COALESCE(SUM(position_count*pack_size*unit_cost),0) FROM retail_positions
               WHERE player_id=? AND employee_id=? AND position_count>0""",
            (player_id, employee_id),
        ).fetchone()[0])
        return preparing + published

    def _simulate_management_events(self, conn, player_id: int, sim_hours: float, now) -> int:
        created = 0
        chances = min(sim_hours, 12.0)
        if self.rng.random() < 1 - math.exp(-0.055 * chances):
            employee = conn.execute(
                "SELECT * FROM employees WHERE player_id=? AND active=1 ORDER BY RANDOM() LIMIT 1",
                (player_id,),
            ).fetchone()
            if employee:
                kind = self.rng.choice(["raise_request", "leave_request", "advance_request"])
                payload = {"employee_id": employee["id"]}
                operation = "операцию" if employee["role"] == "warehouse" else "заказ"
                if kind == "raise_request":
                    market = ROLE_MARKET_PAY.get(employee["role"], 1500)
                    target = max(
                        int(employee["pay_per_job"]) + (250 if employee["role"] == "warehouse" else 100),
                        int(round(max(employee["pay_per_job"] * self.rng.uniform(1.08, 1.22), market * 0.95) / 50) * 50),
                    )
                    floor = max(int(employee["pay_per_job"]), int(target * self.rng.uniform(0.88, 0.97)))
                    payload.update({"requested_pay": target, "offer_pay": int(employee["pay_per_job"]), "floor_pay": floor, "round": 0})
                    title = "Разговор об оплате"
                    body = (
                        f"{employee['alias']} просит пересмотреть условия.\n\n"
                        f"Текущая ставка: {employee['pay_per_job']:,} ₽ / {operation}\n"
                        f"Запрос: <b>{target:,} ₽ / {operation}</b>\n\n"
                        "Можно согласиться, отказать или предложить встречную ставку."
                    )
                elif kind == "leave_request":
                    title = "Просьба о паузе"
                    body = f"{employee['alias']} просит временную паузу.\n\nСрок: 6 игровых часов\nПричина: личные обстоятельства"
                else:
                    amount = min(50_000 if employee["role"] == "warehouse" else 12_000, max(2_000, int(employee["deposit"] * 0.12)))
                    payload["amount"] = amount
                    title = "Запрос сотрудника"
                    body = f"{employee['alias']} просит вернуть часть депозита.\n\nСумма: <b>{amount:,} ₽</b>\nТекущий депозит: {employee['deposit']:,} ₽"
                conn.execute(
                    """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
                       VALUES (?, ?, 'normal', ?, ?, ?, ?)""",
                    (player_id, kind, title, body, json.dumps(payload, ensure_ascii=False), iso(now + self._game_hours_to_real(player_id, 4))),
                )
                created += 1

        if self.rng.random() < 1 - math.exp(-0.035 * chances):
            client = conn.execute(
                "SELECT * FROM clients WHERE player_id=? AND shop_orders>0 ORDER BY RANDOM() LIMIT 1",
                (player_id,),
            ).fetchone()
            if client:
                percent = self.rng.choice([2, 3, 4, 5])
                conn.execute(
                    """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
                       VALUES (?, 'discount_request', 'important', 'Просьба постоянного клиента', ?, ?, ?)""",
                    (
                        player_id,
                        f"{client['alias']} просит небольшую скидку.\n\nРазмер: <b>{percent}%</b>\nПричина: не хватает суммы после изменения курса.",
                        json.dumps({"client_id": client["id"], "percent": percent}, ensure_ascii=False),
                        iso(now + self._game_hours_to_real(player_id, 0.75)),
                    ),
                )
                created += 1

        created += self._check_overexposure_risk(conn, player_id, sim_hours, now)
        return created

    def _check_overexposure_risk(self, conn, player_id: int, sim_hours: float, now) -> int:
        employees = conn.execute(
            "SELECT * FROM employees WHERE player_id=? AND active=1",
            (player_id,),
        ).fetchall()
        for employee in employees:
            exposure = self.employee_exposure(conn, player_id, int(employee["id"]))
            deposit = int(employee["deposit"])
            unsecured = max(0, exposure - deposit)
            if unsecured <= 0:
                continue
            unsecured_ratio = unsecured / max(exposure, 1)
            dishonesty = 1.0 - float(employee["honesty"])
            low_loyalty = max(0.0, 0.60 - float(employee["loyalty"]))
            stress = max(0.0, float(employee["stress"]) - 55.0) / 45.0
            hourly = 0.0008 + unsecured_ratio * (dishonesty * 0.018 + low_loyalty * 0.010 + stress * 0.004)
            chance = 1.0 - math.exp(-hourly * min(sim_hours, 24.0))
            if self.rng.random() >= chance:
                continue
            fraction = 1.0 if dishonesty > 0.40 and self.rng.random() < 0.45 else self.rng.choice([0.25, 0.50, 0.75])
            loss_cost = self._employee_absconds(conn, player_id, employee, fraction)
            deposit_forfeit = deposit
            conn.execute(
                """UPDATE employees SET active=0, available=0, deposit=0, wages_accrued=0,
                       losses=losses+? WHERE id=?""",
                (loss_cost, employee["id"]),
            )
            conn.execute("UPDATE employee_tasks SET status='cancelled' WHERE employee_id=? AND status='active'", (employee["id"],))
            conn.execute(
                "UPDATE shops SET total_profit=total_profit+?-? WHERE player_id=?",
                (deposit_forfeit, loss_cost, player_id),
            )
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, 0, 'deposit_forfeit', 'employee', ?, ?)""",
                (player_id, employee["id"], f"Депозит {employee['alias']} удержан: {deposit_forfeit:,} ₽"),
            )
            conn.execute(
                """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json)
                   VALUES (?, 'employee_theft', 'urgent', 'Сотрудник пропал', ?, ?)""",
                (
                    player_id,
                    f"{employee['alias']} пропал со связи.\n\n"
                    f"Потеря товара по себестоимости: <b>{loss_cost:,} ₽</b>\n"
                    f"Депозит удержан магазином: {deposit_forfeit:,} ₽\n\n"
                    "Потерянный товар вернуть нельзя.",
                    json.dumps({"employee_id": employee["id"], "loss_cost": loss_cost, "deposit_forfeit": deposit_forfeit}, ensure_ascii=False),
                ),
            )
            return 1
        return 0

    def _employee_absconds(self, conn, player_id: int, employee, fraction: float) -> int:
        employee_id = int(employee["id"])
        loss_cost = 0
        if employee["role"] == "warehouse":
            batches = conn.execute(
                """SELECT * FROM batches WHERE player_id=? AND responsible_employee_id=?
                   AND status IN ('receiving','warehouse') AND remaining>0""",
                (player_id, employee_id),
            ).fetchall()
            for batch in batches:
                lost_qty = min(int(batch["remaining"]), max(1, int(round(int(batch["remaining"]) * fraction))))
                loss_cost += lost_qty * int(batch["unit_cost"])
                remaining = int(batch["remaining"]) - lost_qty
                conn.execute(
                    """UPDATE batches SET remaining=?, responsible_employee_id=NULL,
                           status=CASE WHEN ? > 0 THEN 'warehouse' ELSE 'lost' END WHERE id=?""",
                    (remaining, remaining, batch["id"]),
                )
            pending = conn.execute(
                """SELECT * FROM retail_allocations
                   WHERE player_id=? AND wholesale_employee_id=? AND status='waiting'""",
                (player_id, employee_id),
            ).fetchall()
            for allocation in pending:
                lost_qty = min(int(allocation["quantity"]), max(1, int(round(int(allocation["quantity"]) * fraction))))
                recovered = int(allocation["quantity"]) - lost_qty
                loss_cost += lost_qty * int(allocation["unit_cost"])
                if recovered:
                    conn.execute("UPDATE batches SET remaining=remaining+? WHERE id=?", (recovered, allocation["batch_id"]))
                conn.execute("UPDATE retail_allocations SET status='lost', quantity=? WHERE id=?", (lost_qty, allocation["id"]))
        else:
            preparing = conn.execute(
                """SELECT * FROM retail_allocations
                   WHERE player_id=? AND retail_employee_id=? AND status='preparing'""",
                (player_id, employee_id),
            ).fetchall()
            for allocation in preparing:
                lost_qty = min(int(allocation["quantity"]), max(1, int(round(int(allocation["quantity"]) * fraction))))
                recovered = int(allocation["quantity"]) - lost_qty
                loss_cost += lost_qty * int(allocation["unit_cost"])
                if recovered:
                    conn.execute("UPDATE batches SET remaining=remaining+? WHERE id=?", (recovered, allocation["batch_id"]))
                conn.execute("UPDATE retail_allocations SET status='lost', quantity=? WHERE id=?", (lost_qty, allocation["id"]))
            positions = conn.execute(
                """SELECT * FROM retail_positions
                   WHERE player_id=? AND employee_id=? AND position_count>0""",
                (player_id, employee_id),
            ).fetchall()
            for position in positions:
                total_units = int(position["position_count"]) * int(position["pack_size"])
                lost_units = min(total_units, max(int(position["pack_size"]), int(round(total_units * fraction / int(position["pack_size"]))) * int(position["pack_size"])))
                lost_positions = min(int(position["position_count"]), max(1, lost_units // int(position["pack_size"])))
                lost_units = lost_positions * int(position["pack_size"])
                recovered_units = total_units - lost_units
                loss_cost += lost_units * int(position["unit_cost"])
                if recovered_units:
                    conn.execute("UPDATE batches SET remaining=remaining+? WHERE id=?", (recovered_units, position["batch_id"]))
                conn.execute("UPDATE retail_positions SET position_count=0 WHERE id=?", (position["id"],))
        return loss_cost

    def rescale_existing_timers(self, player_id: int, old_speed: float, new_speed: float, now=None) -> None:
        now = now or utcnow()
        super().rescale_existing_timers(player_id, old_speed, new_speed, now)
        with self.db.connect() as conn:
            tasks = conn.execute(
                "SELECT id, completes_at FROM employee_tasks WHERE player_id=? AND status='active'",
                (player_id,),
            ).fetchall()
            for task in tasks:
                target = parse_dt(task["completes_at"])
                remaining_real = max(0.0, (target - now).total_seconds())
                remaining_game = remaining_real * max(0.1, old_speed)
                conn.execute(
                    "UPDATE employee_tasks SET completes_at=? WHERE id=?",
                    (iso(now + timedelta(seconds=remaining_game / max(0.1, new_speed))), task["id"]),
                )

    def fast_forward_timers(self, player_id: int, game_hours: float) -> None:
        super().fast_forward_timers(player_id, game_hours)
        shift = timedelta(hours=max(0.0, game_hours) / self.effective_speed(player_id))
        with self.db.connect() as conn:
            tasks = conn.execute(
                "SELECT id, completes_at FROM employee_tasks WHERE player_id=? AND status='active'",
                (player_id,),
            ).fetchall()
            for task in tasks:
                conn.execute(
                    "UPDATE employee_tasks SET completes_at=? WHERE id=?",
                    (iso(parse_dt(task["completes_at"]) - shift), task["id"]),
                )


class WorkflowGameService(OperationsGameService):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(WORKFLOW_SCHEMA)

    def _task_status(self, player_id: int, employee_id: int) -> str:
        with self.db.connect() as conn:
            task = conn.execute(
                """SELECT * FROM employee_tasks
                   WHERE player_id=? AND employee_id=? AND status='active'
                   ORDER BY completes_at LIMIT 1""",
                (player_id, employee_id),
            ).fetchone()
            employee = conn.execute("SELECT * FROM employees WHERE id=? AND player_id=?", (employee_id, player_id)).fetchone()
        if not employee:
            return "неизвестно"
        if not employee["active"]:
            return "не работает"
        if not employee["available"]:
            return "временно недоступен"
        if not task:
            return "свободен"
        remaining_real = max(0.0, (parse_dt(task["completes_at"]) - utcnow()).total_seconds() / 3600.0)
        remaining_game = remaining_real * self.simulation.effective_speed(player_id)
        eta = "<1 ч" if remaining_game < 1 else f"~{remaining_game:.1f} ч"
        return f"{TASK_LABELS.get(task['kind'], task['kind'])} · {eta}"

    def employees(self, player_id: int):
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM employees WHERE player_id=? AND active=1 ORDER BY role DESC, joined_at",
                (player_id,),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["status_text"] = self._task_status(player_id, int(row["id"]))
            data["exposure"] = self._employee_exposure(player_id, int(row["id"]))
            result.append(data)
        return result

    def _employee_exposure(self, player_id: int, employee_id: int) -> int:
        with self.db.connect() as conn:
            return int(self.simulation.employee_exposure(conn, player_id, employee_id))

    def employee_details(self, player_id: int, employee_id: int) -> str | None:
        with self.db.connect() as conn:
            employee = conn.execute("SELECT * FROM employees WHERE id=? AND player_id=?", (employee_id, player_id)).fetchone()
            if not employee:
                return None
            service = conn.execute(
                """SELECT COUNT(*) count, COALESCE(AVG(courier_rating),0) avg
                   FROM order_ratings WHERE player_id=? AND employee_id=?""",
                (player_id, employee_id),
            ).fetchone()
        exposure = self._employee_exposure(player_id, employee_id)
        unsecured = max(0, exposure - int(employee["deposit"]))
        dispute_rate = employee["disputes"] / employee["jobs_done"] * 100.0 if employee["jobs_done"] else 0.0
        role = "Оптовый сотрудник" if employee["role"] == "warehouse" else "Розничный сотрудник"
        text = (
            f"<b>👤 {employee['alias']}</b> · {role}\n\n"
            f"<b>Сейчас</b>\n"
            f"Статус: <b>{self._task_status(player_id, employee_id)}</b>\n\n"
            f"<b>Условия</b>\n"
            f"Ставка: {employee['pay_per_job']:,} ₽ / операцию\n"
            f"Депозит: <b>{employee['deposit']:,} ₽</b>\n"
            f"Отчисление в депозит: {employee['deposit_contribution_pct']}%\n"
            f"Начислено: {employee['wages_accrued']:,} ₽\n\n"
            f"<b>Ответственность</b>\n"
            f"Товар на руках: {exposure:,} ₽\n"
            f"Не покрыто депозитом: <b>{unsecured:,} ₽</b>\n\n"
            f"<b>Статистика</b>\n"
            f"Операций: {employee['jobs_done']}\n"
            f"Диспутов: {employee['disputes']} ({dispute_rate:.1f}%)\n"
            f"Потери: {employee['losses']:,} ₽"
        )
        if employee["role"] == "courier":
            text += f"\nОценок работы: {service['count']}"
            if service["count"]:
                text += f" · ⭐ {float(service['avg']):.2f}/5"
        if unsecured > 0:
            text += "\n\n🔴 Часть товара не покрыта депозитом. Риск потери выше."
        return text

    def warehouse_staff_for_offer(self, player_id: int, offer_id: int):
        with self.db.connect() as conn:
            offer = conn.execute(
                "SELECT quantity, unit_cost FROM supplier_offers WHERE id=? AND player_id=? AND status='open'",
                (offer_id, player_id),
            ).fetchone()
            if not offer:
                return []
            total = int(offer["quantity"] * offer["unit_cost"])
            staff = conn.execute(
                "SELECT * FROM employees WHERE player_id=? AND active=1 AND role='warehouse' ORDER BY deposit DESC",
                (player_id,),
            ).fetchall()
        result = []
        for employee in staff:
            exposure = self._employee_exposure(player_id, int(employee["id"]))
            free = max(0, int(employee["deposit"]) - exposure)
            after = exposure + total
            result.append({
                "id": int(employee["id"]),
                "alias": employee["alias"],
                "deposit": int(employee["deposit"]),
                "exposure": exposure,
                "free_coverage": free,
                "eligible": True,
                "required": total,
                "unsecured_after": max(0, after - int(employee["deposit"])),
            })
        return result

    def buy_offer_for_employee(self, player_id: int, offer_id: int, employee_id: int) -> str:
        now = utcnow()
        with self.db.connect() as conn:
            offer = conn.execute(
                """SELECT o.*, s.quality_mean, s.quality_sigma, s.reliability,
                          s.title supplier_title, p.title product_title
                   FROM supplier_offers o
                   JOIN suppliers s ON s.id=o.supplier_id
                   JOIN products p ON p.id=o.product_id
                   WHERE o.id=? AND o.player_id=? AND o.status='open'""",
                (offer_id, player_id),
            ).fetchone()
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1 AND role='warehouse'",
                (employee_id, player_id),
            ).fetchone()
            shop = conn.execute("SELECT * FROM shops WHERE player_id=?", (player_id,)).fetchone()
            if not offer:
                return "Предложение уже недоступно."
            if not employee:
                return "Оптовый сотрудник больше недоступен."
            total = int(offer["quantity"] * offer["unit_cost"])
            if int(shop["balance"]) < total:
                return f"Недостаточно денег. Нужно {total:,} ₽."
            delivered = self.rng.random() < float(offer["reliability"])
            quality = clamp(self.rng.gauss(float(offer["quality_mean"]), float(offer["quality_sigma"])), 35.0, 99.0)
            exposure_before = self._employee_exposure(player_id, employee_id)
            conn.execute("UPDATE shops SET balance=balance-? WHERE player_id=?", (total, player_id))
            if delivered:
                cur = conn.execute(
                    """INSERT INTO batches(
                           player_id, supplier_id, product_id, responsible_employee_id,
                           quantity, remaining, unit_cost, quality, status
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'receiving')""",
                    (
                        player_id, offer["supplier_id"], offer["product_id"], employee_id,
                        offer["quantity"], offer["quantity"], offer["unit_cost"], quality,
                    ),
                )
                batch_id = int(cur.lastrowid)
                game_hours = 1.5 + int(offer["quantity"]) / 100.0 * 0.8 + self.rng.uniform(0.2, 1.0)
                conn.execute(
                    """INSERT INTO employee_tasks(
                           player_id, employee_id, kind, batch_id, product_id, quantity, completes_at, note
                       ) VALUES (?, ?, 'receive_batch', ?, ?, ?, ?, ?)""",
                    (
                        player_id, employee_id, batch_id, offer["product_id"], offer["quantity"],
                        iso(now + timedelta(hours=game_hours / self.simulation.effective_speed(player_id))),
                        f"Приём партии {offer['product_title']}",
                    ),
                )
                conn.execute(
                    """UPDATE employees SET jobs_done=jobs_done+1, wages_accrued=wages_accrued+?,
                           stress=MIN(100, stress+1.2), last_contact_at=? WHERE id=?""",
                    (employee["pay_per_job"], iso(now), employee_id),
                )
                note = f"Партия #{batch_id}: {offer['product_title']} · ответственный {employee['alias']}"
            else:
                note = f"Срыв сделки с {offer['supplier_title']}"
                conn.execute("UPDATE shops SET supplier_reputation=MAX(0, supplier_reputation-1) WHERE player_id=?", (player_id,))
            conn.execute(
                "INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note) VALUES (?, ?, 'procurement', 'offer', ?, ?)",
                (player_id, -total, offer_id, note),
            )
            conn.execute("UPDATE supplier_offers SET status='bought' WHERE id=?", (offer_id,))

        if not delivered:
            return f"Сделка сорвалась. Потеря: {total:,} ₽."
        exposure_after = exposure_before + total
        unsecured = max(0, exposure_after - int(employee["deposit"]))
        risk = (
            f"\n\n🔴 Не покрыто депозитом после закупки: <b>{unsecured:,} ₽</b>."
            if unsecured else "\n\nПартия полностью покрыта депозитом сотрудника."
        )
        return (
            f"Партия куплена за <b>{total:,} ₽</b>.\n\n"
            f"Ответственный: <b>{employee['alias']}</b>\n"
            "Статус: принимает партию\n"
            f"Начислено за операцию: {employee['pay_per_job']:,} ₽"
            f"{risk}"
        )

    def allocate_to_retail(self, player_id: int, batch_id: int, retail_employee_id: int, quantity: int) -> str:
        now = utcnow()
        quantity = max(1, int(quantity))
        with self.db.connect() as conn:
            batch = conn.execute(
                """SELECT b.*, p.title product_title, e.alias wholesale_alias
                   FROM batches b JOIN products p ON p.id=b.product_id
                   JOIN employees e ON e.id=b.responsible_employee_id
                   WHERE b.id=? AND b.player_id=? AND b.status='warehouse' AND b.remaining>0""",
                (batch_id, player_id),
            ).fetchone()
            retail = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1 AND role='courier'",
                (retail_employee_id, player_id),
            ).fetchone()
            if not batch:
                return "Партия ещё не готова к распределению или уже закончилась."
            if not retail:
                return "Розничный сотрудник недоступен."
            quantity = min(quantity, int(batch["remaining"]))
            conn.execute("UPDATE batches SET remaining=remaining-? WHERE id=?", (quantity, batch_id))
            cur = conn.execute(
                """INSERT INTO retail_allocations(
                       player_id, batch_id, wholesale_employee_id, retail_employee_id,
                       product_id, quantity, unit_cost, quality, status
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting')""",
                (
                    player_id, batch_id, batch["responsible_employee_id"], retail_employee_id,
                    batch["product_id"], quantity, batch["unit_cost"], batch["quality"],
                ),
            )
            allocation_id = int(cur.lastrowid)
            game_hours = 0.7 + quantity / 25.0 * 0.8 + self.rng.uniform(0.2, 0.8)
            conn.execute(
                """INSERT INTO employee_tasks(
                       player_id, employee_id, kind, batch_id, allocation_id,
                       product_id, quantity, completes_at, note
                   ) VALUES (?, ?, 'handoff', ?, ?, ?, ?, ?, ?)""",
                (
                    player_id, batch["responsible_employee_id"], batch_id, allocation_id,
                    batch["product_id"], quantity,
                    iso(now + timedelta(hours=game_hours / self.simulation.effective_speed(player_id))),
                    f"Подготовка передачи {quantity} ед. для {retail['alias']}",
                ),
            )
        retail_after = self._employee_exposure(player_id, retail_employee_id) + quantity * int(batch["unit_cost"])
        unsecured = max(0, retail_after - int(retail["deposit"]))
        warning = f"\n\n🔴 После получения у сотрудника будет не покрыто депозитом: {unsecured:,} ₽." if unsecured else ""
        return (
            f"Назначено <b>{quantity} ед.</b> {batch['product_title']} сотруднику {retail['alias']}.\n\n"
            f"{batch['wholesale_alias']} начал подготовку передачи. После завершения {retail['alias']} автоматически начнёт подготовку позиций.{warning}"
        )

    def retail_staff_for_batch(self, player_id: int, batch_id: int):
        with self.db.connect() as conn:
            batch = conn.execute("SELECT * FROM batches WHERE id=? AND player_id=?", (batch_id, player_id)).fetchone()
            staff = conn.execute(
                "SELECT * FROM employees WHERE player_id=? AND active=1 AND role='courier' ORDER BY alias",
                (player_id,),
            ).fetchall()
        if not batch:
            return None, []
        result = []
        for employee in staff:
            exposure = self._employee_exposure(player_id, int(employee["id"]))
            result.append({
                "id": int(employee["id"]),
                "alias": employee["alias"],
                "deposit": int(employee["deposit"]),
                "exposure": exposure,
                "free": max(0, int(employee["deposit"]) - exposure),
            })
        return batch, result

    def active_batches(self, player_id: int, employee_id: int):
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT b.*, p.title product_title FROM batches b JOIN products p ON p.id=b.product_id
                   WHERE b.player_id=? AND b.responsible_employee_id=?
                     AND b.status IN ('receiving','warehouse') AND b.remaining>0
                   ORDER BY b.acquired_at DESC""",
                (player_id, employee_id),
            ).fetchall()

    def unassigned_batches(self, player_id: int):
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT b.*, p.title product_title FROM batches b JOIN products p ON p.id=b.product_id
                   WHERE b.player_id=? AND b.responsible_employee_id IS NULL
                     AND b.status='warehouse' AND b.remaining>0 ORDER BY b.id""",
                (player_id,),
            ).fetchall()

    def assign_unassigned_batch(self, player_id: int, batch_id: int, employee_id: int) -> str:
        with self.db.connect() as conn:
            batch = conn.execute(
                "SELECT * FROM batches WHERE id=? AND player_id=? AND responsible_employee_id IS NULL AND status='warehouse'",
                (batch_id, player_id),
            ).fetchone()
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1 AND role='warehouse'",
                (employee_id, player_id),
            ).fetchone()
            if not batch or not employee:
                return "Партия или сотрудник уже недоступны."
            conn.execute("UPDATE batches SET responsible_employee_id=? WHERE id=?", (employee_id, batch_id))
        exposure = self._employee_exposure(player_id, employee_id)
        unsecured = max(0, exposure - int(employee["deposit"]))
        warning = f" Не покрыто депозитом: {unsecured:,} ₽." if unsecured else ""
        return f"Партия #{batch_id} закреплена за {employee['alias']}.{warning}"

    def change_employee_role(self, player_id: int, employee_id: int) -> str:
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                return "Сотрудник недоступен."
            exposure = self.simulation.employee_exposure(conn, player_id, employee_id)
            active_task = conn.execute(
                "SELECT 1 FROM employee_tasks WHERE employee_id=? AND status='active' LIMIT 1",
                (employee_id,),
            ).fetchone()
            if exposure > 0 or active_task:
                return "Сначала сотрудник должен завершить текущие задачи и не иметь товара на руках."
            new_role = "warehouse" if employee["role"] == "courier" else "courier"
            new_pay = ROLE_MARKET_PAY[new_role]
            conn.execute(
                "UPDATE employees SET role=?, pay_per_job=? WHERE id=?",
                (new_role, new_pay, employee_id),
            )
            if new_role == "courier":
                products = conn.execute("SELECT id FROM products WHERE active=1").fetchall()
                for product in products:
                    conn.execute(
                        "INSERT OR IGNORE INTO packaging_rules(player_id, employee_id, product_id) VALUES (?, ?, ?)",
                        (player_id, employee_id, product["id"]),
                    )
        role_title = "оптовый" if new_role == "warehouse" else "розничный"
        return f"{employee['alias']} переведён в роль «{role_title}». Новая базовая ставка: {new_pay:,} ₽ / операцию."

    def packaging_rules(self, player_id: int, employee_id: int):
        self.simulation._ensure_packaging_rules(player_id)
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT pr.*, p.title product_title FROM packaging_rules pr
                   JOIN products p ON p.id=pr.product_id
                   JOIN employees e ON e.id=pr.employee_id
                   WHERE pr.player_id=? AND pr.employee_id=? AND e.active=1 AND e.role='courier'
                   ORDER BY p.id""",
                (player_id, employee_id),
            ).fetchall()

    def adjust_packaging_rule(self, player_id: int, employee_id: int, product_id: int, pack_size: int, delta: int) -> str:
        if pack_size not in {1, 2, 5} or delta not in {-10, 10}:
            raise ValueError("Unsupported packaging adjustment")
        self.simulation._ensure_packaging_rules(player_id)
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT * FROM packaging_rules
                   WHERE player_id=? AND employee_id=? AND product_id=?""",
                (player_id, employee_id, product_id),
            ).fetchone()
            if not row:
                return "Правило не найдено."
            values = {1: int(row["pct_1"]), 2: int(row["pct_2"]), 5: int(row["pct_5"])}
            current = values[pack_size]
            if delta > 0:
                actual = min(delta, 100 - current)
                needed = actual
                for other in sorted((p for p in values if p != pack_size), key=lambda p: values[p], reverse=True):
                    take = min(needed, values[other])
                    values[other] -= take
                    needed -= take
                    if needed <= 0:
                        break
                actual -= needed
                values[pack_size] += actual
            else:
                actual = min(-delta, current)
                values[pack_size] -= actual
                other = max((p for p in values if p != pack_size), key=lambda p: values[p])
                values[other] += actual
            conn.execute(
                """UPDATE packaging_rules SET pct_1=?, pct_2=?, pct_5=?
                   WHERE player_id=? AND employee_id=? AND product_id=?""",
                (values[1], values[2], values[5], player_id, employee_id, product_id),
            )
        return f"×1 {values[1]}% · ×2 {values[2]}% · ×5 {values[5]}%"

    def fire_employee(self, player_id: int, employee_id: int) -> dict:
        exposure = self._employee_exposure(player_id, employee_id)
        with self.db.connect() as conn:
            task = conn.execute(
                "SELECT 1 FROM employee_tasks WHERE employee_id=? AND status='active' LIMIT 1",
                (employee_id,),
            ).fetchone()
        if exposure > 0 or task:
            return {
                "status": "inventory",
                "message": "Нельзя уволить сотрудника, пока у него есть товар или незавершённая задача. Сначала освободи его от ответственности.",
            }
        return super().fire_employee(player_id, employee_id)
