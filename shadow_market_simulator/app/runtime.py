from __future__ import annotations

import json
from datetime import timedelta

from .db import Database
from .game import GameService, ROLE_NAMES
from .simulation import SimulationEngine, TickResult, iso, parse_dt, utcnow


ROLE_MARKET_PAY = {
    "courier": 1500,
    "warehouse": 5000,
    "operator": 1800,
}

STAFF_INBOX_KINDS = {
    "raise_request",
    "leave_request",
    "advance_request",
    "employee_exit",
    "payroll_shortfall",
    "payroll_report",
}


class PlayerSimulationEngine(SimulationEngine):
    """Simulation engine with a per-player time multiplier and accrued payroll."""

    def player_multiplier(self, player_id: int) -> float:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT time_multiplier FROM settings WHERE player_id=?",
                (player_id,),
            ).fetchone()
        return max(0.1, float(row[0])) if row else 1.0

    def effective_speed(self, player_id: int) -> float:
        return max(0.1, float(self.speed) * self.player_multiplier(player_id))

    def advance(self, player_id: int, now=None) -> TickResult:
        now = now or utcnow()
        with self.db.connect() as conn:
            shop = conn.execute(
                "SELECT * FROM shops WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if not shop:
                return TickResult()

            last = parse_dt(shop["last_simulated_at"])
            real_hours = max(0.0, (now - last).total_seconds() / 3600.0)
            sim_hours = min(real_hours * self.effective_speed(player_id), 72.0)
            if sim_hours < 0.015:
                return TickResult()

            orders, disputes = self._simulate_sales(conn, player_id, shop, sim_hours, now)
            messages = self._simulate_management_events(conn, player_id, sim_hours, now)
            self._reactivate_employees(conn, player_id, now)
            self._expire_items(conn, player_id, now)
            self._maybe_refresh_offer(conn, player_id, now)
            conn.execute(
                "UPDATE shops SET last_simulated_at=?, last_seen_at=? WHERE player_id=?",
                (iso(now), iso(now), player_id),
            )
            return TickResult(orders, disputes, messages)

    def _maybe_refresh_candidate(self, conn, player_id: int, now) -> None:
        return None

    def _create_order(self, conn, player_id: int, listing, employee, now) -> bool:
        client = conn.execute(
            "SELECT * FROM clients WHERE player_id=? ORDER BY RANDOM() LIMIT 1",
            (player_id,),
        ).fetchone()
        batch = conn.execute(
            """SELECT * FROM batches
               WHERE player_id=? AND product_id=? AND status='warehouse' AND remaining>=?
               ORDER BY acquired_at LIMIT 1""",
            (player_id, listing["product_id"], listing["pack_size"]),
        ).fetchone()
        if not client or not batch:
            return False

        qty = int(listing["pack_size"])
        revenue = int(listing["price"])
        cost = int(batch["unit_cost"] * qty)
        employee_cost = int(employee["pay_per_job"])
        contribution_pct = int(employee["deposit_contribution_pct"] or 0)
        contribution_preview = max(0, min(employee_cost, int(round(employee_cost * contribution_pct / 100.0))))
        quality = float(batch["quality"])

        conn.execute(
            "UPDATE batches SET remaining=remaining-? WHERE id=?",
            (qty, batch["id"]),
        )
        conn.execute(
            """UPDATE employees
               SET jobs_done=jobs_done+1,
                   wages_accrued=wages_accrued+?,
                   stress=MIN(100, stress+?),
                   last_contact_at=?
               WHERE id=?""",
            (employee_cost, self.rng.uniform(0.05, 0.35), iso(now), employee["id"]),
        )
        conn.execute(
            """UPDATE clients
               SET shop_orders=shop_orders+1,
                   marketplace_orders=marketplace_orders+1,
                   total_spend=total_spend+?
               WHERE id=?""",
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
                employee["id"],
                batch["id"],
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
            """UPDATE shops
               SET balance=balance+?,
                   total_revenue=total_revenue+?,
                   total_profit=total_profit+?,
                   total_orders=total_orders+1
               WHERE player_id=?""",
            (revenue, revenue, profit, player_id),
        )
        conn.execute(
            """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
               VALUES (?, ?, 'sale', 'order', ?, ?)""",
            (
                player_id,
                revenue,
                order_id,
                f"Заказ #{order_id} · зарплата {employee_cost:,} ₽ начислена к суточной выплате",
            ),
        )

        dispute_probability = self._dispute_probability(
            client,
            employee,
            quality,
            float(listing["complaint_modifier"]),
        )
        if self.rng.random() < dispute_probability:
            self._open_dispute(
                conn,
                player_id,
                order_id,
                client,
                employee,
                quality,
                revenue,
                now,
            )
            return True
        return False


class NightshiftGameService(GameService):
    """UI-facing game service with employment terms, negotiation and payroll."""

    def process_payroll(self, player_id: int, now=None) -> dict | None:
        now = now or utcnow()
        with self.db.connect() as conn:
            settings = conn.execute(
                "SELECT * FROM settings WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if not settings:
                return None
            last = parse_dt(settings["last_payroll_at"])
            if (now - last).total_seconds() < 24 * 3600:
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
                    iso(now + timedelta(hours=12)),
                ),
            )
            return {
                "gross": gross,
                "cash": cash_due,
                "deposit": deposit_due,
                "employees": len(employees),
                "status": "paid",
            }

    def process_payroll_all(self) -> None:
        with self.db.connect() as conn:
            player_ids = [row[0] for row in conn.execute("SELECT player_id FROM shops").fetchall()]
        for player_id in player_ids:
            self.process_payroll(player_id)

    def payroll_summary(self, player_id: int) -> str:
        now = utcnow()
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
        remaining = max(0.0, 24.0 - (now - last).total_seconds() / 3600.0)
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
            f"Через ~{remaining:.1f} реального ч\n"
            f"Начислено сейчас: <b>{accrued:,} ₽</b>\n\n"
            "<b>За 7 дней</b>\n"
            f"Начислено: {seven['gross']:,} ₽\n"
            f"Выплачено деньгами: {seven['cash']:,} ₽\n"
            f"Переведено в депозиты: {seven['deposit']:,} ₽\n\n"
            "<b>По сотрудникам</b>\n"
            + ("\n\n".join(lines) if lines else "Нет сотрудников.")
        )

    def employee_details(self, player_id: int, employee_id: int) -> str | None:
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=?",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                return None

        dispute_rate = employee["disputes"] / employee["jobs_done"] * 100.0 if employee["jobs_done"] else 0.0
        status = "работает" if employee["available"] else "временно недоступен"
        contribution = int(employee["deposit_contribution_pct"] or 0)
        per_order_deposit = int(round(employee["pay_per_job"] * contribution / 100.0))
        take_home = employee["pay_per_job"] - per_order_deposit
        market = ROLE_MARKET_PAY.get(employee["role"], 1500)
        delta = (employee["pay_per_job"] / market - 1.0) * 100.0 if market else 0.0

        return (
            f"<b>👤 {employee['alias']}</b> · {ROLE_NAMES.get(employee['role'], employee['role'])}\n\n"
            f"<b>Условия</b>\n"
            f"Статус: {status}\n"
            f"Ставка: <b>{employee['pay_per_job']:,} ₽</b> / заказ ({delta:+.0f}% к рынку)\n"
            f"На руки после выплаты: ~{take_home:,} ₽ / заказ\n"
            f"В депозит: {contribution}% · ~{per_order_deposit:,} ₽ / заказ\n"
            f"Начислено к выплате: <b>{employee['wages_accrued']:,} ₽</b>\n"
            f"Текущий депозит: <b>{employee['deposit']:,} ₽</b>\n"
            f"Автомобиль: {'есть' if employee['has_car'] else 'нет'}\n\n"
            f"<b>Статистика</b>\n"
            f"Заказов: {employee['jobs_done']}\n"
            f"Диспутов: {employee['disputes']} ({dispute_rate:.1f}%)\n"
            f"Прямые потери: {employee['losses']:,} ₽\n"
            f"Всего заработано: {employee['total_wages_paid'] + employee['wages_accrued']:,} ₽\n"
            f"Из заработка в депозит: {employee['deposit_from_wages']:,} ₽\n"
            f"В команде с: {str(employee['joined_at'])[:10]}"
        )

    def hire_candidate(self, player_id: int, candidate_id: int) -> str:
        with self.db.connect() as conn:
            candidate = conn.execute(
                "SELECT * FROM candidates WHERE id=? AND player_id=? AND status='open'",
                (candidate_id, player_id),
            ).fetchone()
            if not candidate:
                return "Кандидат уже недоступен."

            pay = int(candidate["offered_pay"] or candidate["desired_pay"])
            contribution_pct = int(candidate["deposit_contribution_pct"] or 10)
            deposit = int(candidate["deposit"])
            cur = conn.execute(
                """INSERT INTO employees(
                       player_id, alias, role, pay_per_job, deposit,
                       deposit_contribution_pct, has_car,
                       reliability, attention, honesty, loyalty
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    player_id,
                    candidate["alias"],
                    candidate["role"],
                    pay,
                    deposit,
                    contribution_pct,
                    candidate["has_car"],
                    candidate["reliability"],
                    candidate["attention"],
                    candidate["honesty"],
                    candidate["loyalty"],
                ),
            )
            conn.execute(
                "UPDATE shops SET balance=balance+? WHERE player_id=?",
                (deposit, player_id),
            )
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
                   VALUES (?, ?, 'deposit_in', 'employee', ?, ?)""",
                (player_id, deposit, cur.lastrowid, f"Стартовый депозит сотрудника {candidate['alias']}"),
            )
            conn.execute("UPDATE candidates SET status='hired' WHERE id=?", (candidate_id,))

        return (
            f"<b>{candidate['alias']} принят.</b>\n\n"
            f"Ставка: {pay:,} ₽ / заказ\n"
            f"В депозит: {contribution_pct}% заработка\n"
            f"Стартовый депозит: {deposit:,} ₽"
        )

    def start_raise_negotiation(self, player_id: int, item_id: int) -> dict | None:
        with self.db.connect() as conn:
            item = conn.execute(
                "SELECT * FROM inbox WHERE id=? AND player_id=? AND status='open' AND kind='raise_request'",
                (item_id, player_id),
            ).fetchone()
            if not item:
                return None
            payload = json.loads(item["payload_json"] or "{}")
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=?",
                (payload.get("employee_id"), player_id),
            ).fetchone()
            if not employee:
                return None
            requested = int(payload.get("requested_pay") or round(employee["pay_per_job"] * 1.15 / 50) * 50)
            payload.setdefault("requested_pay", requested)
            payload.setdefault("offer_pay", int(employee["pay_per_job"]))
            payload.setdefault("round", 0)
            payload.setdefault("floor_pay", max(int(employee["pay_per_job"]), int(requested * self.rng.uniform(0.88, 0.98))))
            conn.execute(
                "UPDATE inbox SET payload_json=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), item_id),
            )
            return {"item": item, "employee": employee, "payload": payload}

    def adjust_raise_offer(self, player_id: int, item_id: int, delta: int) -> dict | None:
        state = self.start_raise_negotiation(player_id, item_id)
        if not state:
            return None
        payload = state["payload"]
        employee = state["employee"]
        offer = int(payload.get("offer_pay", employee["pay_per_job"])) + delta
        offer = max(int(employee["pay_per_job"]), min(10000, int(round(offer / 50) * 50)))
        payload["offer_pay"] = offer
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE inbox SET payload_json=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), item_id),
            )
        state["payload"] = payload
        return state

    def submit_raise_offer(self, player_id: int, item_id: int) -> str:
        state = self.start_raise_negotiation(player_id, item_id)
        if not state:
            return "Запрос уже неактуален."
        employee = state["employee"]
        payload = state["payload"]
        offer = int(payload["offer_pay"])
        requested = int(payload["requested_pay"])
        floor = int(payload["floor_pay"])
        round_no = int(payload.get("round", 0))
        market = ROLE_MARKET_PAY.get(employee["role"], 1500)

        acceptance_score = offer / max(floor, 1)
        acceptance_score += (float(employee["loyalty"]) - 0.5) * 0.12
        acceptance_score += min(0.08, max(-0.08, (offer - market) / max(market, 1) * 0.12))
        accepted = offer >= requested or acceptance_score >= self.rng.uniform(0.94, 1.04)

        with self.db.connect() as conn:
            if accepted:
                conn.execute(
                    "UPDATE employees SET pay_per_job=?, loyalty=MIN(1.0, loyalty+0.04) WHERE id=?",
                    (offer, employee["id"]),
                )
                conn.execute("UPDATE inbox SET status='closed' WHERE id=?", (item_id,))
                return f"{employee['alias']} согласился на {offer:,} ₽ за заказ."

            if round_no >= 2:
                payload["offer_pay"] = offer
                payload["round"] = round_no + 1
                conn.execute(
                    "UPDATE employees SET loyalty=MAX(0.0, loyalty-0.04), stress=MIN(100, stress+2) WHERE id=?",
                    (employee["id"],),
                )
                conn.execute(
                    "UPDATE inbox SET payload_json=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), item_id),
                )
                return f"{employee['alias']} не согласился. Он по-прежнему хочет около {requested:,} ₽."

            counter = max(offer + 50, int(round((offer + requested) / 2 / 50) * 50))
            payload["requested_pay"] = counter
            payload["round"] = round_no + 1
            payload["offer_pay"] = offer
            conn.execute(
                "UPDATE inbox SET payload_json=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), item_id),
            )
            return f"{employee['alias']} не принял предложение и снизил запрос до {counter:,} ₽."

    def accept_raise_request(self, player_id: int, item_id: int) -> str:
        state = self.start_raise_negotiation(player_id, item_id)
        if not state:
            return "Запрос уже неактуален."
        employee = state["employee"]
        requested = int(state["payload"]["requested_pay"])
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE employees SET pay_per_job=?, loyalty=MIN(1.0, loyalty+0.07) WHERE id=?",
                (requested, employee["id"]),
            )
            conn.execute("UPDATE inbox SET status='closed' WHERE id=?", (item_id,))
        return f"Новая ставка {employee['alias']}: {requested:,} ₽ за заказ."
