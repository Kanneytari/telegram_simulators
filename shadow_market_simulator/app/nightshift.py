from __future__ import annotations

import json

from .runtime import PlayerSimulationEngine, ROLE_MARKET_PAY
from .simulation import iso, utcnow


class NightshiftSimulationEngine(PlayerSimulationEngine):
    """Final game simulation layer with current wage scale and staff-message enrichment."""

    def ensure_player(self, player_id: int, username: str | None) -> bool:
        created = super().ensure_player(player_id, username)
        with self.db.connect() as conn:
            if created:
                # Both starter employees are retail staff. The market reference is 1,500 ₽ per completed order.
                conn.execute(
                    """UPDATE employees
                       SET pay_per_job=?, deposit_contribution_pct=10
                       WHERE player_id=? AND role='courier'""",
                    (ROLE_MARKET_PAY["courier"], player_id),
                )
            conn.execute(
                "UPDATE settings SET last_payroll_at=COALESCE(last_payroll_at, ?) WHERE player_id=?",
                (iso(utcnow()), player_id),
            )
        return created

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
        return created
