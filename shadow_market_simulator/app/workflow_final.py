from __future__ import annotations

import json
import math

from .simulation import iso, parse_dt, utcnow
from .workflow import TASK_LABELS, WorkflowGameService, WorkflowSimulationEngine


class FinalWorkflowSimulationEngine(WorkflowSimulationEngine):


    def _simulate_management_events(self, conn, player_id: int, sim_hours: float, now) -> int:
        created = super()._simulate_management_events(conn, player_id, sim_hours, now)
        hours = min(max(0.0, sim_hours), 12.0)
        if hours <= 0:
            return created

        employees = conn.execute(
            "SELECT * FROM employees WHERE player_id=? AND active=1 AND available=1 ORDER BY id",
            (player_id,),
        ).fetchall()
        for employee in employees:
            existing = conn.execute(
                """SELECT 1 FROM inbox
                   WHERE player_id=? AND status='open' AND kind='resignation_notice'
                     AND json_extract(payload_json, '$.employee_id')=? LIMIT 1""",
                (player_id, employee["id"]),
            ).fetchone()
            if existing:
                continue
            exposure = int(self.employee_exposure(conn, player_id, int(employee["id"])))
            if exposure > 0:
                continue
            active_task = conn.execute(
                "SELECT 1 FROM employee_tasks WHERE player_id=? AND employee_id=? AND status='active' LIMIT 1",
                (player_id, employee["id"]),
            ).fetchone()
            if active_task:
                continue

            loyalty_pressure = max(0.0, 0.58 - float(employee["loyalty"]))
            stress_pressure = max(0.0, float(employee["stress"]) - 72.0) / 100.0
            hourly_rate = loyalty_pressure * 0.020 + stress_pressure * 0.012
            probability = 1.0 - math.exp(-hourly_rate * hours)
            if probability <= 0 or self.rng.random() >= probability:
                continue

            payout = int(employee["deposit"]) + int(employee["wages_accrued"])
            role = "оптовый" if employee["role"] == "warehouse" else "розничный"
            conn.execute(
                "UPDATE employees SET available=0, unavailable_until=NULL WHERE id=?",
                (employee["id"],),
            )
            body = (
                f"{employee['alias']} сообщил, что хочет закончить работу.\n\n"
                f"Роль: {role}\n"
                f"Товар на ответственности: 0 ₽\n"
                f"Депозит к возврату: {employee['deposit']:,} ₽\n"
                f"Начисленная зарплата: {employee['wages_accrued']:,} ₽\n"
                f"Полный расчёт: <b>{payout:,} ₽</b>\n\n"
                "Сотрудник больше не берёт новые задачи. Проведи увольнение и расчёт из его профиля."
            )
            conn.execute(
                """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json)
                   VALUES (?, 'resignation_notice', 'important', 'Сотрудник хочет уйти', ?, ?)""",
                (
                    player_id,
                    body,
                    json.dumps({"employee_id": int(employee["id"])}, ensure_ascii=False),
                ),
            )
            created += 1
            break
        return created


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
            resignation = conn.execute(
                """SELECT 1 FROM inbox
                   WHERE player_id=? AND status='open' AND kind='resignation_notice'
                     AND json_extract(payload_json, '$.employee_id')=? LIMIT 1""",
                (player_id, employee_id),
            ).fetchone()
            if resignation:
                return "готовится уйти"
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
            conn.execute("UPDATE employees SET role=? WHERE id=?", (new_role, employee_id))
        role_title = "оптовый" if new_role == "warehouse" else "розничный"
        return f"{employee['alias']} переведён в роль «{role_title}»."

    def fire_employee(self, player_id: int, employee_id: int) -> dict:
        if self._has_pending_assignment(player_id, employee_id):
            return {
                "status": "inventory",
                "message": "Нельзя уволить сотрудника: у него есть назначенная передача товара. Дождись завершения или сначала освободи его от ответственности.",
            }
        return super().fire_employee(player_id, employee_id)
