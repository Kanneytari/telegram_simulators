from __future__ import annotations

import json
from datetime import timedelta

from .runtime import NightshiftGameService
from .simulation import iso, parse_dt, utcnow


class FinalGameService(NightshiftGameService):
    """Small final overrides that depend on the player-aware simulation clock."""

    def process_payroll(self, player_id: int, now=None) -> dict | None:
        """Settle accrued wages once per 24 game hours.

        The real interval therefore depends on the player's current time multiplier.
        /speed preserves already elapsed game time, while /tick advances this clock.
        """
        now = now or utcnow()
        speed = max(0.1, float(self.simulation.effective_speed(player_id)))
        with self.db.connect() as conn:
            settings = conn.execute(
                "SELECT * FROM settings WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if not settings:
                return None

            last = parse_dt(settings["last_payroll_at"])
            elapsed_real_hours = max(0.0, (now - last).total_seconds() / 3600.0)
            elapsed_game_hours = elapsed_real_hours * speed
            if elapsed_game_hours < 24.0:
                return None

            employees = conn.execute(
                "SELECT * FROM employees WHERE player_id=? AND wages_accrued>0 ORDER BY id",
                (player_id,),
            ).fetchall()
            gross = sum(int(e["wages_accrued"]) for e in employees)
            if gross <= 0:
                conn.execute(
                    "UPDATE settings SET last_payroll_at=? WHERE player_id=?",
                    (iso(now), player_id),
                )
                return {"gross": 0, "cash": 0, "deposit": 0, "employees": 0, "status": "empty"}

            cash_due = 0
            deposit_due = 0
            settlements = []
            for employee in employees:
                accrued = int(employee["wages_accrued"])
                pct = int(employee["deposit_contribution_pct"] or 0)
                deposit_part = max(0, min(accrued, int(round(accrued * pct / 100.0))))
                cash_part = accrued - deposit_part
                cash_due += cash_part
                deposit_due += deposit_part
                settlements.append((employee, accrued, cash_part, deposit_part))

            shop = conn.execute(
                "SELECT balance FROM shops WHERE player_id=?",
                (player_id,),
            ).fetchone()
            balance = int(shop["balance"])
            if balance < cash_due:
                existing = conn.execute(
                    """SELECT 1 FROM inbox
                       WHERE player_id=? AND status='open' AND kind='payroll_shortfall'""",
                    (player_id,),
                ).fetchone()
                if not existing:
                    shortage = cash_due - balance
                    conn.execute(
                        """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json)
                           VALUES (?, 'payroll_shortfall', 'urgent', 'Не хватает на выплаты', ?, '{}')""",
                        (
                            player_id,
                            f"К выплате: {cash_due:,} ₽\n"
                            f"На счету: {balance:,} ₽\n\n"
                            f"🔴 Не хватает {shortage:,} ₽. Выплата сотрудникам задержана.",
                        ),
                    )
                return {
                    "gross": gross,
                    "cash": cash_due,
                    "deposit": deposit_due,
                    "employees": len(employees),
                    "status": "shortfall",
                }

            conn.execute(
                "UPDATE shops SET balance=balance-? WHERE player_id=?",
                (cash_due, player_id),
            )
            for employee, accrued, cash_part, deposit_part in settlements:
                conn.execute(
                    """UPDATE employees
                       SET wages_accrued=0,
                           total_wages_paid=total_wages_paid+?,
                           deposit=deposit+?,
                           deposit_from_wages=deposit_from_wages+?
                       WHERE id=?""",
                    (accrued, deposit_part, deposit_part, employee["id"]),
                )
                conn.execute(
                    """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                       VALUES (?, ?, 'salary', 'employee', ?, ?)""",
                    (
                        player_id,
                        -cash_part,
                        employee["id"],
                        f"Суточная выплата {employee['alias']}: {cash_part:,} ₽; в депозит {deposit_part:,} ₽",
                    ),
                )

            conn.execute(
                """INSERT INTO payroll_runs(player_id, gross_wages, cash_paid, deposit_added, employee_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (player_id, gross, cash_due, deposit_due, len(employees)),
            )
            conn.execute(
                "UPDATE settings SET last_payroll_at=? WHERE player_id=?",
                (iso(now), player_id),
            )
            conn.execute(
                "UPDATE inbox SET status='closed' WHERE player_id=? AND status='open' AND kind='payroll_shortfall'",
                (player_id,),
            )
            conn.execute(
                """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
                   VALUES (?, 'payroll_report', 'normal', 'Суточные выплаты', ?, '{}', ?)""",
                (
                    player_id,
                    f"Начислено: {gross:,} ₽\n"
                    f"Выплачено: {cash_due:,} ₽\n"
                    f"В депозит: {deposit_due:,} ₽\n\n"
                    f"Сотрудников в выплате: {len(employees)}",
                    iso(now + timedelta(hours=12 / speed)),
                ),
            )
            return {
                "gross": gross,
                "cash": cash_due,
                "deposit": deposit_due,
                "employees": len(employees),
                "status": "paid",
            }

    def payroll_summary(self, player_id: int) -> str:
        now = utcnow()
        speed = max(0.1, float(self.simulation.effective_speed(player_id)))
        with self.db.connect() as conn:
            settings = conn.execute(
                "SELECT * FROM settings WHERE player_id=?",
                (player_id,),
            ).fetchone()
            rows = conn.execute(
                """SELECT alias, role, pay_per_job, deposit_contribution_pct, deposit,
                          wages_accrued, total_wages_paid, deposit_from_wages, active
                   FROM employees
                   WHERE player_id=?
                   ORDER BY active DESC, wages_accrued DESC, alias""",
                (player_id,),
            ).fetchall()
            seven = conn.execute(
                """SELECT COALESCE(SUM(gross_wages),0) gross,
                          COALESCE(SUM(cash_paid),0) cash,
                          COALESCE(SUM(deposit_added),0) deposit
                   FROM payroll_runs
                   WHERE player_id=? AND created_at>=datetime('now','-7 day')""",
                (player_id,),
            ).fetchone()

        accrued = sum(int(row["wages_accrued"]) for row in rows)
        last = parse_dt(settings["last_payroll_at"])
        elapsed_game = max(0.0, (now - last).total_seconds() / 3600.0) * speed
        remaining_game = max(0.0, 24.0 - elapsed_game)
        remaining_real_minutes = remaining_game / speed * 60.0
        if remaining_real_minutes >= 120:
            real_eta = f"~{remaining_real_minutes / 60.0:.1f} ч"
        else:
            real_eta = f"~{remaining_real_minutes:.0f} мин"

        lines = []
        for row in rows[:12]:
            status = "" if row["active"] else " · ушёл"
            lines.append(
                f"{row['alias']}{status}\n"
                f"Ставка {row['pay_per_job']:,} ₽ · депозит {row['deposit_contribution_pct']}%\n"
                f"К выплате {row['wages_accrued']:,} ₽ · депозит {row['deposit']:,} ₽"
            )

        return (
            "<b>💸 Выплаты сотрудникам</b>\n\n"
            "<b>Следующая выплата</b>\n"
            f"Через ~{remaining_game:.1f} игровых ч · {real_eta}\n"
            f"Скорость: x{speed:g}\n"
            f"Начислено сейчас: <b>{accrued:,} ₽</b>\n\n"
            "<b>За 7 реальных дней</b>\n"
            f"Начислено: {seven['gross']:,} ₽\n"
            f"Выплачено деньгами: {seven['cash']:,} ₽\n"
            f"Переведено в депозиты: {seven['deposit']:,} ₽\n\n"
            "<b>По сотрудникам</b>\n"
            + ("\n\n".join(lines) if lines else "Нет сотрудников.")
        )

    def handle_inbox_action(self, player_id: int, item_id: int, action: str) -> str:
        with self.db.connect() as conn:
            item = conn.execute(
                "SELECT * FROM inbox WHERE id=? AND player_id=? AND status='open'",
                (item_id, player_id),
            ).fetchone()
            if not item:
                return "Сообщение уже неактуально."

            if item["kind"] == "leave_request" and action == "approve":
                payload = json.loads(item["payload_json"] or "{}")
                employee_id = int(payload["employee_id"])
                speed = max(0.1, float(self.simulation.effective_speed(player_id)))
                until = utcnow() + timedelta(hours=6 / speed)
                conn.execute(
                    """UPDATE employees
                       SET available=0,
                           unavailable_until=?,
                           loyalty=MIN(1.0, loyalty+0.05),
                           stress=MAX(0, stress-12)
                       WHERE id=? AND player_id=?""",
                    (iso(until), employee_id, player_id),
                )
                conn.execute("UPDATE inbox SET status='closed' WHERE id=?", (item_id,))
                return "Пауза согласована. Сотрудник недоступен 6 игровых часов."

        return super().handle_inbox_action(player_id, item_id, action)

    def dispute_payment_context(self, player_id: int, dispute_id: int, decision: str) -> dict | None:
        if decision not in {"refund", "partial"}:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.id dispute_id, d.status, o.id order_id, o.revenue,
                          e.id employee_id, e.alias employee_alias, e.deposit,
                          s.balance, s.reserve_target
                   FROM disputes d
                   JOIN orders o ON o.id=d.order_id
                   JOIN employees e ON e.id=o.employee_id
                   JOIN shops s ON s.player_id=d.player_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
        if not row or row["status"] != "open":
            return None
        amount = int(row["revenue"]) if decision == "refund" else int(row["revenue"] * 0.5)
        return {
            "dispute_id": dispute_id,
            "order_id": int(row["order_id"]),
            "amount": amount,
            "employee_id": int(row["employee_id"]),
            "employee_alias": row["employee_alias"],
            "employee_deposit": int(row["deposit"]),
            "shop_balance": int(row["balance"]),
            "shop_reserve": int(row["reserve_target"]),
        }

    def resolve_dispute_with_source(self, player_id: int, dispute_id: int, decision: str, source: str) -> str:
        if decision not in {"refund", "partial", "reject"}:
            raise ValueError("Unsupported dispute decision")
        if source not in {"shop", "employee", "none"}:
            raise ValueError("Unsupported compensation source")

        if decision == "reject":
            result = super().resolve_dispute(player_id, dispute_id, "reject")
            with self.db.connect() as conn:
                conn.execute(
                    """UPDATE disputes
                       SET refund_amount=0, refund_source='none', refund_employee_id=NULL
                       WHERE id=? AND player_id=?""",
                    (dispute_id, player_id),
                )
            return result

        context = self.dispute_payment_context(player_id, dispute_id, decision)
        if not context:
            return "Этот диспут уже закрыт."
        refund = int(context["amount"])

        if source == "shop":
            if int(context["shop_balance"]) < refund:
                return (
                    "На счёте магазина недостаточно денег.\n\n"
                    f"Нужно: {refund:,} ₽\n"
                    f"Доступно: {context['shop_balance']:,} ₽"
                )
            result = super().resolve_dispute(player_id, dispute_id, decision)
            with self.db.connect() as conn:
                conn.execute(
                    """UPDATE disputes
                       SET refund_amount=?, refund_source='shop', refund_employee_id=NULL
                       WHERE id=? AND player_id=?""",
                    (refund, dispute_id, player_id),
                )
            return f"{result}\nИсточник: счёт магазина."

        if int(context["employee_deposit"]) < refund:
            return (
                "Недостаточно средств в депозите сотрудника.\n\n"
                f"Нужно: {refund:,} ₽\n"
                f"Доступно: {context['employee_deposit']:,} ₽"
            )

        now = utcnow()
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT d.*, o.*, c.id cid, c.review_tendency, c.loyalty,
                          e.id eid, e.alias employee_alias, e.deposit
                   FROM disputes d
                   JOIN orders o ON o.id=d.order_id
                   JOIN clients c ON c.id=o.client_id
                   JOIN employees e ON e.id=o.employee_id
                   WHERE d.id=? AND d.player_id=?""",
                (dispute_id, player_id),
            ).fetchone()
            if not row or row["status"] != "open":
                return "Этот диспут уже закрыт."
            if int(row["deposit"]) < refund:
                return "Депозит сотрудника уже недостаточен для этой компенсации."

            conn.execute(
                """UPDATE employees
                   SET deposit=deposit-?, losses=losses+?, stress=MIN(100, stress+2.5)
                   WHERE id=?""",
                (refund, refund, row["eid"]),
            )
            conn.execute(
                "UPDATE shops SET balance=balance-? WHERE player_id=?",
                (refund, player_id),
            )
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, ?, 'refund_employee_deposit', 'employee', ?, ?)""",
                (
                    player_id,
                    -refund,
                    row["eid"],
                    f"Компенсация по диспуту #{dispute_id} из депозита {row['employee_alias']}",
                ),
            )

            good = self._decision_quality(row["true_cause"], decision)
            rating_delta = 0.0
            if good > 0:
                rating_delta = self.rng.uniform(0.001, 0.008) * float(row["review_tendency"])
                conn.execute("UPDATE clients SET loyalty=MIN(1.0, loyalty+0.03) WHERE id=?", (row["cid"],))
                conn.execute("UPDATE clients SET disputes_won=disputes_won+1 WHERE id=?", (row["cid"],))
            elif good < 0:
                rating_delta = -self.rng.uniform(0.015, 0.055) * float(row["review_tendency"])
                conn.execute("UPDATE clients SET loyalty=MAX(0.0, loyalty-0.12) WHERE id=?", (row["cid"],))

            conn.execute(
                "UPDATE shops SET rating=MAX(1.0, MIN(5.0, rating+?)) WHERE player_id=?",
                (rating_delta, player_id),
            )
            conn.execute(
                """UPDATE disputes
                   SET status='resolved', decision=?, refund_amount=?, refund_source='employee',
                       refund_employee_id=?, resolved_at=?
                   WHERE id=?""",
                (decision, refund, row["eid"], iso(now), dispute_id),
            )
            conn.execute("UPDATE orders SET status='completed' WHERE id=?", (row["order_id"],))
            conn.execute(
                """UPDATE inbox SET status='closed'
                   WHERE player_id=? AND kind='dispute'
                     AND json_extract(payload_json, '$.dispute_id')=?""",
                (player_id, dispute_id),
            )

        quality_text = (
            "Решение выглядит удачным."
            if good > 0
            else "Решение может иметь неприятные последствия."
            if good < 0
            else "Ситуация осталась неоднозначной."
        )
        return (
            f"Диспут закрыт. Компенсация: {refund:,} ₽.\n"
            f"Источник: депозит {context['employee_alias']}.\n\n"
            f"{quality_text}"
        )
