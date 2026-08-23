from __future__ import annotations

from datetime import timedelta

from .simulation import iso, parse_dt, utcnow
from .workflow_final import FinalWorkflowGameService, FinalWorkflowSimulationEngine


STAFF_INSIGHT_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_clock (
    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
    game_hours REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS publication_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    allocation_id INTEGER NOT NULL UNIQUE REFERENCES retail_allocations(id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    units INTEGER NOT NULL,
    positions INTEGER NOT NULL,
    game_hour REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_publication_employee_game_hour
    ON publication_events(player_id, employee_id, game_hour);
"""


class StaffInsightSimulationEngine(FinalWorkflowSimulationEngine):
    """Final simulation layer for starter safety and historical staff throughput."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(STAFF_INSIGHT_SCHEMA)

    def _seed_retail_positions(self, player_id: int) -> None:
        # A fresh game must not silently expose starter couriers to inventory risk.
        # Starter stock remains with the wholesale employee until the player deliberately
        # assigns an amount to retail.
        return None

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO game_clock(player_id, game_hours) VALUES (?, 0)",
                (player_id,),
            )
            if created:
                conn.execute(
                    """UPDATE inbox
                       SET body=?
                       WHERE player_id=? AND kind='tutorial' AND status='open'""",
                    (
                        "Стартовые партии находятся у оптового сотрудника и не выставлены на витрину.\n\n"
                        "Открой «Команда», выбери оптового сотрудника и самостоятельно распредели товар между розничными сотрудниками. "
                        "Непокрытый депозитом риск появляется только после твоего решения передать сотруднику слишком дорогой объём.",
                        player_id,
                    ),
                )
        return created

    def current_game_hour(self, player_id: int, now=None) -> float:
        now = now or utcnow()
        with self.db.connect() as conn:
            clock = conn.execute(
                "SELECT game_hours FROM game_clock WHERE player_id=?",
                (player_id,),
            ).fetchone()
            shop = conn.execute(
                "SELECT last_simulated_at FROM shops WHERE player_id=?",
                (player_id,),
            ).fetchone()
        stored = float(clock["game_hours"]) if clock else 0.0
        if not shop:
            return stored
        real_hours = max(0.0, (now - parse_dt(shop["last_simulated_at"])).total_seconds() / 3600.0)
        pending = min(real_hours * self.effective_speed(player_id), 72.0)
        return stored + pending

    def advance(self, player_id: int, now=None):
        now = now or utcnow()
        with self.db.connect() as conn:
            shop = conn.execute(
                "SELECT last_simulated_at FROM shops WHERE player_id=?",
                (player_id,),
            ).fetchone()
        sim_hours = 0.0
        if shop:
            real_hours = max(0.0, (now - parse_dt(shop["last_simulated_at"])).total_seconds() / 3600.0)
            sim_hours = min(real_hours * self.effective_speed(player_id), 72.0)
        result = super().advance(player_id, now)
        if sim_hours >= 0.015:
            with self.db.connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO game_clock(player_id, game_hours) VALUES (?, 0)",
                    (player_id,),
                )
                conn.execute(
                    "UPDATE game_clock SET game_hours=game_hours+? WHERE player_id=?",
                    (sim_hours, player_id),
                )
        return result

    def _publish_allocation(self, conn, player_id: int, allocation_id: int) -> None:
        exists = conn.execute(
            "SELECT 1 FROM publication_events WHERE allocation_id=?",
            (allocation_id,),
        ).fetchone()
        super()._publish_allocation(conn, player_id, allocation_id)
        if exists:
            return
        allocation = conn.execute(
            "SELECT * FROM retail_allocations WHERE id=? AND player_id=? AND status='published'",
            (allocation_id, player_id),
        ).fetchone()
        if not allocation:
            return
        totals = conn.execute(
            """SELECT COALESCE(SUM(position_count),0) positions,
                      COALESCE(SUM(position_count*pack_size),0) units
               FROM retail_positions WHERE allocation_id=?""",
            (allocation_id,),
        ).fetchone()
        positions = int(totals["positions"] or 0)
        units = int(totals["units"] or 0)
        if positions <= 0:
            return
        conn.execute(
            """INSERT OR IGNORE INTO publication_events(
                   player_id, allocation_id, employee_id, product_id,
                   units, positions, game_hour
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                player_id,
                allocation_id,
                allocation["retail_employee_id"],
                allocation["product_id"],
                units,
                positions,
                self.current_game_hour(player_id),
            ),
        )


class StaffInsightGameService(FinalWorkflowGameService):
    """Employee profile with explicit activity, inventory and throughput history."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(STAFF_INSIGHT_SCHEMA)

    def _task_status(self, player_id: int, employee_id: int) -> str:
        now = utcnow()
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
            task = conn.execute(
                """SELECT t.*, p.title product_title
                   FROM employee_tasks t
                   LEFT JOIN products p ON p.id=t.product_id
                   WHERE t.player_id=? AND t.employee_id=? AND t.status='active'
                   ORDER BY t.completes_at LIMIT 1""",
                (player_id, employee_id),
            ).fetchone()
            if task:
                remaining_real = max(0.0, (parse_dt(task["completes_at"]) - now).total_seconds() / 3600.0)
                remaining_game = remaining_real * self.simulation.effective_speed(player_id)
                eta = "менее 1 ч" if remaining_game < 1 else f"~{remaining_game:.1f} ч"
                labels = {
                    "receive_batch": "получает партию",
                    "handoff": "готовит передачу",
                    "prepare_positions": "готовит позиции",
                }
                return f"{labels.get(task['kind'], task['kind'])} · {eta}"
            if not employee["available"]:
                if employee["unavailable_until"]:
                    remaining_real = max(0.0, (parse_dt(employee["unavailable_until"]) - now).total_seconds() / 3600.0)
                    remaining_game = remaining_real * self.simulation.effective_speed(player_id)
                    eta = "менее 1 ч" if remaining_game < 1 else f"~{remaining_game:.1f} ч"
                    return f"временная пауза · {eta}"
                return "временно недоступен"
            if employee["role"] == "courier":
                waiting = int(conn.execute(
                    """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                       WHERE player_id=? AND retail_employee_id=? AND status='waiting'""",
                    (player_id, employee_id),
                ).fetchone()[0])
                if waiting:
                    return f"ожидает товар · {waiting} ед."
            else:
                ready = int(conn.execute(
                    """SELECT COALESCE(SUM(remaining),0) FROM batches
                       WHERE player_id=? AND responsible_employee_id=?
                         AND status='warehouse' AND remaining>0""",
                    (player_id, employee_id),
                ).fetchone()[0])
                if ready:
                    return f"свободен · к распределению {ready} ед."
        return "свободен"

    def _activity_details(self, player_id: int, employee_id: int) -> list[str]:
        now = utcnow()
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=?",
                (employee_id, player_id),
            ).fetchone()
            task = conn.execute(
                """SELECT t.*, p.title product_title
                   FROM employee_tasks t LEFT JOIN products p ON p.id=t.product_id
                   WHERE t.player_id=? AND t.employee_id=? AND t.status='active'
                   ORDER BY t.completes_at LIMIT 1""",
                (player_id, employee_id),
            ).fetchone()
        if not employee:
            return []
        lines = [f"Статус: <b>{self._task_status(player_id, employee_id)}</b>"]
        if task:
            labels = {
                "receive_batch": "Получение партии",
                "handoff": "Подготовка передачи рознице",
                "prepare_positions": "Подготовка позиций к публикации",
            }
            remaining_real_min = max(0.0, (parse_dt(task["completes_at"]) - now).total_seconds() / 60.0)
            remaining_game_h = remaining_real_min / 60.0 * self.simulation.effective_speed(player_id)
            lines.append(f"Задача: {labels.get(task['kind'], task['kind'])}")
            if task["product_title"]:
                lines.append(f"Товар: {task['product_title']} · {int(task['quantity'])} ед.")
            real_eta = "менее 1 мин" if remaining_real_min < 1 else f"~{remaining_real_min:.0f} мин"
            game_eta = "менее 1 ч" if remaining_game_h < 1 else f"~{remaining_game_h:.1f} ч"
            lines.append(f"Осталось: {game_eta} игровых · {real_eta} реальных")
        return lines

    def _inventory_lines(self, player_id: int, employee_id: int, role: str) -> list[str]:
        with self.db.connect() as conn:
            products = conn.execute("SELECT id, title FROM products WHERE active=1 ORDER BY id").fetchall()
            lines: list[str] = []
            for product in products:
                if role == "courier":
                    waiting = int(conn.execute(
                        """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                           WHERE player_id=? AND retail_employee_id=? AND product_id=? AND status='waiting'""",
                        (player_id, employee_id, product["id"]),
                    ).fetchone()[0])
                    preparing = int(conn.execute(
                        """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                           WHERE player_id=? AND retail_employee_id=? AND product_id=? AND status='preparing'""",
                        (player_id, employee_id, product["id"]),
                    ).fetchone()[0])
                    published = conn.execute(
                        """SELECT COALESCE(SUM(position_count*pack_size),0) units,
                                  COALESCE(SUM(position_count),0) positions
                           FROM retail_positions
                           WHERE player_id=? AND employee_id=? AND product_id=? AND position_count>0""",
                        (player_id, employee_id, product["id"]),
                    ).fetchone()
                    published_units = int(published["units"] or 0)
                    positions = int(published["positions"] or 0)
                    if waiting or preparing or published_units:
                        parts = []
                        if waiting:
                            parts.append(f"ожидает {waiting} ед.")
                        if preparing:
                            parts.append(f"на руках {preparing} ед.")
                        if published_units:
                            parts.append(f"витрина {published_units} ед. / {positions} поз.")
                        lines.append(f"{product['title']}: " + " · ".join(parts))
                else:
                    receiving = int(conn.execute(
                        """SELECT COALESCE(SUM(remaining),0) FROM batches
                           WHERE player_id=? AND responsible_employee_id=? AND product_id=?
                             AND status='receiving'""",
                        (player_id, employee_id, product["id"]),
                    ).fetchone()[0])
                    ready = int(conn.execute(
                        """SELECT COALESCE(SUM(remaining),0) FROM batches
                           WHERE player_id=? AND responsible_employee_id=? AND product_id=?
                             AND status='warehouse'""",
                        (player_id, employee_id, product["id"]),
                    ).fetchone()[0])
                    handoff = int(conn.execute(
                        """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                           WHERE player_id=? AND wholesale_employee_id=? AND product_id=? AND status='waiting'""",
                        (player_id, employee_id, product["id"]),
                    ).fetchone()[0])
                    if receiving or ready or handoff:
                        parts = []
                        if receiving:
                            parts.append(f"получает {receiving} ед.")
                        if ready:
                            parts.append(f"готово {ready} ед.")
                        if handoff:
                            parts.append(f"передаёт {handoff} ед.")
                        lines.append(f"{product['title']}: " + " · ".join(parts))
        return lines

    def _productivity_lines(self, player_id: int, employee_id: int) -> list[str]:
        current_hour = float(self.simulation.current_game_hour(player_id))
        with self.db.connect() as conn:
            total = conn.execute(
                """SELECT COUNT(*) events, COALESCE(SUM(positions),0) positions,
                          MIN(game_hour) first_hour
                   FROM publication_events
                   WHERE player_id=? AND employee_id=?""",
                (player_id, employee_id),
            ).fetchone()
            last = int(conn.execute(
                """SELECT COALESCE(SUM(positions),0) FROM publication_events
                   WHERE player_id=? AND employee_id=? AND game_hour>?""",
                (player_id, employee_id, current_hour - 24.0),
            ).fetchone()[0])
            previous = int(conn.execute(
                """SELECT COALESCE(SUM(positions),0) FROM publication_events
                   WHERE player_id=? AND employee_id=? AND game_hour>? AND game_hour<=?""",
                (player_id, employee_id, current_hour - 48.0, current_hour - 24.0),
            ).fetchone()[0])
        if not total or int(total["events"] or 0) == 0:
            return ["Средняя: пока нет данных", "Динамика: появится после первых публикаций"]
        first_hour = float(total["first_hour"] or current_hour)
        active_days = max(1.0, (current_hour - first_hour) / 24.0)
        average = int(total["positions"] or 0) / active_days
        lines = [f"Средняя: <b>{average:.1f} поз. / игровые сутки</b>", f"Последние 24 игровых ч: {last} поз."]
        if previous > 0:
            delta = (last / previous - 1.0) * 100.0
            arrow = "↑" if delta > 2 else "↓" if delta < -2 else "→"
            lines.append(f"К предыдущим суткам: {arrow} {delta:+.0f}%")
        elif current_hour >= 48.0:
            lines.append("К предыдущим суткам: нет базы для сравнения")
        else:
            lines.append("Динамика: нужно минимум двое игровых суток")
        return lines

    def employee_details(self, player_id: int, employee_id: int) -> str | None:
        with self.db.connect() as conn:
            employee = conn.execute(
                "SELECT * FROM employees WHERE id=? AND player_id=?",
                (employee_id, player_id),
            ).fetchone()
            if not employee:
                return None
            reviews = conn.execute(
                "SELECT COUNT(*) count, COALESCE(AVG(rating),0) avg FROM reviews WHERE player_id=? AND employee_id=?",
                (player_id, employee_id),
            ).fetchone()
        exposure = self._employee_exposure(player_id, employee_id)
        unsecured = max(0, exposure - int(employee["deposit"]))
        dispute_rate = employee["disputes"] / employee["jobs_done"] * 100.0 if employee["jobs_done"] else 0.0
        role_title = "Оптовый сотрудник" if employee["role"] == "warehouse" else "Розничный сотрудник"
        role_icon = "🚚" if employee["role"] == "warehouse" else "👤"

        activity = "\n".join(self._activity_details(player_id, employee_id))
        inventory = self._inventory_lines(player_id, employee_id, employee["role"])
        inventory_text = "\n".join(inventory) if inventory else "Нет товара под ответственностью."

        text = (
            f"<b>{role_icon} {employee['alias']} · {role_title}</b>\n\n"
            f"<b>Сейчас</b>\n{activity}\n\n"
            f"<b>Товар</b>\n{inventory_text}\n\n"
            f"<b>Ответственность</b>\n"
            f"Стоимость товара: {exposure:,} ₽\n"
            f"Депозит: <b>{employee['deposit']:,} ₽</b>\n"
            f"Не покрыто: <b>{unsecured:,} ₽</b>\n\n"
            f"<b>Условия</b>\n"
            f"Ставка: {employee['pay_per_job']:,} ₽ / операцию\n"
            f"В депозит: {employee['deposit_contribution_pct']}%\n"
            f"Начислено: {employee['wages_accrued']:,} ₽\n\n"
        )
        if employee["role"] == "courier":
            text += "<b>Продуктивность</b>\n" + "\n".join(self._productivity_lines(player_id, employee_id)) + "\n\n"
        text += (
            f"<b>Статистика</b>\n"
            f"Операций: {employee['jobs_done']}\n"
            f"Диспутов: {employee['disputes']} ({dispute_rate:.1f}%)\n"
            f"Потери: {employee['losses']:,} ₽\n"
            f"Отзывы: {reviews['count']}"
        )
        if reviews["count"]:
            text += f" · ⭐ {float(reviews['avg']):.2f}"
        if unsecured > 0:
            text += "\n\n🔴 Часть товара не покрыта депозитом. Это осознанный дополнительный риск."
        return text