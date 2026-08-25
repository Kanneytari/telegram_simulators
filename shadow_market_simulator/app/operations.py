from __future__ import annotations

from .dispute_payments import DisputePaymentMixin
from .game import GameService
from .nightshift import NightshiftSimulationMixin
from .runtime import PlayerSimulationEngine


class OperationsSimulationEngine(NightshiftSimulationMixin, PlayerSimulationEngine):
    """Adds accountable wholesale inventory to the core simulation."""

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        if not created:
            return False
        with self.db.connect() as conn:
            warehouse = conn.execute(
                "SELECT id FROM employees WHERE player_id=? AND role='warehouse' AND active=1 LIMIT 1",
                (player_id,),
            ).fetchone()
            if warehouse:
                warehouse_id = int(warehouse["id"])
            else:
                deposit = 700_000
                cur = conn.execute(
                    """INSERT INTO employees(
                           player_id, alias, role, deposit, has_car,
                           reliability, attention, honesty, loyalty, stress
                       ) VALUES (?, 'Маяк', 'warehouse', ?, 1, 0.91, 0.88, 0.93, 0.78, 10)""",
                    (player_id, deposit),
                )
                warehouse_id = int(cur.lastrowid)
            deposits = int(
                conn.execute(
                    "SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1",
                    (player_id,),
                ).fetchone()[0]
            )
            conn.execute(
                "UPDATE shops SET balance=balance+? WHERE player_id=?",
                (deposits, player_id),
            )
            conn.execute(
                "INSERT INTO ledger(player_id, amount, kind, note) VALUES (?, ?, 'deposit_in', 'Стартовые депозиты команды')",
                (player_id, deposits),
            )
            conn.execute(
                "UPDATE batches SET responsible_employee_id=? WHERE player_id=? AND responsible_employee_id IS NULL",
                (warehouse_id, player_id),
            )
        return True


class OperationsGameService(DisputePaymentMixin, GameService):
    """UI-facing accountable inventory and employment operations."""

    def employee_inventory(self, player_id: int, employee_id: int):
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT b.*, p.title product_title
                   FROM batches b JOIN products p ON p.id=b.product_id
                   WHERE b.player_id=? AND b.responsible_employee_id=?
                     AND b.status='warehouse' AND b.remaining>0
                   ORDER BY b.acquired_at DESC""",
                (player_id, employee_id),
            ).fetchall()

    def batch_transfer_options(self, player_id: int, batch_id: int):
        with self.db.connect() as conn:
            batch = conn.execute(
                "SELECT * FROM batches WHERE id=? AND player_id=? AND status='warehouse'",
                (batch_id, player_id),
            ).fetchone()
            if not batch:
                return None, []
            value = int(batch["remaining"] * batch["unit_cost"])
            employees = conn.execute(
                """SELECT e.*,
                          COALESCE((SELECT SUM(b.remaining*b.unit_cost) FROM batches b
                                    WHERE b.player_id=e.player_id
                                      AND b.responsible_employee_id=e.id
                                      AND b.status='warehouse'),0) exposure
                   FROM employees e
                   WHERE e.player_id=? AND e.active=1 AND e.role='warehouse' AND e.id<>?
                   ORDER BY e.deposit DESC""",
                (player_id, batch["responsible_employee_id"] or -1),
            ).fetchall()
        options = []
        for employee in employees:
            free = max(0, int(employee["deposit"]) - int(employee["exposure"] or 0))
            options.append(
                {
                    "id": int(employee["id"]),
                    "alias": employee["alias"],
                    "free": free,
                    "eligible": free >= value,
                }
            )
        return batch, options

    def reassign_batch(self, player_id: int, batch_id: int, employee_id: int) -> str:
        batch, options = self.batch_transfer_options(player_id, batch_id)
        if not batch:
            return "Партия не найдена."
        target = next((row for row in options if row["id"] == employee_id), None)
        if not target or not target["eligible"]:
            return "У выбранного сотрудника недостаточно свободного покрытия."
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE batches SET responsible_employee_id=? WHERE id=? AND player_id=?",
                (employee_id, batch_id, player_id),
            )
        return f"Партия #{batch_id} передана сотруднику {target['alias']}."

    def fire_employee(self, player_id: int, employee_id: int) -> dict:
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=? AND active=1",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                return {
                    "status": "missing",
                    "message": "Сотрудник уже не работает в магазине.",
                }
            exposure = int(
                conn.execute(
                    """SELECT COALESCE(SUM(remaining*unit_cost),0) FROM batches
                       WHERE player_id=? AND responsible_employee_id=? AND status='warehouse'""",
                    (player_id, employee_id),
                ).fetchone()[0]
            )
            if exposure > 0:
                return {
                    "status": "inventory",
                    "message": (
                        "Нельзя уволить сотрудника: на нём числится товар на "
                        f"{exposure:,} ₽. Сначала передай партии другому оптовому сотруднику."
                    ),
                }
            payout = int(employee["deposit"]) + int(employee["wages_accrued"])
            balance = int(
                conn.execute(
                    "SELECT balance FROM shops WHERE player_id=?", (player_id,)
                ).fetchone()[0]
            )
            if balance < payout:
                return {
                    "status": "money",
                    "message": f"Для расчёта нужно {payout:,} ₽, на счёте {balance:,} ₽.",
                }
            conn.execute(
                "UPDATE shops SET balance=balance-? WHERE player_id=?",
                (payout, player_id),
            )
            conn.execute(
                """UPDATE employees SET active=0, available=0, deposit=0,
                       total_wages_paid=total_wages_paid+wages_accrued, wages_accrued=0
                   WHERE id=?""",
                (employee_id,),
            )
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, ?, 'employee_settlement', 'employee', ?, ?)""",
                (
                    player_id,
                    -payout,
                    employee_id,
                    f"Расчёт при увольнении {employee['alias']}",
                ),
            )
            conn.execute(
                """UPDATE inbox SET status='closed'
                   WHERE player_id=? AND status='open'
                     AND json_extract(payload_json, '$.employee_id')=?""",
                (player_id, employee_id),
            )
        return {
            "status": "ok",
            "message": f"{employee['alias']} уволен. Итоговый расчёт: {payout:,} ₽.",
        }
