from __future__ import annotations

from .couriers.idle import courier_idle_ready
from ..staff_relationships import StaffRelationshipGameService


class IdleAwareGameService(StaffRelationshipGameService):
    """Expose one consistent 'completely idle courier' flag to every UI surface."""

    def employees(self, player_id: int):
        rows = super().employees(player_id)
        with self.db.connect() as conn:
            for row in rows:
                row["idle_ready"] = courier_idle_ready(
                    conn, player_id, int(row["id"])
                )
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
                row["idle_ready"] = courier_idle_ready(
                    conn, player_id, int(row["id"])
                )
        return batch, rows

    def allocate_to_retail(
        self,
        player_id: int,
        batch_id: int,
        retail_employee_id: int,
        quantity: int,
    ) -> str:
        with self.db.connect() as conn:
            employee = conn.execute(
                """SELECT active, available, role FROM employees
                   WHERE id=? AND player_id=?""",
                (retail_employee_id, player_id),
            ).fetchone()
        if not employee or not employee["active"] or employee["role"] != "courier":
            return "Закладчик недоступен."
        if not employee["available"]:
            return (
                "Сотрудник сейчас на паузе или недоступен и не может принять новую передачу."
            )

        result = super().allocate_to_retail(
            player_id, batch_id, retail_employee_id, quantity
        )
        if not result.startswith("Назначено "):
            return result

        with self.db.connect() as conn:
            allocation = conn.execute(
                """SELECT a.quantity, a.unit_cost, p.title product_title,
                          w.alias wholesale_alias, r.alias retail_alias,
                          r.deposit retail_deposit
                   FROM retail_allocations a
                   JOIN products p ON p.id=a.product_id
                   JOIN employees w ON w.id=a.wholesale_employee_id
                   JOIN employees r ON r.id=a.retail_employee_id
                   WHERE a.player_id=? AND a.batch_id=?
                     AND a.retail_employee_id=?
                   ORDER BY a.id DESC LIMIT 1""",
                (player_id, batch_id, retail_employee_id),
            ).fetchone()
        if not allocation:
            return result

        allocated = int(allocation["quantity"])
        retail_after = (
            self._employee_exposure(player_id, retail_employee_id)
            + allocated * int(allocation["unit_cost"])
        )
        unsecured = max(
            0,
            retail_after - int(allocation["retail_deposit"]),
        )
        warning = (
            "\n\n🔴 После получения у закладчика будет не покрыто "
            f"депозитом: {unsecured:,} ₽."
            if unsecured
            else ""
        )
        return (
            "<b>✅ Принято</b>\n\n"
            f"Назначено <b>{allocated} ед.</b> "
            f"{allocation['product_title']} сотруднику "
            f"👤 {allocation['retail_alias']}.\n\n"
            f"🚚 {allocation['wholesale_alias']} готовит мастер-клад. "
            f"После завершения 👤 {allocation['retail_alias']} "
            f"автоматически начнёт подготовку товара к витрине."
            f"{warning}"
        )
