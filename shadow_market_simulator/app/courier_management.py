from __future__ import annotations

import json
from datetime import timedelta

from .compensation import _deposit_part, _policy_conn
from .courier_core import CourierCoreGameService, CourierCoreSimulationEngine
from .courier_model import TRAIT_SENSITIVE
from .simulation import clamp, iso, parse_dt, utcnow



BONUS_COST = 5_000
BONUS_COOLDOWN_HOURS = 24.0
REST_OPTIONS = {
    12: {"cost": 3_000, "stress": 28.0, "loyalty": 0.035},
    24: {"cost": 5_500, "stress": 48.0, "loyalty": 0.060},
}
REST_COOLDOWN_HOURS = 36.0
DEPOSIT_PCTS = (20, 50, 80)
DEPOSIT_TARGETS = (60_000, 100_000, 150_000)

TRANSPORT = {
    0: ("пешком", 0, 0.00),
    1: ("самокат", 25_000, 0.08),
    2: ("автомобиль", 75_000, 0.16),
}
PHONE = {
    0: ("старый", 0, 0.00),
    1: ("нормальный", 12_000, 0.04),
    2: ("хороший", 35_000, 0.085),
}


class CourierManagementSimulationEngine(CourierCoreSimulationEngine):
    """Courier core plus sparse, consequential management and development effects."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            self._ensure_courier_management_conn(conn)

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        with self.db.connect() as conn:
            self._ensure_courier_management_conn(conn, player_id)
        return created

    def _ensure_courier_management_conn(self, conn, player_id: int | None = None) -> None:
        params = () if player_id is None else (player_id,)
        where = "" if player_id is None else " AND e.player_id=?"
        rows = conn.execute(
            f"""SELECT e.id, e.player_id, e.deposit, e.has_car
                FROM employees e
                JOIN courier_profiles cp ON cp.employee_id=e.id
                LEFT JOIN courier_management cm ON cm.employee_id=e.id
                WHERE e.role='courier' AND cm.employee_id IS NULL {where}""",
            params,
        ).fetchall()
        for row in rows:
            target = max(60_000, int(row["deposit"]))
            conn.execute(
                """INSERT INTO courier_management(
                       employee_id, player_id, deposit_target, deposit_contribution_pct,
                       transport_level, phone_level
                   ) VALUES (?, ?, ?, 50, ?, 0)""",
                (
                    int(row["id"]),
                    int(row["player_id"]),
                    target,
                    2 if int(row["has_car"]) else 0,
                ),
            )

    def _management_conn(self, conn, employee_id: int):
        return conn.execute(
            "SELECT * FROM courier_management WHERE employee_id=?",
            (employee_id,),
        ).fetchone()

    def _management(self, employee_id: int):
        with self.db.connect() as conn:
            return self._management_conn(conn, employee_id)

    def _employee_deposit_contribution(
        self, conn, player_id: int, employee_id: int, employee_cost: int, default_pct: int
    ) -> int:
        management = self._management_conn(conn, employee_id)
        employee = conn.execute(
            "SELECT deposit, deposit_accrued FROM employees WHERE id=?",
            (employee_id,),
        ).fetchone()
        if not management or not employee:
            return _deposit_part(employee_cost, default_pct)

        deposit = int(employee["deposit"])
        pending = int(employee["deposit_accrued"])
        target = int(management["deposit_target"])
        if deposit + pending >= target:
            return _deposit_part(employee_cost, default_pct)

        pct = int(management["deposit_contribution_pct"])
        desired = _deposit_part(employee_cost, pct)
        return min(desired, max(0, target - deposit - pending))

    def _effective_pace(self, profile, stress: float) -> float:
        value = super()._effective_pace(profile, stress)
        management = self._management(int(profile["employee_id"]))
        if not management:
            return value
        bonus = TRANSPORT[int(management["transport_level"])][2]
        return clamp(value + bonus, 0.34, 1.20)

    def _effective_precision(self, profile, stress: float) -> float:
        value = super()._effective_precision(profile, stress)
        management = self._management(int(profile["employee_id"]))
        if not management:
            return value
        bonus = PHONE[int(management["phone_level"])][2]
        return clamp(value + bonus, 0.32, 0.995)




class CourierManagementGameService(CourierCoreGameService):
    """Rare management decisions: care, deposit strategy and equipment investment."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            pass
            self.simulation._ensure_courier_management_conn(conn)

    def hire_candidate(self, player_id: int, candidate_id: int) -> str:
        with self.db.connect() as conn:
            candidate = conn.execute(
                "SELECT * FROM candidates WHERE id=? AND player_id=? AND status='open'",
                (candidate_id, player_id),
            ).fetchone()
            equipment = conn.execute(
                "SELECT * FROM courier_candidate_equipment WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        result = super().hire_candidate(player_id, candidate_id)
        if not candidate or candidate["role"] != "courier":
            return result

        with self.db.connect() as conn:
            employee = conn.execute(
                """SELECT * FROM employees
                   WHERE player_id=? AND alias=? AND role='courier'
                   ORDER BY id DESC LIMIT 1""",
                (player_id, candidate["alias"]),
            ).fetchone()
            if not employee:
                return result
            self.simulation._ensure_courier_management_conn(conn, player_id)
            conn.execute(
                """UPDATE courier_management
                   SET deposit_target=?, transport_level=?, phone_level=?, updated_at=CURRENT_TIMESTAMP
                   WHERE employee_id=?""",
                (
                    max(60_000, int(employee["deposit"])),
                    2 if int(candidate["has_car"]) else 0,
                    int(equipment["phone_level"]) if equipment else 0,
                    int(employee["id"]),
                ),
            )
        return result

    @staticmethod
    def _free_cash_conn(conn, player_id: int) -> int:
        shop = conn.execute(
            "SELECT balance, reserve_target FROM shops WHERE player_id=?",
            (player_id,),
        ).fetchone()
        if not shop:
            return 0
        deposits = int(
            conn.execute(
                "SELECT COALESCE(SUM(deposit),0) FROM employees WHERE player_id=? AND active=1",
                (player_id,),
            ).fetchone()[0]
        )
        wages = int(
            conn.execute(
                "SELECT COALESCE(SUM(wages_accrued),0) FROM employees WHERE player_id=? AND active=1",
                (player_id,),
            ).fetchone()[0]
        )
        return int(shop["balance"]) - int(shop["reserve_target"]) - deposits - wages

    def _game_hours_since(self, player_id: int, value: str | None) -> float:
        if not value:
            return 1_000_000.0
        return max(
            0.0,
            (utcnow() - parse_dt(value)).total_seconds()
            / 3600.0
            * self.simulation.effective_speed(player_id),
        )

    @staticmethod
    def _relationship_delta(current: float, base: float, trait: str) -> float:
        value = float(base)
        if value > 0 and trait == TRAIT_SENSITIVE:
            value *= 1.20
        if value > 0 and current >= 0.82:
            value *= 0.50
        return value

    @staticmethod
    def _management_event_conn(
        conn,
        player_id: int,
        employee_id: int,
        kind: str,
        *,
        amount: int = 0,
        loyalty_delta: float = 0.0,
        stress_delta: float = 0.0,
        details: dict | None = None,
    ) -> None:
        conn.execute(
            """INSERT INTO courier_management_events(
                   player_id, employee_id, kind, amount, loyalty_delta, stress_delta, details_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                player_id,
                employee_id,
                kind,
                int(amount),
                float(loyalty_delta),
                float(stress_delta),
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )

    @staticmethod
    def _charge_conn(conn, player_id: int, employee_id: int, amount: int, note: str) -> None:
        conn.execute(
            "UPDATE shops SET balance=balance-?, total_profit=total_profit-? WHERE player_id=?",
            (amount, amount, player_id),
        )
        conn.execute(
            """INSERT INTO ledger(player_id, amount, kind, reference_type, reference_id, note)
               VALUES (?, ?, 'staff_investment', 'employee', ?, ?)""",
            (player_id, -amount, employee_id, note),
        )

    def _managed_employee_conn(self, conn, player_id: int, employee_id: int):
        return conn.execute(
            """SELECT e.*, cp.trait, cm.deposit_target, cm.deposit_contribution_pct,
                      cm.transport_level, cm.phone_level, cm.invested_total,
                      cm.bonuses_given, cm.rests_taken, cm.last_bonus_at, cm.last_rest_at
               FROM employees e
               JOIN courier_profiles cp ON cp.employee_id=e.id
               JOIN courier_management cm ON cm.employee_id=e.id
               WHERE e.id=? AND e.player_id=? AND e.active=1 AND e.role='courier'""",
            (employee_id, player_id),
        ).fetchone()

    def courier_management_snapshot(self, player_id: int, employee_id: int) -> dict | None:
        with self.db.connect() as conn:
            self.simulation._ensure_courier_management_conn(conn, player_id)
            row = self._managed_employee_conn(conn, player_id, employee_id)
            if not row:
                return None
            free_cash = self._free_cash_conn(conn, player_id)
        icon, condition = self._condition(float(row["stress"]))
        policy = self.compensation_policy(player_id, "courier")
        target = int(row["deposit_target"])
        deposit = int(row["deposit"])
        plan_active = deposit < target
        return {
            "employee_id": employee_id,
            "alias": str(row["alias"]),
            "stress": float(row["stress"]),
            "condition_icon": icon,
            "condition": condition,
            "loyalty": float(row["loyalty"]),
            "relationship": self._relationship(float(row["loyalty"])),
            "deposit": deposit,
            "deposit_target": target,
            "deposit_pct": int(row["deposit_contribution_pct"]),
            "plan_active": plan_active,
            "standard_pct": int(policy["deposit_contribution_pct"]),
            "transport_level": int(row["transport_level"]),
            "transport": TRANSPORT[int(row["transport_level"])][0],
            "phone_level": int(row["phone_level"]),
            "phone": PHONE[int(row["phone_level"])][0],
            "invested_total": int(row["invested_total"]),
            "free_cash": free_cash,
            "last_bonus_at": row["last_bonus_at"],
            "last_rest_at": row["last_rest_at"],
            "available": bool(row["available"]),
            "unavailable_until": row["unavailable_until"],
        }

    @staticmethod
    def _condition(stress: float) -> tuple[str, str]:
        if stress >= 78:
            return "🔴", "на пределе"
        if stress >= 52:
            return "🟡", "напряжён"
        return "🟢", "в порядке"

    @staticmethod
    def _relationship(loyalty: float) -> str:
        if loyalty >= 0.82:
            return "🟢 очень хорошее"
        if loyalty >= 0.67:
            return "🟢 хорошее"
        if loyalty >= 0.50:
            return "⚪ нормальное"
        if loyalty >= 0.36:
            return "🟡 прохладное"
        return "🔴 плохое"

    def give_bonus(self, player_id: int, employee_id: int) -> dict:
        now = utcnow()
        with self.db.connect() as conn:
            self.simulation._ensure_courier_management_conn(conn, player_id)
            row = self._managed_employee_conn(conn, player_id, employee_id)
            if not row:
                return {"status": "missing", "message": "Сотрудник недоступен."}
            cooldown = BONUS_COOLDOWN_HOURS - self._game_hours_since(player_id, row["last_bonus_at"])
            if cooldown > 0:
                return {
                    "status": "cooldown",
                    "message": f"Недавняя премия ещё не забылась. Повтори позже, примерно через {cooldown:.0f} игровых ч.",
                }
            if self._free_cash_conn(conn, player_id) < BONUS_COST:
                return {"status": "money", "message": "Недостаточно свободных денег для премии."}

            old_loyalty = float(row["loyalty"])
            old_stress = float(row["stress"])
            base = 0.08 if old_stress >= 52 else 0.055
            loyalty_delta = self._relationship_delta(old_loyalty, base, str(row["trait"]))
            new_loyalty = clamp(old_loyalty + loyalty_delta, 0.0, 1.0)
            new_stress = max(8.0, old_stress - (8.0 if old_stress >= 52 else 5.0))
            self._charge_conn(
                conn,
                player_id,
                employee_id,
                BONUS_COST,
                f"Разовая премия {row['alias']}",
            )
            conn.execute(
                """UPDATE employees
                   SET loyalty=?, stress=?, total_wages_paid=total_wages_paid+?
                   WHERE id=?""",
                (new_loyalty, new_stress, BONUS_COST, employee_id),
            )
            conn.execute(
                """UPDATE courier_management
                   SET invested_total=invested_total+?, bonuses_given=bonuses_given+1,
                       last_bonus_at=?, updated_at=CURRENT_TIMESTAMP
                   WHERE employee_id=?""",
                (BONUS_COST, iso(now), employee_id),
            )
            self._management_event_conn(
                conn,
                player_id,
                employee_id,
                "bonus",
                amount=BONUS_COST,
                loyalty_delta=new_loyalty - old_loyalty,
                stress_delta=new_stress - old_stress,
            )
        return {
            "status": "ok",
            "message": f"{row['alias']} получил премию {BONUS_COST:,} ₽. Отношение улучшилось, напряжение немного снизилось.",
        }

    def send_to_rest(self, player_id: int, employee_id: int, hours: int) -> dict:
        if hours not in REST_OPTIONS:
            return {"status": "invalid", "message": "Такой вариант отдыха недоступен."}
        option = REST_OPTIONS[hours]
        now = utcnow()
        with self.db.connect() as conn:
            self.simulation._ensure_courier_management_conn(conn, player_id)
            row = self._managed_employee_conn(conn, player_id, employee_id)
            if not row:
                return {"status": "missing", "message": "Сотрудник недоступен."}
            if not int(row["available"]):
                return {"status": "busy", "message": "Сотрудник уже временно недоступен."}
            active_tasks = int(
                conn.execute(
                    """SELECT COUNT(*) FROM employee_tasks
                       WHERE player_id=? AND employee_id=? AND status='active'""",
                    (player_id, employee_id),
                ).fetchone()[0]
            )
            if active_tasks:
                return {
                    "status": "tasks",
                    "message": "Сначала дождись завершения текущей задачи сотрудника.",
                }
            cooldown = REST_COOLDOWN_HOURS - self._game_hours_since(player_id, row["last_rest_at"])
            if cooldown > 0:
                return {
                    "status": "cooldown",
                    "message": f"Сотрудник недавно отдыхал. Следующий оплачиваемый отдых будет уместен примерно через {cooldown:.0f} игровых ч.",
                }
            if self._free_cash_conn(conn, player_id) < int(option["cost"]):
                return {"status": "money", "message": "Недостаточно свободных денег для оплачиваемого отдыха."}

            old_loyalty = float(row["loyalty"])
            old_stress = float(row["stress"])
            base_loyalty = float(option["loyalty"]) if old_stress >= 35 else float(option["loyalty"]) * 0.45
            loyalty_delta = self._relationship_delta(old_loyalty, base_loyalty, str(row["trait"]))
            new_loyalty = clamp(old_loyalty + loyalty_delta, 0.0, 1.0)
            new_stress = max(8.0, old_stress - float(option["stress"]))
            until = now + timedelta(hours=hours / self.simulation.effective_speed(player_id))
            cost = int(option["cost"])
            self._charge_conn(
                conn,
                player_id,
                employee_id,
                cost,
                f"Оплачиваемый отдых {row['alias']} · {hours} ч",
            )
            conn.execute(
                """UPDATE employees
                   SET available=0, unavailable_until=?, loyalty=?, stress=?,
                       total_wages_paid=total_wages_paid+?
                   WHERE id=?""",
                (iso(until), new_loyalty, new_stress, cost, employee_id),
            )
            conn.execute(
                """UPDATE courier_management
                   SET invested_total=invested_total+?, rests_taken=rests_taken+1,
                       last_rest_at=?, updated_at=CURRENT_TIMESTAMP
                   WHERE employee_id=?""",
                (cost, iso(now), employee_id),
            )
            self._management_event_conn(
                conn,
                player_id,
                employee_id,
                "rest",
                amount=cost,
                loyalty_delta=new_loyalty - old_loyalty,
                stress_delta=new_stress - old_stress,
                details={"hours": hours},
            )
        return {
            "status": "ok",
            "message": f"{row['alias']} отправлен на оплачиваемый отдых на {hours} игровых ч. Напряжение заметно снизилось.",
        }

    def set_deposit_plan(self, player_id: int, employee_id: int, pct: int) -> dict:
        if pct not in DEPOSIT_PCTS:
            return {"status": "invalid", "message": "Недоступная доля накопления."}
        with self.db.connect() as conn:
            self.simulation._ensure_courier_management_conn(conn, player_id)
            row = self._managed_employee_conn(conn, player_id, employee_id)
            if not row:
                return {"status": "missing", "message": "Сотрудник недоступен."}
            old = int(row["deposit_contribution_pct"])
            if old == pct:
                return {"status": "same", "message": "Этот депозитный план уже выбран."}
            old_loyalty = float(row["loyalty"])
            if pct > old:
                base = -0.012 - (pct - old) / 60.0 * 0.030
            else:
                base = (old - pct) / 60.0 * 0.020
            loyalty_delta = self._relationship_delta(old_loyalty, base, str(row["trait"]))
            new_loyalty = clamp(old_loyalty + loyalty_delta, 0.0, 1.0)
            conn.execute(
                "UPDATE courier_management SET deposit_contribution_pct=?, updated_at=CURRENT_TIMESTAMP WHERE employee_id=?",
                (pct, employee_id),
            )
            conn.execute("UPDATE employees SET loyalty=? WHERE id=?", (new_loyalty, employee_id))
            self._management_event_conn(
                conn,
                player_id,
                employee_id,
                "deposit_pct",
                loyalty_delta=new_loyalty - old_loyalty,
                details={"old": old, "new": pct},
            )
        return {
            "status": "ok",
            "message": f"Теперь до достижения цели {pct}% заработка {row['alias']} направляется в депозит.",
        }

    def set_deposit_target(self, player_id: int, employee_id: int, target: int) -> dict:
        if target not in DEPOSIT_TARGETS:
            return {"status": "invalid", "message": "Недоступная цель депозита."}
        with self.db.connect() as conn:
            self.simulation._ensure_courier_management_conn(conn, player_id)
            row = self._managed_employee_conn(conn, player_id, employee_id)
            if not row:
                return {"status": "missing", "message": "Сотрудник недоступен."}
            old = int(row["deposit_target"])
            if old == target:
                return {"status": "same", "message": "Эта цель уже выбрана."}
            old_loyalty = float(row["loyalty"])
            if target > old and target > int(row["deposit"]):
                base = -0.012 if target - old <= 50_000 else -0.020
            else:
                base = 0.010
            loyalty_delta = self._relationship_delta(old_loyalty, base, str(row["trait"]))
            new_loyalty = clamp(old_loyalty + loyalty_delta, 0.0, 1.0)
            conn.execute(
                "UPDATE courier_management SET deposit_target=?, updated_at=CURRENT_TIMESTAMP WHERE employee_id=?",
                (target, employee_id),
            )
            conn.execute("UPDATE employees SET loyalty=? WHERE id=?", (new_loyalty, employee_id))
            self._management_event_conn(
                conn,
                player_id,
                employee_id,
                "deposit_target",
                loyalty_delta=new_loyalty - old_loyalty,
                details={"old": old, "new": target},
            )
        return {
            "status": "ok",
            "message": f"Цель депозита {row['alias']} изменена на {target:,} ₽.",
        }

    def upgrade_equipment(self, player_id: int, employee_id: int, slot: str) -> dict:
        if slot not in {"transport", "phone"}:
            return {"status": "invalid", "message": "Неизвестный тип оснащения."}
        table = TRANSPORT if slot == "transport" else PHONE
        field = "transport_level" if slot == "transport" else "phone_level"
        with self.db.connect() as conn:
            self.simulation._ensure_courier_management_conn(conn, player_id)
            row = self._managed_employee_conn(conn, player_id, employee_id)
            if not row:
                return {"status": "missing", "message": "Сотрудник недоступен."}
            current = int(row[field])
            if current >= 2:
                return {"status": "max", "message": "Это оснащение уже максимального уровня."}
            new_level = current + 1
            title, cost, _ = table[new_level]
            if self._free_cash_conn(conn, player_id) < cost:
                return {"status": "money", "message": f"Недостаточно свободных денег. Нужно {cost:,} ₽."}

            old_loyalty = float(row["loyalty"])
            base = 0.035 if slot == "transport" else 0.025
            loyalty_delta = self._relationship_delta(old_loyalty, base, str(row["trait"]))
            new_loyalty = clamp(old_loyalty + loyalty_delta, 0.0, 1.0)
            self._charge_conn(
                conn,
                player_id,
                employee_id,
                cost,
                f"Оснащение {row['alias']} · {slot} · {title}",
            )
            conn.execute(
                f"""UPDATE courier_management
                    SET {field}=?, invested_total=invested_total+?, updated_at=CURRENT_TIMESTAMP
                    WHERE employee_id=?""",
                (new_level, cost, employee_id),
            )
            conn.execute("UPDATE employees SET loyalty=? WHERE id=?", (new_loyalty, employee_id))
            if slot == "transport" and new_level == 2:
                conn.execute("UPDATE employees SET has_car=1 WHERE id=?", (employee_id,))
            self._management_event_conn(
                conn,
                player_id,
                employee_id,
                f"upgrade_{slot}",
                amount=cost,
                loyalty_delta=new_loyalty - old_loyalty,
                details={"level": new_level},
            )
        label = "транспорт" if slot == "transport" else "телефон"
        return {
            "status": "ok",
            "message": f"{label.capitalize()} {row['alias']} улучшен: {title}. Вложение {cost:,} ₽ уже влияет на работу.",
        }

    def employee_details(self, player_id: int, employee_id: int) -> str | None:
        text = super().employee_details(player_id, employee_id)
        if not text:
            return text
        snapshot = self.courier_management_snapshot(player_id, employee_id)
        if not snapshot:
            return text
        equipment = (
            "<b>Оснащение</b>\n"
            f"🛵 {snapshot['transport']} · 📱 {snapshot['phone']}\n\n"
        )
        marker = "<b>Что известно</b>"
        if marker in text:
            text = text.replace(marker, equipment + marker, 1)
        return text

    def courier_management_text(self, player_id: int, employee_id: int) -> str | None:
        s = self.courier_management_snapshot(player_id, employee_id)
        if not s:
            return None
        if s["plan_active"]:
            deposit_line = (
                f"{s['deposit']:,} / {s['deposit_target']:,} ₽ · "
                f"{s['deposit_pct']}% заработка"
            )
        else:
            deposit_line = (
                f"{s['deposit']:,} ₽ · цель достигнута · "
                f"стандарт команды {s['standard_pct']}%"
            )
        return (
            f"<b>🧭 Управление · {s['alias']}</b>\n\n"
            f"Состояние: {s['condition_icon']} <b>{s['condition']}</b>\n"
            f"Отношение: {s['relationship']}\n\n"
            f"<b>Депозит</b>\n{deposit_line}\n\n"
            f"<b>Оснащение</b>\n"
            f"🛵 {s['transport']} · 📱 {s['phone']}\n\n"
            f"Вложено в сотрудника: <b>{s['invested_total']:,} ₽</b>\n"
            f"Свободно у магазина: {s['free_cash']:,} ₽\n\n"
            "Премия и отдых помогают состоянию и отношениям, но имеют паузу между повторениями. "
            "Оснащение даёт постоянный рабочий эффект."
        )

    def courier_deposit_text(self, player_id: int, employee_id: int) -> str | None:
        s = self.courier_management_snapshot(player_id, employee_id)
        if not s:
            return None
        state = (
            f"План активен: <b>{s['deposit_pct']}%</b> заработка идёт в депозит."
            if s["plan_active"]
            else f"Цель достигнута. Сейчас действует общий процент команды: <b>{s['standard_pct']}%</b>."
        )
        return (
            f"<b>💰 Депозит · {s['alias']}</b>\n\n"
            f"Сейчас: <b>{s['deposit']:,} ₽</b>\n"
            f"Цель: <b>{s['deposit_target']:,} ₽</b>\n"
            f"{state}\n\n"
            "20% оставляет сотруднику больше денег сейчас. 80% быстрее создаёт финансовое покрытие, "
            "но жёсткий план может ухудшать отношение."
        )

    def courier_equipment_text(self, player_id: int, employee_id: int) -> str | None:
        s = self.courier_management_snapshot(player_id, employee_id)
        if not s:
            return None
        t_next = (
            "максимум"
            if s["transport_level"] >= 2
            else f"{TRANSPORT[s['transport_level'] + 1][0]} · {TRANSPORT[s['transport_level'] + 1][1]:,} ₽"
        )
        p_next = (
            "максимум"
            if s["phone_level"] >= 2
            else f"{PHONE[s['phone_level'] + 1][0]} · {PHONE[s['phone_level'] + 1][1]:,} ₽"
        )
        return (
            f"<b>🧰 Оснащение · {s['alias']}</b>\n\n"
            f"🛵 Транспорт: <b>{s['transport']}</b>\n"
            f"Следующее: {t_next}\n"
            "Влияет на реальный темп подготовки.\n\n"
            f"📱 Телефон: <b>{s['phone']}</b>\n"
            f"Следующее: {p_next}\n"
            "Влияет на аккуратность оформления и качество заказов.\n\n"
            "Улучшение постоянное и привязано к этому сотруднику: если человек окажется неудачным вложением, "
            "потраченные деньги не возвращаются."
        )

    def courier_rest_text(self, player_id: int, employee_id: int) -> str | None:
        s = self.courier_management_snapshot(player_id, employee_id)
        if not s:
            return None
        return (
            f"<b>🏖 Отдых · {s['alias']}</b>\n\n"
            f"Сейчас: {s['condition_icon']} <b>{s['condition']}</b>\n\n"
            "12 ч · 3 000 ₽ — заметно снимает напряжение.\n"
            "24 ч · 5 500 ₽ — сильное восстановление и больший эффект на отношение.\n\n"
            "На время отдыха сотрудник недоступен, поэтому его товар временно не участвует в продажах."
        )
