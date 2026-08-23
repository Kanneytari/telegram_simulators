from __future__ import annotations

import json
from datetime import timedelta

from .runtime import NightshiftGameService
from .simulation import iso, utcnow


class FinalGameService(NightshiftGameService):
    """Small final overrides that depend on the player-aware simulation clock."""

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
