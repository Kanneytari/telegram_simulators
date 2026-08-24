from __future__ import annotations

from datetime import timedelta

from .delayed_disputes import DelayedDisputeGameService, DelayedDisputeSimulationEngine
from .simulation import iso, parse_dt, utcnow


DEFAULT_POLICIES = {
    "courier": {
        "fixed_fee": 200,
        "base_rate_bps": 400,
        "risk_rate_bps": 0,
        "deposit_contribution_pct": 20,
    },
    "warehouse": {
        "fixed_fee": 0,
        "base_rate_bps": 200,
        "risk_rate_bps": 100,
        "deposit_contribution_pct": 25,
    },
}

COMPENSATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS staff_compensation_policies (
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('courier','warehouse')),
    fixed_fee INTEGER NOT NULL DEFAULT 0,
    base_rate_bps INTEGER NOT NULL DEFAULT 0,
    risk_rate_bps INTEGER NOT NULL DEFAULT 0,
    deposit_contribution_pct INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(player_id, role)
);

CREATE TABLE IF NOT EXISTS wholesale_delivery_payments (
    allocation_id INTEGER PRIMARY KEY REFERENCES retail_allocations(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    goods_value INTEGER NOT NULL,
    uncovered_value INTEGER NOT NULL DEFAULT 0,
    base_amount INTEGER NOT NULL,
    risk_amount INTEGER NOT NULL DEFAULT 0,
    amount INTEGER NOT NULL,
    deposit_contribution INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wholesale_delivery_payments_employee
    ON wholesale_delivery_payments(player_id, employee_id, created_at);

CREATE TABLE IF NOT EXISTS compensation_policy_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value INTEGER NOT NULL,
    new_value INTEGER NOT NULL,
    loyalty_delta REAL NOT NULL DEFAULT 0,
    stress_delta REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _ensure_policy_conn(conn, player_id: int, role: str) -> None:
    defaults = DEFAULT_POLICIES[role]
    conn.execute(
        """INSERT OR IGNORE INTO staff_compensation_policies(
               player_id, role, fixed_fee, base_rate_bps, risk_rate_bps,
               deposit_contribution_pct
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            player_id,
            role,
            defaults["fixed_fee"],
            defaults["base_rate_bps"],
            defaults["risk_rate_bps"],
            defaults["deposit_contribution_pct"],
        ),
    )


def _policy_conn(conn, player_id: int, role: str):
    _ensure_policy_conn(conn, player_id, role)
    return conn.execute(
        "SELECT * FROM staff_compensation_policies WHERE player_id=? AND role=?",
        (player_id, role),
    ).fetchone()


def _money_from_bps(value: int, bps: int) -> int:
    return max(0, int(round(int(value) * int(bps) / 10000.0)))


def _deposit_part(amount: int, pct: int) -> int:
    return max(0, min(int(amount), int(round(int(amount) * int(pct) / 100.0))))


class CompensationSimulationEngine(DelayedDisputeSimulationEngine):
    """Global commission model for retail and wholesale staff."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(COMPENSATION_SCHEMA)
            for row in conn.execute("SELECT player_id FROM shops").fetchall():
                for role in DEFAULT_POLICIES:
                    _ensure_policy_conn(conn, int(row["player_id"]), role)

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        with self.db.connect() as conn:
            conn.executescript(COMPENSATION_SCHEMA)
            for role in DEFAULT_POLICIES:
                _ensure_policy_conn(conn, player_id, role)
            # Live compensation is defined by the shop-wide policy. Per-employee
            # operation rates stay zero at this layer so they cannot be charged twice.
            conn.execute(
                "UPDATE employees SET pay_per_job=0, deposit_contribution_pct=0 WHERE player_id=?",
                (player_id,),
            )
        return created

    def _create_retail_order(self, conn, player_id: int, listing, now) -> bool | None:
        position = conn.execute(
            """SELECT rp.id position_id, rp.allocation_id, rp.batch_id,
                      rp.employee_id retail_employee_id, rp.product_id,
                      rp.pack_size, rp.position_count,
                      rp.unit_cost position_unit_cost, rp.quality position_quality,
                      e.id employee_id, e.attention, e.stress, e.honesty, e.loyalty
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
                   wages_accrued=wages_accrued+?,
                   deposit_accrued=deposit_accrued+?,
                   stress=MIN(100, stress+?),
                   last_contact_at=?
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
               SET shop_orders=shop_orders+1,
                   marketplace_orders=marketplace_orders+1,
                   total_spend=total_spend+?
               WHERE id=?""",
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
                position["employee_id"],
                position["batch_id"],
                listing["product_id"],
                qty,
                revenue,
                cost,
                employee_cost,
                deposit_part,
                quality,
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

    def _process_tasks(self, conn, player_id: int, now) -> int:
        due_handoffs = conn.execute(
            """SELECT t.id task_id, t.allocation_id,
                      a.wholesale_employee_id, a.quantity, a.unit_cost
               FROM employee_tasks t
               JOIN retail_allocations a ON a.id=t.allocation_id
               WHERE t.player_id=? AND t.kind='handoff' AND t.status='active'
                 AND t.completes_at<=?""",
            (player_id, iso(now)),
        ).fetchall()

        snapshots: dict[int, dict[str, int]] = {}
        for row in due_handoffs:
            employee_id = int(row["wholesale_employee_id"])
            employee = conn.execute(
                """SELECT deposit FROM employees
                   WHERE id=? AND player_id=? AND active=1 AND role='warehouse'""",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                continue
            allocation_id = int(row["allocation_id"])
            snapshots[allocation_id] = {
                "employee_id": employee_id,
                "goods_value": int(row["quantity"]) * int(row["unit_cost"]),
                "deposit": int(employee["deposit"]),
                "exposure": int(self.employee_exposure(conn, player_id, employee_id)),
            }

        completed = super()._process_tasks(conn, player_id, now)

        for row in due_handoffs:
            allocation_id = int(row["allocation_id"])
            snap = snapshots.get(allocation_id)
            if not snap:
                continue
            state = conn.execute(
                """SELECT t.status task_status, a.status allocation_status,
                          e.active, e.role
                   FROM employee_tasks t
                   JOIN retail_allocations a ON a.id=t.allocation_id
                   JOIN employees e ON e.id=a.wholesale_employee_id
                   WHERE t.id=? AND a.player_id=?""",
                (row["task_id"], player_id),
            ).fetchone()
            if (
                not state
                or state["task_status"] != "completed"
                or state["allocation_status"] not in {"preparing", "published"}
                or not state["active"]
                or state["role"] != "warehouse"
            ):
                continue
            if conn.execute(
                "SELECT 1 FROM wholesale_delivery_payments WHERE allocation_id=?",
                (allocation_id,),
            ).fetchone():
                continue

            policy = _policy_conn(conn, player_id, "warehouse")
            uncovered_total = max(0, snap["exposure"] - snap["deposit"])
            uncovered_value = min(snap["goods_value"], uncovered_total)
            base_amount = _money_from_bps(
                snap["goods_value"], int(policy["base_rate_bps"])
            )
            risk_amount = _money_from_bps(
                uncovered_value, int(policy["risk_rate_bps"])
            )
            amount = base_amount + risk_amount
            deposit_part = _deposit_part(
                amount, int(policy["deposit_contribution_pct"])
            )
            conn.execute(
                """INSERT INTO wholesale_delivery_payments(
                       allocation_id, player_id, employee_id, goods_value,
                       uncovered_value, base_amount, risk_amount, amount,
                       deposit_contribution
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    allocation_id,
                    player_id,
                    snap["employee_id"],
                    snap["goods_value"],
                    uncovered_value,
                    base_amount,
                    risk_amount,
                    amount,
                    deposit_part,
                ),
            )
            conn.execute(
                """UPDATE employees
                   SET jobs_done=jobs_done+1,
                       wages_accrued=wages_accrued+?,
                       deposit_accrued=deposit_accrued+?,
                       stress=MIN(100, stress+0.35), last_contact_at=?
                   WHERE id=? AND player_id=?""",
                (amount, deposit_part, iso(now), snap["employee_id"], player_id),
            )
            conn.execute(
                "UPDATE shops SET total_profit=total_profit-? WHERE player_id=?",
                (amount, player_id),
            )
        return completed

    def _simulate_management_events(self, conn, player_id: int, sim_hours: float, now) -> int:
        """Use existing staff events but discard individual raise requests."""
        before_id = int(
            conn.execute(
                "SELECT COALESCE(MAX(id),0) FROM inbox WHERE player_id=?",
                (player_id,),
            ).fetchone()[0]
        )
        created = super()._simulate_management_events(conn, player_id, sim_hours, now)
        obsolete = conn.execute(
            "SELECT id FROM inbox WHERE player_id=? AND id>? AND kind='raise_request'",
            (player_id, before_id),
        ).fetchall()
        if obsolete:
            conn.executemany(
                "DELETE FROM inbox WHERE id=?",
                [(int(row["id"]),) for row in obsolete],
            )
            created = max(0, int(created) - len(obsolete))
        conn.execute(
            """UPDATE employees SET deposit_accrued=0
               WHERE player_id=? AND wages_accrued=0 AND deposit_accrued<>0""",
            (player_id,),
        )
        return created


class CompensationGameService(DelayedDisputeGameService):
    """UI-facing commission policies and payroll."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(COMPENSATION_SCHEMA)
            for row in conn.execute("SELECT player_id FROM shops").fetchall():
                for role in DEFAULT_POLICIES:
                    _ensure_policy_conn(conn, int(row["player_id"]), role)

    def compensation_policy(self, player_id: int, role: str) -> dict[str, int]:
        if role not in DEFAULT_POLICIES:
            raise ValueError("Unsupported role")
        with self.db.connect() as conn:
            row = _policy_conn(conn, player_id, role)
            return {
                "fixed_fee": int(row["fixed_fee"]),
                "base_rate_bps": int(row["base_rate_bps"]),
                "risk_rate_bps": int(row["risk_rate_bps"]),
                "deposit_contribution_pct": int(row["deposit_contribution_pct"]),
            }

    @staticmethod
    def _policy_score(role: str, values: dict[str, int]) -> float:
        if role == "courier":
            gross = int(values["fixed_fee"]) + int(values["base_rate_bps"])
        else:
            gross = (
                500_000 * int(values["base_rate_bps"]) / 10000.0
                + 150_000 * int(values["risk_rate_bps"]) / 10000.0
            )
        return gross * (1.0 - int(values["deposit_contribution_pct"]) / 200.0)

    def adjust_compensation_policy(
        self, player_id: int, role: str, field: str, delta: int
    ) -> dict:
        if role not in DEFAULT_POLICIES:
            raise ValueError("Unsupported role")
        ranges = {
            "courier": {
                "fixed_fee": (0, 1000, 50),
                "base_rate_bps": (100, 800, 50),
                "deposit_contribution_pct": (0, 50, 5),
            },
            "warehouse": {
                "base_rate_bps": (50, 500, 50),
                "risk_rate_bps": (0, 300, 50),
                "deposit_contribution_pct": (0, 50, 5),
            },
        }
        if field not in ranges[role]:
            raise ValueError("Unsupported compensation field")
        low, high, step = ranges[role][field]
        if delta not in {-step, step}:
            raise ValueError("Unsupported compensation adjustment")

        before = self.compensation_policy(player_id, role)
        old_value = int(before[field])
        new_value = max(low, min(high, old_value + delta))
        if new_value == old_value:
            return {
                "changed": False,
                "policy": before,
                "reaction": "Условия уже на предельном значении.",
            }

        after = dict(before)
        after[field] = new_value
        old_score = max(1.0, self._policy_score(role, before))
        new_score = max(1.0, self._policy_score(role, after))
        relative = new_score / old_score - 1.0
        if relative > 0.001:
            severity = min(1.0, relative / 0.20)
            loyalty_delta = 0.008 + 0.018 * severity
            stress_delta = -(0.4 + 1.6 * severity)
            reaction = "Условия стали выгоднее для сотрудников."
        elif relative < -0.001:
            severity = min(1.0, abs(relative) / 0.20)
            loyalty_delta = -(0.010 + 0.025 * severity)
            stress_delta = 0.6 + 2.4 * severity
            reaction = "Условия стали хуже для сотрудников."
        else:
            loyalty_delta = 0.0
            stress_delta = 0.0
            reaction = "Экономический эффект изменения почти нейтрален."

        with self.db.connect() as conn:
            conn.execute(
                f"""UPDATE staff_compensation_policies
                    SET {field}=?, updated_at=CURRENT_TIMESTAMP
                    WHERE player_id=? AND role=?""",
                (new_value, player_id, role),
            )
            conn.execute(
                """UPDATE employees
                   SET loyalty=MIN(1.0, MAX(0.0, loyalty+?)),
                       stress=MIN(100.0, MAX(0.0, stress+?))
                   WHERE player_id=? AND role=? AND active=1""",
                (loyalty_delta, stress_delta, player_id, role),
            )
            conn.execute(
                """INSERT INTO compensation_policy_changes(
                       player_id, role, field, old_value, new_value,
                       loyalty_delta, stress_delta
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    player_id,
                    role,
                    field,
                    old_value,
                    new_value,
                    loyalty_delta,
                    stress_delta,
                ),
            )
        return {
            "changed": True,
            "policy": self.compensation_policy(player_id, role),
            "reaction": reaction,
        }

    def buy_offer_for_employee(self, player_id: int, offer_id: int, employee_id: int) -> str:
        with self.db.connect() as conn:
            before = conn.execute(
                """SELECT jobs_done, wages_accrued, deposit_accrued, pay_per_job
                   FROM employees
                   WHERE id=? AND player_id=? AND active=1 AND role='warehouse'""",
                (employee_id, player_id),
            ).fetchone()
            max_task_id = int(
                conn.execute(
                    "SELECT COALESCE(MAX(id),0) FROM employee_tasks WHERE player_id=?",
                    (player_id,),
                ).fetchone()[0]
            )
        result = super().buy_offer_for_employee(player_id, offer_id, employee_id)
        if not before:
            return result
        with self.db.connect() as conn:
            receive_task = conn.execute(
                """SELECT id FROM employee_tasks
                   WHERE player_id=? AND employee_id=? AND kind='receive_batch' AND id>?
                   ORDER BY id LIMIT 1""",
                (player_id, employee_id, max_task_id),
            ).fetchone()
            if receive_task:
                after = conn.execute(
                    "SELECT jobs_done, wages_accrued, deposit_accrued FROM employees WHERE id=?",
                    (employee_id,),
                ).fetchone()
                receive_time_amount = int(before["pay_per_job"] or 0)
                if (
                    int(after["jobs_done"]) > int(before["jobs_done"])
                    and int(after["wages_accrued"]) >= int(before["wages_accrued"]) + receive_time_amount
                ):
                    conn.execute(
                        """UPDATE employees
                           SET jobs_done=?, wages_accrued=?, deposit_accrued=?
                           WHERE id=? AND player_id=?""",
                        (
                            int(before["jobs_done"]),
                            int(before["wages_accrued"]),
                            int(before["deposit_accrued"]),
                            employee_id,
                            player_id,
                        ),
                    )
        marker = f"Начислено за операцию: {int(before['pay_per_job'] or 0):,} ₽"
        if marker in result:
            result = result.replace(
                marker,
                "Оплата будет начислена после успешной передачи товара рознице.",
            )
        return result

    def wholesale_handoff_quote(
        self, player_id: int, batch_id: int, quantity: int
    ) -> dict[str, int] | None:
        with self.db.connect() as conn:
            batch = conn.execute(
                "SELECT * FROM batches WHERE id=? AND player_id=? AND status='warehouse'",
                (batch_id, player_id),
            ).fetchone()
            if not batch or not batch["responsible_employee_id"]:
                return None
            employee = conn.execute(
                """SELECT id, deposit FROM employees
                   WHERE id=? AND player_id=? AND active=1 AND role='warehouse'""",
                (batch["responsible_employee_id"], player_id),
            ).fetchone()
            if not employee:
                return None
            policy = _policy_conn(conn, player_id, "warehouse")
            quantity = max(1, min(int(quantity), int(batch["remaining"])))
            goods_value = quantity * int(batch["unit_cost"])
            exposure = int(
                self.simulation.employee_exposure(conn, player_id, int(employee["id"]))
            )
            uncovered_total = max(0, exposure - int(employee["deposit"]))
            uncovered_value = min(goods_value, uncovered_total)
            base_amount = _money_from_bps(goods_value, int(policy["base_rate_bps"]))
            risk_amount = _money_from_bps(uncovered_value, int(policy["risk_rate_bps"]))
            return {
                "goods_value": goods_value,
                "uncovered_value": uncovered_value,
                "base_amount": base_amount,
                "risk_amount": risk_amount,
                "amount": base_amount + risk_amount,
            }

    def process_payroll(self, player_id: int, now=None) -> dict | None:
        now = now or utcnow()
        speed = max(0.1, float(self.simulation.effective_speed(player_id)))
        with self.db.connect() as conn:
            settings = conn.execute(
                "SELECT * FROM settings WHERE player_id=?", (player_id,)
            ).fetchone()
            if not settings:
                return None
            if not settings["last_payroll_at"]:
                conn.execute(
                    "UPDATE settings SET last_payroll_at=? WHERE player_id=?",
                    (iso(now), player_id),
                )
                return None
            last = parse_dt(settings["last_payroll_at"])
            elapsed_game_hours = max(0.0, (now - last).total_seconds() / 3600.0) * speed
            if elapsed_game_hours < 24.0:
                return None

            employees = conn.execute(
                "SELECT * FROM employees WHERE player_id=? AND wages_accrued>0 ORDER BY id",
                (player_id,),
            ).fetchall()
            gross = sum(int(e["wages_accrued"]) for e in employees)
            if gross <= 0:
                conn.execute(
                    "UPDATE settings SET last_payroll_at=? WHERE player_id=?",
                    (iso(now), player_id),
                )
                return {"gross": 0, "cash": 0, "deposit": 0, "employees": 0, "status": "empty"}

            settlements = []
            cash_due = 0
            deposit_due = 0
            for employee in employees:
                accrued = int(employee["wages_accrued"])
                deposit_part = max(0, min(accrued, int(employee["deposit_accrued"])))
                cash_part = accrued - deposit_part
                cash_due += cash_part
                deposit_due += deposit_part
                settlements.append((employee, accrued, cash_part, deposit_part))

            balance = int(
                conn.execute(
                    "SELECT balance FROM shops WHERE player_id=?", (player_id,)
                ).fetchone()[0]
            )
            if balance < cash_due:
                existing = conn.execute(
                    """SELECT 1 FROM inbox
                       WHERE player_id=? AND status='open' AND kind='payroll_shortfall'""",
                    (player_id,),
                ).fetchone()
                if not existing:
                    shortage = cash_due - balance
                    conn.execute(
                        """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json)
                           VALUES (?, 'payroll_shortfall', 'urgent', 'Не хватает на выплаты', ?, '{}')""",
                        (
                            player_id,
                            f"К выплате деньгами: {cash_due:,} ₽\n"
                            f"На счету: {balance:,} ₽\n\n"
                            f"🔴 Не хватает {shortage:,} ₽. Выплата сотрудникам задержана.",
                        ),
                    )
                return {
                    "gross": gross,
                    "cash": cash_due,
                    "deposit": deposit_due,
                    "employees": len(employees),
                    "status": "shortfall",
                }

            conn.execute(
                "UPDATE shops SET balance=balance-? WHERE player_id=?",
                (cash_due, player_id),
            )
            for employee, accrued, cash_part, deposit_part in settlements:
                conn.execute(
                    """UPDATE employees
                       SET wages_accrued=0, deposit_accrued=0,
                           total_wages_paid=total_wages_paid+?,
                           deposit=deposit+?, deposit_from_wages=deposit_from_wages+?
                       WHERE id=?""",
                    (accrued, deposit_part, deposit_part, employee["id"]),
                )
                conn.execute(
                    """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                       VALUES (?, ?, 'salary', 'employee', ?, ?)""",
                    (
                        player_id,
                        -cash_part,
                        employee["id"],
                        f"Суточная выплата {employee['alias']}: {cash_part:,} ₽; в депозит {deposit_part:,} ₽",
                    ),
                )

            conn.execute(
                """INSERT INTO payroll_runs(
                       player_id, gross_wages, cash_paid, deposit_added, employee_count
                   ) VALUES (?, ?, ?, ?, ?)""",
                (player_id, gross, cash_due, deposit_due, len(employees)),
            )
            conn.execute(
                "UPDATE settings SET last_payroll_at=? WHERE player_id=?",
                (iso(now), player_id),
            )
            conn.execute(
                """UPDATE inbox SET status='closed'
                   WHERE player_id=? AND status='open' AND kind='payroll_shortfall'""",
                (player_id,),
            )
            conn.execute(
                """INSERT INTO inbox(
                       player_id, kind, priority, title, body, payload_json, expires_at
                   ) VALUES (?, 'payroll_report', 'normal', 'Суточные выплаты', ?, '{}', ?)""",
                (
                    player_id,
                    f"Начислено: {gross:,} ₽\n"
                    f"Выплачено деньгами: {cash_due:,} ₽\n"
                    f"Переведено в депозиты: {deposit_due:,} ₽\n\n"
                    f"Сотрудников в выплате: {len(employees)}",
                    iso(now + timedelta(hours=12 / speed)),
                ),
            )
            return {
                "gross": gross,
                "cash": cash_due,
                "deposit": deposit_due,
                "employees": len(employees),
                "status": "paid",
            }

    def process_payroll_all(self) -> None:
        with self.db.connect() as conn:
            player_ids = [int(row[0]) for row in conn.execute("SELECT player_id FROM shops").fetchall()]
        for player_id in player_ids:
            self.process_payroll(player_id)

    def payroll_summary(self, player_id: int) -> str:
        now = utcnow()
        speed = max(0.1, float(self.simulation.effective_speed(player_id)))
        with self.db.connect() as conn:
            settings = conn.execute(
                "SELECT * FROM settings WHERE player_id=?", (player_id,)
            ).fetchone()
            rows = conn.execute(
                """SELECT alias, role, deposit, wages_accrued, deposit_accrued,
                          total_wages_paid, deposit_from_wages, active
                   FROM employees WHERE player_id=?
                   ORDER BY active DESC, wages_accrued DESC, alias""",
                (player_id,),
            ).fetchall()
            seven = conn.execute(
                """SELECT COALESCE(SUM(gross_wages),0) gross,
                          COALESCE(SUM(cash_paid),0) cash,
                          COALESCE(SUM(deposit_added),0) deposit
                   FROM payroll_runs
                   WHERE player_id=? AND created_at>=datetime('now','-7 day')""",
                (player_id,),
            ).fetchone()
        accrued = sum(int(row["wages_accrued"]) for row in rows)
        deposit_accrued = sum(int(row["deposit_accrued"]) for row in rows)
        last = parse_dt(settings["last_payroll_at"]) if settings and settings["last_payroll_at"] else now
        elapsed_game = max(0.0, (now - last).total_seconds() / 3600.0) * speed
        remaining_game = max(0.0, 24.0 - elapsed_game)
        remaining_real_minutes = remaining_game / speed * 60.0
        real_eta = (
            f"~{remaining_real_minutes / 60.0:.1f} ч"
            if remaining_real_minutes >= 120
            else f"~{remaining_real_minutes:.0f} мин"
        )
        lines = []
        for row in rows[:12]:
            status = "" if row["active"] else " · ушёл"
            role = "опт" if row["role"] == "warehouse" else "розница"
            cash = int(row["wages_accrued"]) - int(row["deposit_accrued"])
            lines.append(
                f"{row['alias']} · {role}{status}\n"
                f"Начислено {row['wages_accrued']:,} ₽ · деньгами {cash:,} ₽ · "
                f"в депозит {row['deposit_accrued']:,} ₽"
            )
        return (
            "<b>💸 Выплаты сотрудникам</b>\n\n"
            "<b>Следующая выплата</b>\n"
            f"Через ~{remaining_game:.1f} игровых ч · {real_eta}\n"
            f"Скорость: x{speed:g}\n"
            f"Начислено сейчас: <b>{accrued:,} ₽</b>\n"
            f"Из них в депозит: {deposit_accrued:,} ₽\n\n"
            "<b>За 7 реальных дней</b>\n"
            f"Начислено: {seven['gross']:,} ₽\n"
            f"Выплачено деньгами: {seven['cash']:,} ₽\n"
            f"Переведено в депозиты: {seven['deposit']:,} ₽\n\n"
            "<b>По сотрудникам</b>\n"
            + ("\n\n".join(lines) if lines else "Нет сотрудников.")
        )

    def employee_details(self, player_id: int, employee_id: int) -> str | None:
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=?",
                (employee_id, player_id),
            ).fetchone()
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
            text += "<b>Продуктивность</b>\n" + "\n".join(
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
        if role == "courier":
            text += f"\nОценок работы: {service['count']}"
            if service["count"]:
                text += f" · ⭐ {float(service['avg']):.2f}/5"
        if unsecured > 0:
            text += "\n\n🔴 Часть товара не покрыта депозитом. Это осознанный дополнительный риск."
        return text

    def change_employee_role(self, player_id: int, employee_id: int) -> str:
        result = super().change_employee_role(player_id, employee_id)
        with self.db.connect() as conn:
            if conn.execute(
                "SELECT 1 FROM employees WHERE id=? AND player_id=? AND active=1",
                (employee_id, player_id),
            ).fetchone():
                conn.execute(
                    "UPDATE employees SET pay_per_job=0, deposit_contribution_pct=0 WHERE id=?",
                    (employee_id,),
                )
        return result

    def hire_candidate(self, player_id: int, candidate_id: int) -> str:
        with self.db.connect() as conn:
            candidate = conn.execute(
                "SELECT * FROM candidates WHERE id=? AND player_id=? AND status='open'",
                (candidate_id, player_id),
            ).fetchone()
            if not candidate:
                return "Кандидат уже недоступен."
            deposit = int(candidate["deposit"])
            cur = conn.execute(
                """INSERT INTO employees(
                       player_id, alias, role, pay_per_job, deposit,
                       deposit_contribution_pct, deposit_accrued, has_car,
                       reliability, attention, honesty, loyalty
                   ) VALUES (?, ?, ?, 0, ?, 0, 0, ?, ?, ?, ?, ?)""",
                (
                    player_id,
                    candidate["alias"],
                    candidate["role"],
                    deposit,
                    candidate["has_car"],
                    candidate["reliability"],
                    candidate["attention"],
                    candidate["honesty"],
                    candidate["loyalty"],
                ),
            )
            employee_id = int(cur.lastrowid)
            conn.execute(
                "UPDATE shops SET balance=balance+? WHERE player_id=?",
                (deposit, player_id),
            )
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, ?, 'deposit_in', 'employee', ?, ?)""",
                (
                    player_id,
                    deposit,
                    employee_id,
                    f"Стартовый депозит сотрудника {candidate['alias']}",
                ),
            )
            conn.execute("UPDATE candidates SET status='hired' WHERE id=?", (candidate_id,))
        self.simulation._ensure_packaging_rules(player_id)
        policy = self.compensation_policy(player_id, str(candidate["role"]))
        if candidate["role"] == "courier":
            terms = f"{policy['fixed_fee']:,} ₽ за заказ + {policy['base_rate_bps'] / 100:.1f}% с продажи"
        else:
            terms = (
                f"{policy['base_rate_bps'] / 100:.1f}% от передачи + "
                f"{policy['risk_rate_bps'] / 100:.1f}% за непокрытый риск"
            )
        return (
            f"<b>{candidate['alias']} принят.</b>\n\n"
            f"Условия: {terms}\n"
            f"В депозит из заработка: {policy['deposit_contribution_pct']}%\n"
            f"Стартовый депозит: {deposit:,} ₽"
        )
