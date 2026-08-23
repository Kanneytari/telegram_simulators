from __future__ import annotations

from .delayed_disputes import DelayedDisputeGameService, DelayedDisputeSimulationEngine
from .simulation import iso


WHOLESALE_COMPENSATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS wholesale_delivery_payments (
    allocation_id INTEGER PRIMARY KEY REFERENCES retail_allocations(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    amount INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wholesale_delivery_payments_employee
    ON wholesale_delivery_payments(player_id, employee_id, created_at);
"""


class WholesaleCompensationSimulationEngine(DelayedDisputeSimulationEngine):
    """Pays wholesale staff once for each successfully completed handoff to retail."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(WHOLESALE_COMPENSATION_SCHEMA)

    def _process_tasks(self, conn, player_id: int, now) -> int:
        # Snapshot due handoffs before the base workflow completes them. New retail
        # preparation tasks created by those handoffs are intentionally not part of
        # this list.
        due_handoffs = conn.execute(
            """SELECT t.id task_id, t.allocation_id, a.wholesale_employee_id
               FROM employee_tasks t
               JOIN retail_allocations a ON a.id=t.allocation_id
               WHERE t.player_id=?
                 AND t.kind='handoff'
                 AND t.status='active'
                 AND t.completes_at<=?""",
            (player_id, iso(now)),
        ).fetchall()

        completed = super()._process_tasks(conn, player_id, now)

        for handoff in due_handoffs:
            # Compensation is earned only if the handoff actually completed and the
            # allocation reached the retail employee. A blocked/lost handoff is not paid.
            state = conn.execute(
                """SELECT t.status task_status, a.status allocation_status,
                          e.id employee_id, e.pay_per_job, e.active, e.role
                   FROM employee_tasks t
                   JOIN retail_allocations a ON a.id=t.allocation_id
                   JOIN employees e ON e.id=a.wholesale_employee_id
                   WHERE t.id=? AND a.player_id=?""",
                (handoff["task_id"], player_id),
            ).fetchone()
            if not state:
                continue
            if state["task_status"] != "completed":
                continue
            if state["allocation_status"] not in {"preparing", "published"}:
                continue
            if not state["active"] or state["role"] != "warehouse":
                continue

            already_paid = conn.execute(
                "SELECT 1 FROM wholesale_delivery_payments WHERE allocation_id=?",
                (handoff["allocation_id"],),
            ).fetchone()
            if already_paid:
                continue

            amount = int(state["pay_per_job"])
            conn.execute(
                """INSERT INTO wholesale_delivery_payments(
                       allocation_id, player_id, employee_id, amount
                   ) VALUES (?, ?, ?, ?)""",
                (handoff["allocation_id"], player_id, state["employee_id"], amount),
            )
            conn.execute(
                """UPDATE employees
                   SET jobs_done=jobs_done+1,
                       wages_accrued=wages_accrued+?,
                       stress=MIN(100, stress+0.35),
                       last_contact_at=?
                   WHERE id=? AND player_id=?""",
                (amount, iso(now), state["employee_id"], player_id),
            )

        return completed


class WholesaleCompensationGameService(DelayedDisputeGameService):
    """Removes the legacy procurement-time wage and keeps pay tied to retail handoffs."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(WHOLESALE_COMPENSATION_SCHEMA)

    def buy_offer_for_employee(self, player_id: int, offer_id: int, employee_id: int) -> str:
        # The inherited procurement implementation historically counted receiving a
        # supplier batch as a paid wholesale operation. Preserve all procurement logic,
        # then neutralize only that legacy wage/job increment when a receive task was
        # actually created. Wholesale pay is now awarded by the simulation when the
        # employee completes a handoff to retail.
        with self.db.connect() as conn:
            before = conn.execute(
                """SELECT jobs_done, wages_accrued, pay_per_job
                   FROM employees
                   WHERE id=? AND player_id=? AND active=1 AND role='warehouse'""",
                (employee_id, player_id),
            ).fetchone()
            max_task_id = int(conn.execute(
                "SELECT COALESCE(MAX(id),0) FROM employee_tasks WHERE player_id=?",
                (player_id,),
            ).fetchone()[0])

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
            if not receive_task:
                return result

            after = conn.execute(
                "SELECT jobs_done, wages_accrued FROM employees WHERE id=? AND player_id=?",
                (employee_id, player_id),
            ).fetchone()
            amount = int(before["pay_per_job"])
            jobs_delta = int(after["jobs_done"]) - int(before["jobs_done"])
            wages_delta = int(after["wages_accrued"]) - int(before["wages_accrued"])
            if jobs_delta >= 1 and wages_delta >= amount:
                conn.execute(
                    """UPDATE employees
                       SET jobs_done=jobs_done-1,
                           wages_accrued=MAX(0, wages_accrued-?)
                       WHERE id=? AND player_id=?""",
                    (amount, employee_id, player_id),
                )

        legacy_line = f"Начислено за операцию: {int(before['pay_per_job']):,} ₽"
        if legacy_line in result:
            result = result.replace(
                legacy_line,
                "Оплата начислится после передачи товара розничному сотруднику.",
            )
        return result
