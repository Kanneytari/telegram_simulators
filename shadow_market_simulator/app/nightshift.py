from __future__ import annotations

import json
from datetime import timedelta

from .game import ROLE_NAMES
from .runtime import PlayerSimulationEngine, ROLE_MARKET_PAY
from .simulation import iso, parse_dt, utcnow

ROLE_NAMES["warehouse"] = "Оптовый сотрудник"
ROLE_NAMES["courier"] = "Розничный сотрудник"

# Broad product categories keep the setting recognizable without copying real-world
# illegal-market listings or current black-market prices. Ruble values are internal
# game balance values, not sourced market data.
GAME_PRODUCTS = (
    (1, "STIMULANT", "Стимулятор", 6000, 18.0, 0.95),
    (2, "EMPATHOGEN", "Эмпатоген", 8000, 10.0, 1.10),
    (3, "CANNABINOID", "Каннабиноид", 11000, 6.0, 0.90),
)

STARTER_UNIT_COSTS = {
    1: 3000,
    2: 3900,
    3: 5200,
}


class NightshiftSimulationEngine(PlayerSimulationEngine):
    """Final game simulation layer with personal game time and staff-message enrichment."""

    def seed_catalog(self) -> None:
        super().seed_catalog()
        with self.db.connect() as conn:
            for product_id, code, title, base_price, base_demand, complaint_modifier in GAME_PRODUCTS:
                conn.execute(
                    """UPDATE products
                       SET code=?, title=?, base_market_price=?, base_demand=?, complaint_modifier=?
                       WHERE id=?""",
                    (code, title, base_price, base_demand, complaint_modifier, product_id),
                )

    def effective_speed(self, player_id: int) -> float:
        # /speed is absolute relative to standard time: x60 == one game hour per real minute.
        return self.player_multiplier(player_id)

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        with self.db.connect() as conn:
            if created:
                conn.execute(
                    """UPDATE employees
                       SET pay_per_job=?, deposit_contribution_pct=10
                       WHERE player_id=? AND role='courier'""",
                    (ROLE_MARKET_PAY["courier"], player_id),
                )
                for product_id, _, _, base_price, _, _ in GAME_PRODUCTS:
                    prices = {
                        1: int(round(base_price * 1.05 / 100.0) * 100),
                        2: int(round(base_price * 1.95 / 100.0) * 100),
                        5: int(round(base_price * 4.55 / 100.0) * 100),
                    }
                    for pack_size, price in prices.items():
                        conn.execute(
                            """UPDATE listings SET price=?
                               WHERE player_id=? AND product_id=? AND pack_size=?""",
                            (price, player_id, product_id, pack_size),
                        )
                    conn.execute(
                        "UPDATE batches SET unit_cost=? WHERE player_id=? AND product_id=?",
                        (STARTER_UNIT_COSTS[product_id], player_id, product_id),
                    )
            conn.execute(
                "UPDATE settings SET last_payroll_at=COALESCE(last_payroll_at, ?) WHERE player_id=?",
                (iso(utcnow()), player_id),
            )
        return created

    def advance(self, player_id: int, now=None):
        now = now or utcnow()
        with self.db.connect() as conn:
            before = {
                "inbox": conn.execute("SELECT COALESCE(MAX(id),0) FROM inbox WHERE player_id=?", (player_id,)).fetchone()[0],
                "disputes": conn.execute("SELECT COALESCE(MAX(id),0) FROM disputes WHERE player_id=?", (player_id,)).fetchone()[0],
                "offers": conn.execute("SELECT COALESCE(MAX(id),0) FROM supplier_offers WHERE player_id=?", (player_id,)).fetchone()[0],
            }
        result = super().advance(player_id, now)
        self._scale_new_timers(player_id, before, now)
        return result

    def _scale_new_timers(self, player_id: int, before: dict[str, int], now) -> None:
        speed = self.effective_speed(player_id)
        if abs(speed - 1.0) < 0.0001:
            return
        with self.db.connect() as conn:
            self._scale_rows_after_id(conn, "inbox", "expires_at", player_id, before["inbox"], now, speed)
            self._scale_rows_after_id(conn, "disputes", "deadline_at", player_id, before["disputes"], now, speed)
            self._scale_rows_after_id(conn, "supplier_offers", "expires_at", player_id, before["offers"], now, speed)

    @staticmethod
    def _scale_rows_after_id(conn, table: str, column: str, player_id: int, after_id: int, now, speed: float) -> None:
        rows = conn.execute(
            f"SELECT id, {column} FROM {table} WHERE player_id=? AND id>? AND {column} IS NOT NULL",
            (player_id, after_id),
        ).fetchall()
        for row in rows:
            target = parse_dt(row[column])
            remaining = max(0.0, (target - now).total_seconds())
            conn.execute(
                f"UPDATE {table} SET {column}=? WHERE id=?",
                (iso(now + timedelta(seconds=remaining / speed)), row["id"]),
            )

    def rescale_existing_timers(self, player_id: int, old_speed: float, new_speed: float, now=None) -> None:
        """Preserve remaining game-time duration when /speed changes."""
        now = now or utcnow()
        old_speed = max(0.1, float(old_speed))
        new_speed = max(0.1, float(new_speed))
        with self.db.connect() as conn:
            targets = (
                ("inbox", "expires_at", "status='open'"),
                ("disputes", "deadline_at", "status='open'"),
                ("supplier_offers", "expires_at", "status='open'"),
                ("candidates", "expires_at", "status='open'"),
                ("employees", "unavailable_until", "active=1 AND available=0"),
            )
            for table, column, condition in targets:
                rows = conn.execute(
                    f"SELECT id, {column} FROM {table} WHERE player_id=? AND {condition} AND {column} IS NOT NULL",
                    (player_id,),
                ).fetchall()
                for row in rows:
                    target = parse_dt(row[column])
                    remaining_real = max(0.0, (target - now).total_seconds())
                    remaining_game = remaining_real * old_speed
                    conn.execute(
                        f"UPDATE {table} SET {column}=? WHERE id=?",
                        (iso(now + timedelta(seconds=remaining_game / new_speed)), row["id"]),
                    )

    def fast_forward_timers(self, player_id: int, game_hours: float) -> None:
        """Move existing gameplay deadlines forward for the admin /tick helper."""
        speed = self.effective_speed(player_id)
        shift = timedelta(hours=max(0.0, game_hours) / speed)
        with self.db.connect() as conn:
            targets = (
                ("inbox", "expires_at", "status='open'"),
                ("disputes", "deadline_at", "status='open'"),
                ("supplier_offers", "expires_at", "status='open'"),
                ("candidates", "expires_at", "status='open'"),
                ("employees", "unavailable_until", "active=1 AND available=0"),
            )
            for table, column, condition in targets:
                rows = conn.execute(
                    f"SELECT id, {column} FROM {table} WHERE player_id=? AND {condition} AND {column} IS NOT NULL",
                    (player_id,),
                ).fetchall()
                for row in rows:
                    conn.execute(
                        f"UPDATE {table} SET {column}=? WHERE id=?",
                        (iso(parse_dt(row[column]) - shift), row["id"]),
                    )

    def _simulate_management_events(self, conn, player_id: int, sim_hours: float, now) -> int:
        created = super()._simulate_management_events(conn, player_id, sim_hours, now)

        rows = conn.execute(
            """SELECT i.*, e.alias, e.pay_per_job, e.role
               FROM inbox i
               JOIN employees e ON e.id=json_extract(i.payload_json, '$.employee_id')
               WHERE i.player_id=? AND i.status='open' AND i.kind='raise_request'""",
            (player_id,),
        ).fetchall()
        for item in rows:
            payload = json.loads(item["payload_json"] or "{}")
            if payload.get("requested_pay"):
                continue
            current = int(item["pay_per_job"])
            market = ROLE_MARKET_PAY.get(item["role"], 1500)
            target = max(
                current + 100,
                int(round(max(current * self.rng.uniform(1.08, 1.22), market * 0.95) / 50) * 50),
            )
            floor = max(current, int(round(target * self.rng.uniform(0.88, 0.97) / 50) * 50))
            payload.update(
                {
                    "requested_pay": target,
                    "offer_pay": current,
                    "floor_pay": floor,
                    "round": 0,
                }
            )
            body = (
                f"{item['alias']} просит пересмотреть условия.\n\n"
                f"Текущая ставка: {current:,} ₽ / заказ\n"
                f"Запрос: <b>{target:,} ₽ / заказ</b>\n\n"
                "Можно согласиться, отказать или предложить встречную ставку."
            )
            conn.execute(
                "UPDATE inbox SET body=?, payload_json=? WHERE id=?",
                (body, json.dumps(payload, ensure_ascii=False), item["id"]),
            )

        # Reformat older one-line event generators into the same compact block layout.
        compact_items = conn.execute(
            """SELECT * FROM inbox
               WHERE player_id=? AND status='open'
                 AND kind IN ('leave_request','advance_request','discount_request')""",
            (player_id,),
        ).fetchall()
        for item in compact_items:
            if "\n\n" in item["body"]:
                continue
            payload = json.loads(item["payload_json"] or "{}")
            if item["kind"] == "leave_request":
                employee = conn.execute(
                    "SELECT alias FROM employees WHERE id=? AND player_id=?",
                    (payload.get("employee_id"), player_id),
                ).fetchone()
                if employee:
                    body = (
                        f"{employee['alias']} просит временную паузу.\n\n"
                        "Срок при согласовании: 6 игровых часов\n"
                        "Причина: личные обстоятельства"
                    )
                    conn.execute("UPDATE inbox SET body=? WHERE id=?", (body, item["id"]))
            elif item["kind"] == "advance_request":
                employee = conn.execute(
                    "SELECT alias, deposit FROM employees WHERE id=? AND player_id=?",
                    (payload.get("employee_id"), player_id),
                ).fetchone()
                if employee:
                    body = (
                        f"{employee['alias']} просит вернуть часть депозита.\n\n"
                        f"Сумма: <b>{int(payload.get('amount', 0)):,} ₽</b>\n"
                        f"Текущий депозит: {int(employee['deposit']):,} ₽"
                    )
                    conn.execute("UPDATE inbox SET body=? WHERE id=?", (body, item["id"]))
            else:
                client = conn.execute(
                    "SELECT alias FROM clients WHERE id=? AND player_id=?",
                    (payload.get("client_id"), player_id),
                ).fetchone()
                if client:
                    body = (
                        f"{client['alias']} просит небольшую скидку.\n\n"
                        f"Размер: <b>{int(payload.get('percent', 0))}%</b>\n"
                        "Причина: не хватает суммы после изменения курса."
                    )
                    conn.execute("UPDATE inbox SET body=? WHERE id=?", (body, item["id"]))

        # Exit messages are staff messages too; attach the employee id so the UI can open their profile.
        exits = conn.execute(
            """SELECT * FROM inbox
               WHERE player_id=? AND status='open' AND kind='employee_exit'""",
            (player_id,),
        ).fetchall()
        employees = conn.execute(
            "SELECT id, alias FROM employees WHERE player_id=? ORDER BY id DESC",
            (player_id,),
        ).fetchall()
        for item in exits:
            payload = json.loads(item["payload_json"] or "{}")
            if payload.get("employee_id"):
                continue
            for employee in employees:
                if employee["alias"] and employee["alias"] in item["body"]:
                    payload["employee_id"] = employee["id"]
                    conn.execute(
                        "UPDATE inbox SET payload_json=? WHERE id=?",
                        (json.dumps(payload, ensure_ascii=False), item["id"]),
                    )
                    break
        return created
