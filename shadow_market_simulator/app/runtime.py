from __future__ import annotations

from .db import Database
from .game import GameService, ROLE_NAMES
from .simulation import SimulationEngine, TickResult, iso, parse_dt, utcnow


class PlayerSimulationEngine(SimulationEngine):
    """Simulation engine with a per-player time multiplier and deposit accumulation."""

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
            # Recruitment is handled by RecruitmentService; old automatic candidates are disabled.
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
        contribution = int(round(employee_cost * contribution_pct / 100.0))
        contribution = max(0, min(employee_cost, contribution))
        cash_pay = employee_cost - contribution
        quality = float(batch["quality"])

        conn.execute(
            "UPDATE batches SET remaining=remaining-? WHERE id=?",
            (qty, batch["id"]),
        )
        conn.execute(
            """UPDATE employees
               SET jobs_done=jobs_done+1,
                   deposit=deposit+?,
                   stress=MIN(100, stress+?),
                   last_contact_at=?
               WHERE id=?""",
            (contribution, self.rng.uniform(0.05, 0.35), iso(now), employee["id"]),
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
                contribution,
                quality,
            ),
        )
        order_id = cur.lastrowid
        profit = revenue - cost - employee_cost
        cash_change = revenue - cash_pay
        conn.execute(
            """UPDATE shops
               SET balance=balance+?,
                   total_revenue=total_revenue+?,
                   total_profit=total_profit+?,
                   total_orders=total_orders+1
               WHERE player_id=?""",
            (cash_change, revenue, profit, player_id),
        )
        note = f"Заказ #{order_id}"
        if contribution:
            note += f" · в депозит сотрудника {contribution:,} ₽"
        conn.execute(
            """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
               VALUES (?, ?, 'sale', 'order', ?, ?)""",
            (player_id, cash_change, order_id, note),
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
    """UI-facing game service with the extended employment terms."""

    def employee_details(self, player_id: int, employee_id: int) -> str | None:
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=?",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                return None

        dispute_rate = (
            employee["disputes"] / employee["jobs_done"] * 100.0
            if employee["jobs_done"]
            else 0.0
        )
        status = "работает" if employee["available"] else "временно недоступен"
        contribution = int(employee["deposit_contribution_pct"] or 0)
        per_order = int(round(employee["pay_per_job"] * contribution / 100.0))
        take_home = employee["pay_per_job"] - per_order

        return (
            f"<b>👤 {employee['alias']}</b> · {ROLE_NAMES.get(employee['role'], employee['role'])}\n\n"
            f"<b>Условия</b>\n"
            f"Статус: {status}\n"
            f"Ставка: <b>{employee['pay_per_job']:,} ₽</b> / заказ\n"
            f"На руки: {take_home:,} ₽\n"
            f"В депозит: {contribution}% · ~{per_order:,} ₽ / заказ\n"
            f"Текущий депозит: <b>{employee['deposit']:,} ₽</b>\n"
            f"Автомобиль: {'есть' if employee['has_car'] else 'нет'}\n\n"
            f"<b>Статистика</b>\n"
            f"Заказов: {employee['jobs_done']}\n"
            f"Диспутов: {employee['disputes']} ({dispute_rate:.1f}%)\n"
            f"Прямые потери: {employee['losses']:,} ₽\n"
            f"В команде с: {str(employee['joined_at'])[:10]}"
        )

    def hire_candidate(self, player_id: int, candidate_id: int) -> str:
        with self.db.connect() as conn:
            candidate = conn.execute(
                """SELECT * FROM candidates
                   WHERE id=? AND player_id=? AND status='open'""",
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
                (
                    player_id,
                    deposit,
                    cur.lastrowid,
                    f"Стартовый депозит сотрудника {candidate['alias']}",
                ),
            )
            conn.execute(
                "UPDATE candidates SET status='hired' WHERE id=?",
                (candidate_id,),
            )

        return (
            f"<b>{candidate['alias']} принят.</b>\n\n"
            f"Ставка: {pay:,} ₽ / заказ\n"
            f"В депозит: {contribution_pct}% заработка\n"
            f"Стартовый депозит: {deposit:,} ₽"
        )
