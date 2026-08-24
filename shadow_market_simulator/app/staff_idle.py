from __future__ import annotations

from .courier_idle import courier_idle_ready
from .staff_relationships import StaffRelationshipGameService


class IdleAwareGameService(StaffRelationshipGameService):
    """Expose one consistent 'completely idle courier' flag to every UI surface."""

    def employees(self, player_id: int):
        rows = super().employees(player_id)
        with self.db.connect() as conn:
            for row in rows:
                row["idle_ready"] = courier_idle_ready(conn, player_id, int(row["id"]))
        return rows

    def retail_staff_for_batch(self, player_id: int, batch_id: int):
        batch, rows = super().retail_staff_for_batch(player_id, batch_id)
        if not batch:
            return batch, rows
        with self.db.connect() as conn:
            for row in rows:
                employee = conn.execute(
                    "SELECT available FROM employees WHERE id=? AND player_id=? AND active=1",
                    (row["id"], player_id),
                ).fetchone()
                row["available"] = int(employee["available"]) if employee else 0
                row["status_text"] = self._task_status(player_id, int(row["id"]))
                row["idle_ready"] = courier_idle_ready(conn, player_id, int(row["id"]))
        return batch, rows

    def allocate_to_retail(self, player_id: int, batch_id: int, retail_employee_id: int, quantity: int) -> str:
        with self.db.connect() as conn:
            employee = conn.execute(
                """SELECT active, available, role FROM employees
                   WHERE id=? AND player_id=?""",
                (retail_employee_id, player_id),
            ).fetchone()
        if not employee or not employee["active"] or employee["role"] != "courier":
            return "Закладчик недоступен."
        if not employee["available"]:
            return "Сотрудник сейчас на паузе или недоступен и не может принять новую передачу."
        return super().allocate_to_retail(player_id, batch_id, retail_employee_id, quantity)
