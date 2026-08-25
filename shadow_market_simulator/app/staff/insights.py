from __future__ import annotations

from .simulation import parse_dt, utcnow
from .workflow import WorkflowGameService, WorkflowSimulationEngine


class StaffInsightSimulationEngine(WorkflowSimulationEngine):
    """Final simulation layer for starter safety and historical staff throughput."""

    def _seed_retail_positions(self, player_id: int) -> None:
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
                       SET title='Первая смена',
                           body='Склад пуст. Начни с первой закупки в разделе Товар.'
                       WHERE player_id=? AND kind='tutorial' AND status='open'""",
                    (player_id,),
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
        real_hours = max(
            0.0,
            (now - parse_dt(shop["last_simulated_at"])).total_seconds() / 3600.0,
        )
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
            real_hours = max(
                0.0,
                (now - parse_dt(shop["last_simulated_at"])).total_seconds() / 3600.0,
            )
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


class StaffInsightGameService(WorkflowGameService):
    """Employee profile with explicit activity, inventory and throughput history."""

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
                """SELECT t.* FROM employee_tasks t
                   WHERE t.player_id=? AND t.employee_id=? AND t.status='active'
                   ORDER BY t.completes_at LIMIT 1""",
                (player_id, employee_id),
            ).fetchone()
            if task:
                remaining_real = max(
                    0.0,
                    (parse_dt(task["completes_at"]) - now).total_seconds() / 3600.0,
                )
                remaining_game = remaining_real * self.simulation.effective_speed(player_id)
                eta = "менее 1 ч" if remaining_game < 1 else f"~{remaining_game:.1f} ч"
                labels = {
                    "receive_batch": "получает партию",
                    "handoff": "готовит мастер-клад",
                    "place_stashes": "раскидывает клады",
                }
                return f"{labels.get(task['kind'], task['kind'])} · {eta}"
            if not employee["available"]:
                if employee["unavailable_until"]:
                    remaining_real = max(
                        0.0,
                        (
                            parse_dt(employee["unavailable_until"]) - now
                        ).total_seconds()
                        / 3600.0,
                    )
                    remaining_game = remaining_real * self.simulation.effective_speed(
                        player_id
                    )
                    eta = (
                        "менее 1 ч" if remaining_game < 1 else f"~{remaining_game:.1f} ч"
                    )
                    return (
                        f"отдыхает · {eta}"
                        if employee["role"] == "courier"
                        else f"недоступен · {eta}"
                    )
                return "временно недоступен"
            if employee["role"] == "courier":
                waiting = int(
                    conn.execute(
                        """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                           WHERE player_id=? AND retail_employee_id=? AND status='waiting'""",
                        (player_id, employee_id),
                    ).fetchone()[0]
                )
                if waiting:
                    return f"ожидает товар · {waiting} ед."
                preparing = int(
                    conn.execute(
                        """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                           WHERE player_id=? AND retail_employee_id=? AND status='preparing'""",
                        (player_id, employee_id),
                    ).fetchone()[0]
                )
                if preparing:
                    return f"раскидывает клады · {preparing} ед."
                published = int(
                    conn.execute(
                        """SELECT COALESCE(SUM(position_count*pack_size),0) FROM retail_positions
                           WHERE player_id=? AND employee_id=? AND position_count>0""",
                        (player_id, employee_id),
                    ).fetchone()[0]
                )
                if published:
                    return f"ждёт продажи · {published} ед."
            else:
                ready = int(
                    conn.execute(
                        """SELECT COALESCE(SUM(remaining),0) FROM batches
                           WHERE player_id=? AND responsible_employee_id=?
                             AND status='warehouse' AND remaining>0""",
                        (player_id, employee_id),
                    ).fetchone()[0]
                )
                if ready:
                    return f"ждёт распределения · {ready} ед."
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
                "handoff": "Подготовка мастер-клада",
                "place_stashes": "Подготовка товара к витрине",
            }
            remaining_real_min = max(
                0.0,
                (parse_dt(task["completes_at"]) - now).total_seconds() / 60.0,
            )
            remaining_game_h = (
                remaining_real_min
                / 60.0
                * self.simulation.effective_speed(player_id)
            )
            lines.append(f"Задача: {labels.get(task['kind'], task['kind'])}")
            if task["product_title"]:
                lines.append(
                    f"Товар: {task['product_title']} · {int(task['quantity'])} ед."
                )
            real_eta = (
                "менее 1 мин"
                if remaining_real_min < 1
                else f"~{remaining_real_min:.0f} мин"
            )
            game_eta = (
                "менее 1 ч" if remaining_game_h < 1 else f"~{remaining_game_h:.1f} ч"
            )
            lines.append(f"Осталось: {game_eta} игровых · {real_eta} реальных")
        return lines

    def _inventory_lines(
        self, player_id: int, employee_id: int, role: str
    ) -> list[str]:
        with self.db.connect() as conn:
            products = conn.execute(
                "SELECT id, title FROM products WHERE active=1 ORDER BY id"
            ).fetchall()
            lines: list[str] = []
            for product in products:
                if role == "courier":
                    waiting = int(
                        conn.execute(
                            """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                               WHERE player_id=? AND retail_employee_id=? AND product_id=? AND status='waiting'""",
                            (player_id, employee_id, product["id"]),
                        ).fetchone()[0]
                    )
                    preparing = int(
                        conn.execute(
                            """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                               WHERE player_id=? AND retail_employee_id=? AND product_id=? AND status='preparing'""",
                            (player_id, employee_id, product["id"]),
                        ).fetchone()[0]
                    )
                    published = conn.execute(
                        """SELECT COALESCE(SUM(position_count*pack_size),0) units,
                                  COALESCE(SUM(position_count),0) positions
                           FROM retail_positions
                           WHERE player_id=? AND employee_id=? AND product_id=? AND position_count>0""",
                        (player_id, employee_id, product["id"]),
                    ).fetchone()
                    published_units = int(published["units"] or 0)
                    if waiting or preparing or published_units:
                        parts = []
                        if waiting:
                            parts.append(f"ожидает {waiting} ед.")
                        if preparing:
                            parts.append(f"на руках {preparing} ед.")
                        if published_units:
                            parts.append(f"витрина {published_units} ед.")
                        lines.append(f"{product['title']}: " + " · ".join(parts))
                else:
                    receiving = int(
                        conn.execute(
                            """SELECT COALESCE(SUM(remaining),0) FROM batches
                               WHERE player_id=? AND responsible_employee_id=? AND product_id=?
                                 AND status='receiving'""",
                            (player_id, employee_id, product["id"]),
                        ).fetchone()[0]
                    )
                    ready = int(
                        conn.execute(
                            """SELECT COALESCE(SUM(remaining),0) FROM batches
                               WHERE player_id=? AND responsible_employee_id=? AND product_id=?
                                 AND status='warehouse'""",
                            (player_id, employee_id, product["id"]),
                        ).fetchone()[0]
                    )
                    handoff = int(
                        conn.execute(
                            """SELECT COALESCE(SUM(quantity),0) FROM retail_allocations
                               WHERE player_id=? AND wholesale_employee_id=? AND product_id=? AND status='waiting'""",
                            (player_id, employee_id, product["id"]),
                        ).fetchone()[0]
                    )
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
            last = int(
                conn.execute(
                    """SELECT COALESCE(SUM(positions),0) FROM publication_events
                       WHERE player_id=? AND employee_id=? AND game_hour>?""",
                    (player_id, employee_id, current_hour - 24.0),
                ).fetchone()[0]
            )
            previous = int(
                conn.execute(
                    """SELECT COALESCE(SUM(positions),0) FROM publication_events
                       WHERE player_id=? AND employee_id=? AND game_hour>? AND game_hour<=?""",
                    (player_id, employee_id, current_hour - 48.0, current_hour - 24.0),
                ).fetchone()[0]
            )
        if not total or int(total["events"] or 0) == 0:
            return [
                "Средняя: пока нет данных",
                "Динамика: появится после первых публикаций",
            ]
        first_hour = float(total["first_hour"] or current_hour)
        active_days = max(1.0, (current_hour - first_hour) / 24.0)
        average = int(total["positions"] or 0) / active_days
        lines = [
            f"Средняя: <b>{average:.1f} фасовок / игровые сутки</b>",
            f"Последние 24 игровых ч: {last} фасовок",
        ]
        if previous > 0:
            delta = (last / previous - 1.0) * 100.0
            arrow = "↑" if delta > 2 else "↓" if delta < -2 else "→"
            lines.append(f"К предыдущим суткам: {arrow} {delta:+.0f}%")
        elif current_hour >= 48.0:
            lines.append("К предыдущим суткам: нет базы для сравнения")
        else:
            lines.append("Динамика: нужно минимум двое игровых суток")
        return lines
