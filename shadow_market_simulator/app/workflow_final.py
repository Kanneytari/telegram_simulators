from __future__ import annotations

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
