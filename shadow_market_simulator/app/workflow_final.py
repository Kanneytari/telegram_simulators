from __future__ import annotations

from .runtime import ROLE_MARKET_PAY
from .simulation import iso, parse_dt, utcnow
from .workflow import TASK_LABELS, WORKFLOW_SCHEMA, WorkflowGameService, WorkflowSimulationEngine


class FinalWorkflowSimulationEngine(WorkflowSimulationEngine):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(WORKFLOW_SCHEMA)
            # Reuse the existing staff-inbox UX for dishonest exits.
            conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS trg_employee_theft_to_staff_inbox
                AFTER INSERT ON inbox
                WHEN NEW.kind='employee_theft'
                BEGIN
                    UPDATE inbox SET kind='employee_exit' WHERE id=NEW.id;
                END;
                """
            )

    def _create_retail_order(self, conn, player_id: int, listing, now) -> bool | None:
        position = conn.execute(
            """SELECT rp.id position_id, rp.allocation_id, rp.batch_id,
                      rp.employee_id retail_employee_id, rp.product_id,
                      rp.pack_size, rp.position_count,
                      rp.unit_cost position_unit_cost, rp.quality position_quality,
                      e.id employee_id, e.pay_per_job, e.deposit_contribution_pct,
                      e.attention, e.stress, e.honesty, e.loyalty
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
            (employee_cost, self.rng.uniform(0.05, 0.35), iso(now), position["employee_id"]),
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
                position["employee_id"],
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
        order_id = cur.lastrowid
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

        employee_view = {
            "id": int(position["employee_id"]),
            "attention": float(position["attention"]),
            "stress": float(position["stress"]),
            "honesty": float(position["honesty"]),
            "loyalty": float(position["loyalty"]),
        }
        probability = self._dispute_probability(client, employee_view, quality, float(listing["complaint_modifier"]))
        if self.rng.random() < probability:
            self._open_dispute(conn, player_id, order_id, client, employee_view, quality, revenue, now)
            return True
        self._create_review(conn, player_id, order_id, force=False)
        return False


class FinalWorkflowGameService(WorkflowGameService):
    def _task_status(self, player_id: int, employee_id: int) -> str:
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=?",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                return "неизвестно"
            if not employee["active"]:
                return "не работает"
            if not employee["available"]:
                return "временно недоступен"
            task = conn.execute(
                """SELECT * FROM employee_tasks
                   WHERE player_id=? AND employee_id=? AND status='active'
                   ORDER BY completes_at LIMIT 1""",
                (player_id, employee_id),
            ).fetchone()
            if task:
                remaining_real = max(0.0, (parse_dt(task["completes_at"]) - utcnow()).total_seconds() / 3600.0)
                remaining_game = remaining_real * self.simulation.effective_speed(player_id)
                eta = "<1 ч" if remaining_game < 1 else f"~{remaining_game:.1f} ч"
                return f"{TASK_LABELS.get(task['kind'], task['kind'])} · {eta}"

            if employee["role"] == "courier":
                waiting = int(conn.execute(
                    """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                       WHERE player_id=? AND retail_employee_id=? AND status='waiting'""",
                    (player_id, employee_id),
                ).fetchone()[0])
                if waiting:
                    return f"ожидает товар · {waiting} ед."
                positions = int(conn.execute(
                    """SELECT COALESCE(SUM(position_count),0) FROM retail_positions
                       WHERE player_id=? AND employee_id=? AND position_count>0""",
                    (player_id, employee_id),
                ).fetchone()[0])
                if positions:
                    return f"на витрине · {positions} поз."
            else:
                units = int(conn.execute(
                    """SELECT COALESCE(SUM(remaining),0) FROM batches
                       WHERE player_id=? AND responsible_employee_id=?
                         AND status='warehouse' AND remaining>0""",
                    (player_id, employee_id),
                ).fetchone()[0])
                if units:
                    return f"готово к распределению · {units} ед."
        return "свободен"

    def hire_candidate(self, player_id: int, candidate_id: int) -> str:
        result = super().hire_candidate(player_id, candidate_id)
        with self.db.connect() as conn:
            employee = conn.execute(
                """SELECT e.* FROM employees e
                   JOIN candidates c ON c.alias=e.alias AND c.player_id=e.player_id
                   WHERE c.id=? AND e.player_id=?
                   ORDER BY e.id DESC LIMIT 1""",
                (candidate_id, player_id),
            ).fetchone()
        if not employee:
            return result
        if employee["role"] == "courier":
            self.simulation._ensure_packaging_rules(player_id)
        role = "оптовый" if employee["role"] == "warehouse" else "розничный"
        return (
            f"<b>{employee['alias']} принят.</b>\n\n"
            f"Роль: {role}\n"
            f"Ставка: {employee['pay_per_job']:,} ₽ / операцию\n"
            f"В депозит: {employee['deposit_contribution_pct']}% заработка\n"
            f"Стартовый депозит: {employee['deposit']:,} ₽"
        )

    def _has_pending_assignment(self, player_id: int, employee_id: int) -> bool:
        with self.db.connect() as conn:
            return bool(conn.execute(
                """SELECT 1 FROM retail_allocations
                   WHERE player_id=? AND status IN ('waiting','preparing')
                     AND (retail_employee_id=? OR wholesale_employee_id=?) LIMIT 1""",
                (player_id, employee_id, employee_id),
            ).fetchone())

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
            pending = conn.execute(
                """SELECT 1 FROM retail_allocations
                   WHERE player_id=? AND status IN ('waiting','preparing')
                     AND (retail_employee_id=? OR wholesale_employee_id=?) LIMIT 1""",
                (player_id, employee_id, employee_id),
            ).fetchone()
            if exposure > 0 or active_task or pending:
                return "Сначала сотрудник должен завершить текущие задачи и не иметь назначенного товара."
            new_role = "warehouse" if employee["role"] == "courier" else "courier"
            new_pay = ROLE_MARKET_PAY[new_role]
            conn.execute("UPDATE employees SET role=?, pay_per_job=? WHERE id=?", (new_role, new_pay, employee_id))
            if new_role == "courier":
                products = conn.execute("SELECT id FROM products WHERE active=1").fetchall()
                for product in products:
                    conn.execute(
                        "INSERT OR IGNORE INTO packaging_rules(player_id, employee_id, product_id) VALUES (?, ?, ?)",
                        (player_id, employee_id, product["id"]),
                    )
        role_title = "оптовый" if new_role == "warehouse" else "розничный"
        return f"{employee['alias']} переведён в роль «{role_title}». Новая базовая ставка: {new_pay:,} ₽ / операцию."

    def fire_employee(self, player_id: int, employee_id: int) -> dict:
        if self._has_pending_assignment(player_id, employee_id):
            return {
                "status": "inventory",
                "message": "Нельзя уволить сотрудника: у него есть назначенная передача товара. Дождись завершения или сначала освободи его от ответственности.",
            }
        return super().fire_employee(player_id, employee_id)
