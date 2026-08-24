from __future__ import annotations

import json
import math
from datetime import timedelta

from .courier_model import TRAIT_CONCEALS, TRAIT_LEARNER, TRAIT_METICULOUS, TRAIT_OVERHEATS, TRAIT_PRESSURE_PROOF, TRAIT_SENSITIVE, TRAIT_STEADY, condition_band, pace_band, relationship_band
from .customer_trust import CustomerTrustGameService, CustomerTrustSimulationEngine
from .simulation import clamp, iso, utcnow


class CourierCoreSimulationEngine(CustomerTrustSimulationEngine):
    """Live economy with distinct hidden courier personalities and observable history."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            pass
            self._ensure_courier_profiles_conn(conn)

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        with self.db.connect() as conn:
            pass
            self._ensure_courier_profiles_conn(conn, player_id)
        return created

    def _ensure_courier_profiles_conn(self, conn, player_id: int | None = None) -> None:
        params = () if player_id is None else (player_id,)
        where = "" if player_id is None else " AND e.player_id=?"
        rows = conn.execute(
            f"""SELECT e.* FROM employees e
                LEFT JOIN courier_profiles cp ON cp.employee_id=e.id
                WHERE e.role='courier' AND cp.employee_id IS NULL {where}
                ORDER BY e.id""",
            params,
        ).fetchall()
        traits = (
            TRAIT_STEADY,
            TRAIT_METICULOUS,
            TRAIT_OVERHEATS,
            TRAIT_PRESSURE_PROOF,
            TRAIT_SENSITIVE,
            TRAIT_LEARNER,
        )
        for row in rows:
            pace = clamp(float(row["reliability"]), 0.45, 0.97)
            precision = clamp(float(row["attention"]), 0.45, 0.99)
            integrity = clamp(float(row["honesty"]), 0.30, 0.99)
            resilience = clamp(0.56 + (pace + precision - 1.2) * 0.28, 0.48, 0.93)
            if integrity < 0.58:
                trait = TRAIT_CONCEALS
            elif precision >= 0.90 and pace < 0.72:
                trait = TRAIT_METICULOUS
            elif pace >= 0.88 and resilience < 0.68:
                trait = TRAIT_OVERHEATS
            else:
                trait = traits[int(row["id"]) % len(traits)]
            conn.execute(
                """INSERT INTO courier_profiles(
                       employee_id, player_id, pace, precision, resilience, integrity, trait
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (int(row["id"]), int(row["player_id"]), pace, precision, resilience, integrity, trait),
            )
            self._sync_legacy_mirrors_conn(conn, int(row["id"]))

    def _profile_conn(self, conn, employee_id: int):
        return conn.execute(
            "SELECT * FROM courier_profiles WHERE employee_id=?",
            (employee_id,),
        ).fetchone()

    def _profile(self, employee_id: int):
        with self.db.connect() as conn:
            return self._profile_conn(conn, employee_id)

    def _sync_legacy_mirrors_conn(self, conn, employee_id: int) -> None:
        profile = self._profile_conn(conn, employee_id)
        if not profile:
            return
        # Lower shared layers still read these columns. For couriers they are only
        # mirrors of the canonical profile, never independently generated stats.
        conn.execute(
            """UPDATE employees
               SET reliability=?, attention=?, honesty=?
               WHERE id=? AND role='courier'""",
            (
                float(profile["pace"]),
                float(profile["precision"]),
                float(profile["integrity"]),
                employee_id,
            ),
        )

    @staticmethod
    def _learning_bonus(profile) -> float:
        if profile["trait"] != TRAIT_LEARNER:
            return 0.0
        return min(0.08, int(profile["observed_orders"] or 0) / 180.0 * 0.08)

    def _effective_pace(self, profile, stress: float) -> float:
        base = float(profile["pace"]) + self._learning_bonus(profile)
        pressure = max(0.0, (float(stress) - 38.0) / 62.0)
        sensitivity = 1.0 - float(profile["resilience"])
        penalty = pressure * sensitivity * 0.42
        trait = str(profile["trait"])
        if trait == TRAIT_OVERHEATS:
            penalty *= 1.65
            if stress < 45:
                base += 0.035
        elif trait == TRAIT_SENSITIVE:
            penalty *= 1.45
        elif trait == TRAIT_PRESSURE_PROOF:
            penalty *= 0.30
        elif trait == TRAIT_METICULOUS:
            base -= 0.025
        return clamp(base - penalty, 0.34, 1.08)

    def _effective_precision(self, profile, stress: float) -> float:
        base = float(profile["precision"]) + self._learning_bonus(profile)
        pressure = max(0.0, (float(stress) - 35.0) / 65.0)
        sensitivity = 1.0 - float(profile["resilience"])
        penalty = pressure * sensitivity * 0.52
        trait = str(profile["trait"])
        if trait == TRAIT_OVERHEATS:
            penalty *= 1.75
        elif trait == TRAIT_SENSITIVE:
            penalty *= 1.55
        elif trait == TRAIT_PRESSURE_PROOF:
            penalty *= 0.32
        elif trait == TRAIT_METICULOUS:
            base += 0.025
        return clamp(base - penalty, 0.32, 0.995)

    def _stress_per_order(self, profile) -> float:
        value = 0.07 + (1.0 - float(profile["resilience"])) * 0.24
        trait = str(profile["trait"])
        if trait == TRAIT_OVERHEATS:
            value *= 1.55
        elif trait == TRAIT_SENSITIVE:
            value *= 1.35
        elif trait == TRAIT_PRESSURE_PROOF:
            value *= 0.55
        return value

    @staticmethod
    def _employee_id(employee) -> int:
        if isinstance(employee, dict):
            for key in ("id", "employee_id", "retail_employee_id"):
                value = employee.get(key)
                if value is not None:
                    return int(value)
            return 0
        keys = set(employee.keys()) if hasattr(employee, "keys") else set()
        for key in ("id", "employee_id", "retail_employee_id"):
            if key in keys and employee[key] is not None:
                return int(employee[key])
        return 0

    def _courier_rating(self, employee) -> int:
        employee_id = self._employee_id(employee)
        profile = self._profile(employee_id) if employee_id else None
        if not profile:
            return super()._courier_rating(employee)
        precision = self._effective_precision(profile, float(employee["stress"]))
        pace = self._effective_pace(profile, float(employee["stress"]))
        relationship = float(employee["loyalty"])
        service = precision * 0.78 + pace * 0.10 + relationship * 0.12 + self.rng.uniform(-0.035, 0.035)
        if service >= 0.90:
            return 5
        if service >= 0.78:
            return 4
        if service >= 0.65:
            return 3
        if service >= 0.52:
            return 2
        return 1

    def _dispute_probability(self, client, employee, quality: float, modifier: float) -> float:
        employee_id = self._employee_id(employee)
        profile = self._profile(employee_id) if employee_id else None
        if not profile:
            return super()._dispute_probability(client, employee, quality, modifier)
        stress = float(employee.get("stress", 10.0)) if isinstance(employee, dict) else float(employee["stress"])
        precision = self._effective_precision(profile, stress)
        employee_error = (1.0 - precision) * 0.34
        pressure = max(0.0, stress - 50.0) / 50.0
        stress_error = pressure * (1.0 - float(profile["resilience"])) * 0.12
        quality_error = max(0.0, 78.0 - float(quality)) / 100.0 * 0.14
        fraud = float(client["fraud_propensity"]) * 0.10
        return clamp((0.016 + employee_error + stress_error + quality_error + fraud) * float(modifier), 0.01, 0.42)

    def _open_dispute(self, conn, player_id: int, order_id: int, client, employee, quality: float, revenue: int, now) -> None:
        employee_id = self._employee_id(employee)
        profile = self._profile_conn(conn, employee_id) if employee_id else None
        if not profile:
            super()._open_dispute(conn, player_id, order_id, client, employee, quality, revenue, now)
            return
        stress = float(employee.get("stress", 10.0)) if isinstance(employee, dict) else float(employee["stress"])
        proxy = {
            "id": employee_id,
            "attention": self._effective_precision(profile, stress),
            "stress": stress,
            "honesty": float(profile["integrity"]),
            "loyalty": float(employee.get("loyalty", 0.55)) if isinstance(employee, dict) else float(employee["loyalty"]),
        }
        super()._open_dispute(conn, player_id, order_id, client, proxy, quality, revenue, now)

    def _record_rating_conn(self, conn, order_id: int, employee) -> int:
        existed = conn.execute("SELECT 1 FROM order_ratings WHERE order_id=?", (order_id,)).fetchone()
        result = super()._record_rating_conn(conn, order_id, employee)
        if existed:
            return result
        rating = conn.execute(
            "SELECT courier_rating, employee_id FROM order_ratings WHERE order_id=?",
            (order_id,),
        ).fetchone()
        if not rating:
            return result
        stress = float(employee["stress"])
        high = int(stress >= 58.0)
        conn.execute(
            """UPDATE courier_profiles
               SET observed_orders=observed_orders+1,
                   rating_sum=rating_sum+?,
                   high_stress_orders=high_stress_orders+?,
                   high_stress_rating_sum=high_stress_rating_sum+?
               WHERE employee_id=?""",
            (
                int(rating["courier_rating"]),
                high,
                int(rating["courier_rating"]) if high else 0,
                int(rating["employee_id"]),
            ),
        )
        return result

    def _create_retail_order(self, conn, player_id: int, listing, now) -> bool | None:
        selected = conn.execute(
            """SELECT rp.employee_id, e.stress
               FROM retail_positions rp
               JOIN employees e ON e.id=rp.employee_id
               WHERE rp.player_id=? AND rp.product_id=? AND rp.pack_size=?
                 AND rp.position_count>0 AND e.active=1 AND e.available=1 AND e.role='courier'
               ORDER BY rp.created_at, rp.id LIMIT 1""",
            (player_id, listing["product_id"], listing["pack_size"]),
        ).fetchone()
        result = super()._create_retail_order(conn, player_id, listing, now)
        if result is None or not selected:
            return result
        profile = self._profile_conn(conn, int(selected["employee_id"]))
        if profile:
            new_stress = min(100.0, float(selected["stress"]) + self._stress_per_order(profile))
            conn.execute(
                "UPDATE employees SET stress=? WHERE id=?",
                (new_stress, int(selected["employee_id"])),
            )
        return result

    def _process_tasks(self, conn, player_id: int, now) -> int:
        due = conn.execute(
            """SELECT t.id, t.employee_id, t.quantity, m.planned_game_hours, m.effective_pace
               FROM employee_tasks t
               JOIN courier_task_metrics m ON m.task_id=t.id
               WHERE t.player_id=? AND t.kind='prepare_positions' AND t.status='active'
                 AND t.completes_at<=?""",
            (player_id, iso(now)),
        ).fetchall()

        completed = super()._process_tasks(conn, player_id, now)

        for task in due:
            state = conn.execute("SELECT status FROM employee_tasks WHERE id=?", (task["id"],)).fetchone()
            if not state or state["status"] != "completed":
                continue
            conn.execute(
                """UPDATE courier_profiles
                   SET prep_tasks=prep_tasks+1,
                       prep_units=prep_units+?,
                       prep_game_hours=prep_game_hours+?,
                       pace_observation_sum=pace_observation_sum+?,
                       pace_observation_count=pace_observation_count+1
                   WHERE employee_id=?""",
                (
                    int(task["quantity"]),
                    float(task["planned_game_hours"]),
                    float(task["effective_pace"]),
                    int(task["employee_id"]),
                ),
            )

        new_tasks = conn.execute(
            """SELECT t.*, e.stress
               FROM employee_tasks t
               JOIN employees e ON e.id=t.employee_id
               LEFT JOIN courier_task_metrics m ON m.task_id=t.id
               WHERE t.player_id=? AND t.kind='prepare_positions' AND t.status='active'
                 AND e.role='courier' AND m.task_id IS NULL""",
            (player_id,),
        ).fetchall()
        for task in new_tasks:
            profile = self._profile_conn(conn, int(task["employee_id"]))
            if not profile:
                continue
            stress = float(task["stress"])
            effective_pace = self._effective_pace(profile, stress)
            base_hours = 0.48 + max(1, int(task["quantity"])) / 18.0 * 0.62
            if profile["trait"] == TRAIT_METICULOUS:
                base_hours *= 1.08
            planned = max(0.25, base_hours / effective_pace)
            conn.execute(
                "UPDATE employee_tasks SET completes_at=? WHERE id=?",
                (
                    iso(now + timedelta(hours=planned / self.effective_speed(player_id))),
                    int(task["id"]),
                ),
            )
            conn.execute(
                """INSERT INTO courier_task_metrics(
                       task_id, player_id, employee_id, planned_game_hours,
                       effective_pace, stress_at_start
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    int(task["id"]),
                    player_id,
                    int(task["employee_id"]),
                    planned,
                    effective_pace,
                    stress,
                ),
            )
        return completed

    def _recover_courier_state_conn(self, conn, player_id: int, sim_hours: float) -> None:
        if sim_hours <= 0:
            return
        rows = conn.execute(
            """SELECT e.id, e.stress, cp.resilience, cp.trait
               FROM employees e JOIN courier_profiles cp ON cp.employee_id=e.id
               WHERE e.player_id=? AND e.active=1 AND e.role='courier'""",
            (player_id,),
        ).fetchall()
        for row in rows:
            recovery = (0.24 + float(row["resilience"]) * 0.28) * min(float(sim_hours), 24.0)
            if row["trait"] == TRAIT_PRESSURE_PROOF:
                recovery *= 1.12
            elif row["trait"] == TRAIT_SENSITIVE:
                recovery *= 0.90
            stress = max(8.0, float(row["stress"]) - recovery)
            conn.execute("UPDATE employees SET stress=? WHERE id=?", (stress, int(row["id"])))

    def _simulate_courier_problem_conn(self, conn, player_id: int, sim_hours: float, now) -> int:
        rows = conn.execute(
            """SELECT e.*, cp.resilience, cp.integrity, cp.trait
               FROM employees e JOIN courier_profiles cp ON cp.employee_id=e.id
               WHERE e.player_id=? AND e.active=1 AND e.available=1 AND e.role='courier'
                 AND e.stress>=58
               ORDER BY e.stress DESC""",
            (player_id,),
        ).fetchall()
        for row in rows:
            existing = conn.execute(
                """SELECT 1 FROM inbox
                   WHERE player_id=? AND status='open' AND kind='courier_problem'
                     AND json_extract(payload_json, '$.employee_id')=? LIMIT 1""",
                (player_id, int(row["id"])),
            ).fetchone()
            if existing:
                continue
            pressure = max(0.0, (float(row["stress"]) - 55.0) / 45.0)
            fragility = 1.0 - float(row["resilience"])
            trait_factor = 1.0
            if row["trait"] == TRAIT_OVERHEATS:
                trait_factor = 1.55
            elif row["trait"] == TRAIT_SENSITIVE:
                trait_factor = 1.75
            elif row["trait"] == TRAIT_PRESSURE_PROOF:
                trait_factor = 0.35
            hourly = 0.0025 * pressure * (0.35 + fragility * 1.8) * trait_factor
            chance = 1.0 - math.exp(-hourly * min(max(0.0, float(sim_hours)), 12.0))
            if chance <= 0 or self.rng.random() >= chance:
                continue

            pause_hours = self.rng.choice([2, 3, 4, 6])
            until = now + timedelta(hours=pause_hours / self.effective_speed(player_id))
            conn.execute(
                """UPDATE employees
                   SET available=0, unavailable_until=?, stress=MAX(35, stress-18)
                   WHERE id=?""",
                (iso(until), int(row["id"])),
            )
            conn.execute(
                """UPDATE courier_profiles
                   SET negative_events=negative_events+1, missed_shifts=missed_shifts+1
                   WHERE employee_id=?""",
                (int(row["id"]),),
            )
            body = (
                f"{row['alias']} внезапно выпал из работы.\n\n"
                f"Пауза: около {pause_hours} игровых ч\n"
                "Перед срывом сотрудник работал в напряжённом состоянии. "
                "Это учитывается в его дальнейшей статистике надёжности."
            )
            conn.execute(
                """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json)
                   VALUES (?, 'courier_problem', 'important', 'Срыв работы сотрудника', ?, ?)""",
                (
                    player_id,
                    body,
                    json.dumps({"employee_id": int(row["id"])}, ensure_ascii=False),
                ),
            )
            return 1
        return 0

    def _simulate_management_events(self, conn, player_id: int, sim_hours: float, now) -> int:
        self._ensure_courier_profiles_conn(conn, player_id)
        self._recover_courier_state_conn(conn, player_id, sim_hours)
        created = super()._simulate_management_events(conn, player_id, sim_hours, now)
        created += self._simulate_courier_problem_conn(conn, player_id, sim_hours, now)
        return created


class CourierCoreGameService(CustomerTrustGameService):
    """Player-facing courier profile based on observed performance, not hidden stats."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            pass
            self.simulation._ensure_courier_profiles_conn(conn)

    def hire_candidate(self, player_id: int, candidate_id: int) -> str:
        with self.db.connect() as conn:
            candidate = conn.execute(
                "SELECT * FROM candidates WHERE id=? AND player_id=? AND status='open'",
                (candidate_id, player_id),
            ).fetchone()
            profile = conn.execute(
                "SELECT * FROM courier_candidate_profiles WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        result = super().hire_candidate(player_id, candidate_id)
        if not candidate or candidate["role"] != "courier" or not profile:
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
            conn.execute(
                """INSERT OR REPLACE INTO courier_profiles(
                       employee_id, player_id, pace, precision, resilience, integrity, trait
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(employee["id"]),
                    player_id,
                    float(profile["pace"]),
                    float(profile["precision"]),
                    float(profile["resilience"]),
                    float(profile["integrity"]),
                    str(profile["trait"]),
                ),
            )
            self.simulation._sync_legacy_mirrors_conn(conn, int(employee["id"]))
        return result

    @staticmethod
    def _reliability_label(employee, profile) -> str:
        orders = int(profile["observed_orders"] or 0)
        events = int(profile["negative_events"] or 0)
        jobs = max(1, int(employee["jobs_done"] or 0))
        dispute_rate = int(employee["disputes"] or 0) / jobs
        if orders < 10 and int(profile["prep_tasks"] or 0) < 3:
            return "пока мало данных"
        if int(employee["losses"] or 0) > 0 or events >= 2:
            return "низкая"
        if events == 1 or dispute_rate >= 0.12:
            return "нестабильная"
        if orders >= 45 and dispute_rate <= 0.05:
            return "высокая"
        return "нормальная"

    @staticmethod
    def _observations(employee, profile) -> list[str]:
        lines: list[str] = []
        pace_n = int(profile["pace_observation_count"] or 0)
        orders = int(profile["observed_orders"] or 0)
        if pace_n >= 2:
            observed_pace = float(profile["pace_observation_sum"] or 0) / pace_n
            band = pace_band(observed_pace)
            if band in {"высокий", "очень высокий"}:
                lines.append("Работает быстрее большинства сотрудников.")
            elif band == "низкий":
                lines.append("На подготовку товара обычно требуется больше времени.")
        if orders >= 8:
            avg = float(profile["rating_sum"] or 0) / max(1, orders)
            if avg >= 4.55:
                lines.append("По заказам держит стабильно высокое качество работы.")
            elif avg < 3.75:
                lines.append("Ошибки и слабые оценки встречаются заметно чаще среднего.")
        high_n = int(profile["high_stress_orders"] or 0)
        if high_n >= 6 and orders > high_n:
            high_avg = float(profile["high_stress_rating_sum"] or 0) / high_n
            normal_n = max(1, orders - high_n)
            normal_avg = (float(profile["rating_sum"] or 0) - float(profile["high_stress_rating_sum"] or 0)) / normal_n
            if high_avg + 0.35 < normal_avg:
                lines.append("Под высокой нагрузкой качество работы заметно падает.")
            elif high_avg >= normal_avg - 0.15:
                lines.append("Даже под высокой нагрузкой качество почти не проседает.")
        if int(profile["negative_events"] or 0) >= 1:
            lines.append("Уже были внезапные срывы работы под нагрузкой.")
        return lines[:4]

    def employee_details(self, player_id: int, employee_id: int) -> str | None:
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=?",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                return None
            if employee["role"] != "courier":
                return super().employee_details(player_id, employee_id)
            profile = conn.execute(
                "SELECT * FROM courier_profiles WHERE employee_id=?",
                (employee_id,),
            ).fetchone()
        if not profile:
            return super().employee_details(player_id, employee_id)

        exposure = self._employee_exposure(player_id, employee_id)
        unsecured = max(0, exposure - int(employee["deposit"]))
        policy = self.compensation_policy(player_id, "courier")
        service = self.employee_service_metrics(player_id, employee_id)
        activity = "\n".join(self._activity_details(player_id, employee_id))
        inventory = self._inventory_lines(player_id, employee_id, "courier")
        inventory_text = "\n".join(inventory) if inventory else "Нет товара под ответственностью."
        icon, condition = condition_band(float(employee["stress"]))

        pace_n = int(profile["pace_observation_count"] or 0)
        if pace_n >= 2:
            observed_pace = float(profile["pace_observation_sum"] or 0) / pace_n
            pace_text = pace_band(observed_pace)
            throughput = (
                f" · {int(profile['prep_units']) / max(0.1, float(profile['prep_game_hours'])):.1f} ед./игр. ч"
                if int(profile["prep_units"] or 0) > 0 else ""
            )
        else:
            pace_text = "пока мало данных"
            throughput = ""

        reliability = self._reliability_label(employee, profile)
        observations = self._observations(employee, profile)
        observation_text = "\n".join(f"• {line}" for line in observations) if observations else "Пока слишком мало истории, чтобы делать выводы."
        dispute_rate = int(employee["disputes"] or 0) / max(1, int(employee["jobs_done"] or 0)) * 100.0
        accrued_cash = int(employee["wages_accrued"]) - int(employee["deposit_accrued"])

        text = (
            f"<b>👤 {employee['alias']} · Розничный сотрудник</b>\n\n"
            f"<b>Сейчас</b>\n{activity}\n"
            f"Состояние: {icon} <b>{condition}</b>\n\n"
            f"<b>Работа</b>\n"
            f"⚡ Темп: <b>{pace_text}</b>{throughput}\n"
        )
        if service["count"]:
            text += f"⭐ Качество: <b>{service['rating']:.2f}/5</b> · {service['count']} заказов\n"
        else:
            text += "⭐ Качество: пока нет оценок\n"
        text += (
            f"🛡 Надёжность: <b>{reliability}</b>\n"
            f"Диспуты: {int(employee['disputes'])} · {dispute_rate:.1f}%\n\n"
            f"<b>Ответственность</b>\n"
            f"Товар: {exposure:,} ₽\n"
            f"Депозит: <b>{int(employee['deposit']):,} ₽</b>\n"
            f"Не покрыто: <b>{unsecured:,} ₽</b>\n\n"
            f"<b>Что известно</b>\n{observation_text}\n\n"
            f"<b>Отношение</b>\n{relationship_band(float(employee['loyalty']))}\n\n"
            f"<b>Условия</b>\n"
            f"За заказ: {policy['fixed_fee']:,} ₽ + {policy['base_rate_bps'] / 100:.1f}% с продажи\n"
            f"В депозит: {policy['deposit_contribution_pct']}%\n"
            f"Начислено: <b>{int(employee['wages_accrued']):,} ₽</b>\n"
            f"Из них деньгами: {accrued_cash:,} ₽\n\n"
            f"<b>Товар</b>\n{inventory_text}\n\n"
            f"<b>История</b>\n"
            f"Заказов: {int(employee['jobs_done'])}\n"
            f"Срывов работы: {int(profile['negative_events'])}\n"
            f"Потери: {int(employee['losses']):,} ₽\n"
            f"Всего заработано: {int(employee['total_wages_paid']) + int(employee['wages_accrued']):,} ₽"
        )
        if unsecured > 0:
            text += "\n\n🔴 Часть товара не покрыта депозитом. Риск серьёзного инцидента выше."
        return text
