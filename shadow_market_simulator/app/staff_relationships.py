from __future__ import annotations

from .compensation import CompensationGameService, CompensationSimulationEngine
from .simulation import iso


SALES_ACTIVITY_MULTIPLIER = 5.0




def _apply_relationship_delta(
    conn,
    player_id: int,
    employee_id: int,
    *,
    kind: str,
    loyalty_delta: float,
    stress_delta: float,
    reference_type: str | None = None,
    reference_id: int | None = None,
) -> None:
    employee = conn.execute(
        "SELECT id FROM employees WHERE id=? AND player_id=? AND active=1",
        (employee_id, player_id),
    ).fetchone()
    if not employee:
        return
    conn.execute(
        """UPDATE employees
           SET loyalty=MIN(1.0, MAX(0.0, loyalty+?)),
               stress=MIN(100.0, MAX(0.0, stress+?))
           WHERE id=? AND player_id=? AND active=1""",
        (float(loyalty_delta), float(stress_delta), employee_id, player_id),
    )
    conn.execute(
        """INSERT INTO staff_relationship_events(
               player_id, employee_id, kind, reference_type, reference_id,
               loyalty_delta, stress_delta
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            player_id,
            employee_id,
            kind,
            reference_type,
            reference_id,
            float(loyalty_delta),
            float(stress_delta),
        ),
    )


def _apply_overexposure_effect(
    conn,
    player_id: int,
    employee_id: int,
    exposure_before: int,
    exposure_after: int,
    *,
    reference_type: str,
    reference_id: int | None,
) -> bool:
    employee = conn.execute(
        "SELECT deposit FROM employees WHERE id=? AND player_id=? AND active=1",
        (employee_id, player_id),
    ).fetchone()
    if not employee:
        return False

    deposit = max(0, int(employee["deposit"]))
    before_unsecured = max(0, int(exposure_before) - deposit)
    after_unsecured = max(0, int(exposure_after) - deposit)
    added_unsecured = max(0, after_unsecured - before_unsecured)
    if added_unsecured <= 0:
        return False

    basis = max(deposit, 50_000)
    severity = min(1.0, added_unsecured / basis)
    _apply_relationship_delta(
        conn,
        player_id,
        employee_id,
        kind="overexposure_trust",
        loyalty_delta=0.025 * severity,
        stress_delta=5.0 * severity,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    return True


class StaffRelationshipSimulationEngine(CompensationSimulationEngine):
    """Hidden staff reactions plus the live sales pacing multiplier."""


    def _process_tasks(self, conn, player_id: int, now) -> int:
        due_handoffs = conn.execute(
            """SELECT t.id task_id, t.allocation_id, a.retail_employee_id
               FROM employee_tasks t
               JOIN retail_allocations a ON a.id=t.allocation_id
               WHERE t.player_id=? AND t.kind='handoff' AND t.status='active'
                 AND t.completes_at<=?""",
            (player_id, iso(now)),
        ).fetchall()
        before = {
            int(row["allocation_id"]): self.employee_exposure(
                conn, player_id, int(row["retail_employee_id"])
            )
            for row in due_handoffs
        }

        completed = super()._process_tasks(conn, player_id, now)

        for row in due_handoffs:
            allocation_id = int(row["allocation_id"])
            employee_id = int(row["retail_employee_id"])
            state = conn.execute(
                "SELECT status FROM retail_allocations WHERE id=? AND player_id=?",
                (allocation_id, player_id),
            ).fetchone()
            if not state or state["status"] not in {"preparing", "published"}:
                continue
            exposure_after = self.employee_exposure(conn, player_id, employee_id)
            _apply_overexposure_effect(
                conn,
                player_id,
                employee_id,
                int(before.get(allocation_id, 0)),
                int(exposure_after),
                reference_type="allocation",
                reference_id=allocation_id,
            )

        return completed


class StaffRelationshipGameService(CompensationGameService):
    """Hidden trust, pressure and employer-support effects."""

    def buy_offer_for_employee(self, player_id: int, offer_id: int, employee_id: int) -> str:
        exposure_before = self._employee_exposure(player_id, employee_id)
        result = super().buy_offer_for_employee(player_id, offer_id, employee_id)
        exposure_after = self._employee_exposure(player_id, employee_id)
        if exposure_after > exposure_before:
            with self.db.connect() as conn:
                _apply_overexposure_effect(
                    conn,
                    player_id,
                    employee_id,
                    exposure_before,
                    exposure_after,
                    reference_type="offer",
                    reference_id=offer_id,
                )
        return result

    def assign_unassigned_batch(self, player_id: int, batch_id: int, employee_id: int) -> str:
        exposure_before = self._employee_exposure(player_id, employee_id)
        result = super().assign_unassigned_batch(player_id, batch_id, employee_id)
        exposure_after = self._employee_exposure(player_id, employee_id)
        if exposure_after > exposure_before:
            with self.db.connect() as conn:
                _apply_overexposure_effect(
                    conn,
                    player_id,
                    employee_id,
                    exposure_before,
                    exposure_after,
                    reference_type="batch",
                    reference_id=batch_id,
                )
        return result

    def resolve_dispute_with_source(
        self,
        player_id: int,
        dispute_id: int,
        decision: str,
        source: str,
    ) -> str:
        with self.db.connect() as conn:
            before = conn.execute(
                """SELECT d.status, d.true_cause, o.employee_id
                   FROM disputes d
                   JOIN orders o ON o.id=d.order_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()

        result = super().resolve_dispute_with_source(
            player_id, dispute_id, decision, source
        )
        if not before or before["status"] != "open" or decision == "reject":
            return result

        with self.db.connect() as conn:
            after = conn.execute(
                "SELECT status, refund_source FROM disputes WHERE id=? AND player_id=?",
                (dispute_id, player_id),
            ).fetchone()
            if not after or after["status"] != "resolved":
                return result

            employee_id = int(before["employee_id"])
            full = decision == "refund"
            employee_fault = before["true_cause"] in {"EMPLOYEE_ERROR", "DESCRIPTION_ERROR"}

            if after["refund_source"] == "shop":
                loyalty_delta = 0.028 if full else 0.018
                stress_delta = -4.0 if full else -3.0
                if employee_fault:
                    loyalty_delta += 0.010
                    stress_delta -= 1.0
                _apply_relationship_delta(
                    conn,
                    player_id,
                    employee_id,
                    kind="shop_absorbed_refund",
                    loyalty_delta=loyalty_delta,
                    stress_delta=stress_delta,
                    reference_type="dispute",
                    reference_id=dispute_id,
                )
            elif after["refund_source"] == "employee":
                _apply_relationship_delta(
                    conn,
                    player_id,
                    employee_id,
                    kind="employee_deposit_refund",
                    loyalty_delta=-0.035 if full else -0.020,
                    stress_delta=0.0,
                    reference_type="dispute",
                    reference_id=dispute_id,
                )

        return result
