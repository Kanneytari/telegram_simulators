from __future__ import annotations

from .delayed_disputes import DelayedDisputeGameService, DelayedDisputeSimulationEngine
from .simulation import iso


DEPOSIT_SHARE_COOLDOWN_GAME_HOURS = 12.0


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

CREATE TABLE IF NOT EXISTS deposit_share_negotiations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    from_pct INTEGER NOT NULL,
    to_pct INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    acceptance_chance REAL NOT NULL,
    game_hour REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_deposit_share_negotiations_employee
    ON deposit_share_negotiations(player_id, employee_id, game_hour);
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
    """Final game service for wholesale pay and staff deposit-share negotiations."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(WHOLESALE_COMPENSATION_SCHEMA)

    def _current_game_hour(self, player_id: int) -> float:
        getter = getattr(self.simulation, "current_game_hour", None)
        return float(getter(player_id)) if getter else 0.0

    @staticmethod
    def _normalize_deposit_share(value: int) -> int:
        value = max(0, min(50, int(value)))
        return int(round(value / 5.0) * 5)

    def deposit_share_context(self, player_id: int, employee_id: int, target_pct: int | None = None) -> dict | None:
        game_hour = self._current_game_hour(player_id)
        with self.db.connect() as conn:
            employee = conn.execute(
                """SELECT id, alias, role, pay_per_job, deposit_contribution_pct,
                          loyalty, stress, active
                   FROM employees
                   WHERE id=? AND player_id=?""",
                (employee_id, player_id),
            ).fetchone()
            if not employee or not employee["active"]:
                return None
            last = conn.execute(
                """SELECT game_hour FROM deposit_share_negotiations
                   WHERE player_id=? AND employee_id=?
                   ORDER BY id DESC LIMIT 1""",
                (player_id, employee_id),
            ).fetchone()

        current = int(employee["deposit_contribution_pct"] or 0)
        target = current if target_pct is None else self._normalize_deposit_share(target_pct)
        cooldown = 0.0
        if last:
            cooldown = max(0.0, DEPOSIT_SHARE_COOLDOWN_GAME_HOURS - (game_hour - float(last["game_hour"])))
        pay = int(employee["pay_per_job"])
        current_deposit = int(round(pay * current / 100.0))
        target_deposit = int(round(pay * target / 100.0))
        return {
            "id": int(employee["id"]),
            "alias": employee["alias"],
            "role": employee["role"],
            "pay_per_job": pay,
            "current_pct": current,
            "target_pct": target,
            "current_deposit": current_deposit,
            "current_cash": pay - current_deposit,
            "target_deposit": target_deposit,
            "target_cash": pay - target_deposit,
            "loyalty": float(employee["loyalty"]),
            "stress": float(employee["stress"]),
            "cooldown_game_hours": cooldown,
            "can_propose": cooldown <= 0.001 and target != current,
        }

    def propose_deposit_share(self, player_id: int, employee_id: int, target_pct: int) -> dict:
        context = self.deposit_share_context(player_id, employee_id, target_pct)
        if not context:
            return {"status": "missing", "text": "Сотрудник больше недоступен."}
        if context["target_pct"] == context["current_pct"]:
            return {"status": "same", "text": "Это уже текущая доля выплат в депозит."}
        if context["cooldown_game_hours"] > 0.001:
            return {
                "status": "cooldown",
                "text": "Вы уже недавно обсуждали эти условия. Вернуться к переговорам можно позже.",
                "cooldown_game_hours": context["cooldown_game_hours"],
            }

        current = int(context["current_pct"])
        target = int(context["target_pct"])
        delta = target - current
        steps = abs(delta) / 5.0
        loyalty = float(context["loyalty"])
        stress = float(context["stress"])

        chance = 0.22 + loyalty * 0.62 - stress * 0.0022
        if delta > 0:
            chance -= 0.075 * steps
            chance -= max(0, target - 30) * 0.005
        else:
            chance += 0.10 * steps
        chance = max(0.05, min(0.95, chance))
        accepted = self.rng.random() < chance

        if accepted and delta > 0:
            loyalty_delta = -(0.012 + 0.010 * steps)
            stress_delta = 0.6 + 0.8 * steps
            reaction = "Сотрудник согласился, но ужесточение условий воспринял без энтузиазма."
        elif accepted:
            loyalty_delta = 0.010 + 0.008 * steps
            stress_delta = -(0.6 + 0.7 * steps)
            reaction = "Сотрудник согласился. Более свободная выплата была воспринята положительно."
        elif delta > 0:
            loyalty_delta = -(0.005 + 0.004 * steps)
            stress_delta = 0.3 + 0.4 * steps
            reaction = "Сотрудник отказался. Сам разговор об увеличении удержаний ему не понравился."
        else:
            loyalty_delta = 0.0
            stress_delta = 0.1
            reaction = "Сотрудник отказался менять привычную схему выплат."

        outcome = "accepted" if accepted else "rejected"
        game_hour = self._current_game_hour(player_id)
        with self.db.connect() as conn:
            if accepted:
                conn.execute(
                    """UPDATE employees
                       SET deposit_contribution_pct=?,
                           loyalty=MIN(1.0, MAX(0.0, loyalty+?)),
                           stress=MIN(100.0, MAX(0.0, stress+?))
                       WHERE id=? AND player_id=? AND active=1""",
                    (target, loyalty_delta, stress_delta, employee_id, player_id),
                )
            else:
                conn.execute(
                    """UPDATE employees
                       SET loyalty=MIN(1.0, MAX(0.0, loyalty+?)),
                           stress=MIN(100.0, MAX(0.0, stress+?))
                       WHERE id=? AND player_id=? AND active=1""",
                    (loyalty_delta, stress_delta, employee_id, player_id),
                )
            conn.execute(
                """INSERT INTO deposit_share_negotiations(
                       player_id, employee_id, from_pct, to_pct, outcome,
                       acceptance_chance, game_hour
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (player_id, employee_id, current, target, outcome, chance, game_hour),
            )

        if accepted:
            text = (
                f"<b>{context['alias']} согласился.</b>\n\n"
                f"Доля в депозит: {current}% → <b>{target}%</b>\n"
                f"Из ставки {context['pay_per_job']:,} ₽ теперь примерно {context['target_deposit']:,} ₽ "
                f"будет уходить в депозит и {context['target_cash']:,} ₽ — в денежную выплату.\n\n"
                f"{reaction}"
            )
        else:
            text = (
                f"<b>{context['alias']} отказался.</b>\n\n"
                f"Предложение: {current}% → {target}% в депозит.\n"
                f"Текущие условия остаются без изменений.\n\n"
                f"{reaction}"
            )
        return {
            "status": outcome,
            "accepted": accepted,
            "chance": chance,
            "from_pct": current,
            "to_pct": target,
            "text": text,
        }

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
