from __future__ import annotations

from .simulation import iso
from .workflow import WORKFLOW_SCHEMA, WorkflowGameService, WorkflowSimulationEngine


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
