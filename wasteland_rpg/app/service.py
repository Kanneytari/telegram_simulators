from __future__ import annotations

from .content import SECTORS
from .gameplay import GameService as GameplayService
from .progression import level_from_xp, progress_from_xp, xp_required_for_next
from .sector_progression import SECTOR_NEXT, SECTOR_PREVIOUS


class GameService(GameplayService):
    """Runtime game service with current progression and sector mastery rules."""

    def level(self, player) -> int:
        return level_from_xp(int(player["xp"]))

    def xp_progress(self, player) -> tuple[int, int]:
        return progress_from_xp(int(player["xp"]))

    def xp_needed_for_next_level(self, player) -> int:
        return xp_required_for_next(self.level(player))

    def sector_max_threat(self, telegram_id: int, sector_id: str) -> int:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT max_threat FROM sector_progress WHERE telegram_id = ? AND sector_id = ?",
                (telegram_id, sector_id),
            ).fetchone()
        return int(row["max_threat"]) if row else 0

    def sector_mastered(self, telegram_id: int, sector_id: str) -> bool:
        return self.sector_max_threat(telegram_id, sector_id) >= 100

    def sector_unlocked(self, player, sector_id: str) -> bool:
        if sector_id not in SECTORS:
            return False
        sector = SECTORS[sector_id]
        telegram_id = int(player["telegram_id"])
        if self.location_id(telegram_id) != sector["hub"]:
            return False
        previous = SECTOR_PREVIOUS.get(sector_id)
        return previous is None or self.sector_mastered(telegram_id, previous)

    def sector_unlock_requirement(self, sector_id: str) -> str | None:
        previous = SECTOR_PREVIOUS.get(sector_id)
        if previous is None:
            return None
        return SECTORS[previous]["name"]

    def explore(self, telegram_id: int) -> dict:
        before = self.get_player(telegram_id)
        sector_id = before.get("sector_id")
        result = super().explore(telegram_id)
        if not sector_id:
            return result

        player = self.get_player(telegram_id)
        threat = int(player["threat"])
        newly_mastered = self._record_sector_progress(telegram_id, str(sector_id), threat)
        if newly_mastered:
            next_sector_id = SECTOR_NEXT.get(str(sector_id))
            if next_sector_id:
                next_sector = SECTORS[next_sector_id]
                result["text"] += (
                    f"\n\n☣️ Угроза достигла 100/100. Сектор освоен до предела. "
                    f"Открыта новая вылазка: {next_sector['icon']} {next_sector['name']}."
                )
            else:
                result["text"] += "\n\n☣️ Угроза достигла 100/100. Сектор освоен до предела."
        return result

    def _record_sector_progress(self, telegram_id: int, sector_id: str, threat: int) -> bool:
        threat = max(0, min(100, int(threat)))
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT max_threat FROM sector_progress WHERE telegram_id = ? AND sector_id = ?",
                (telegram_id, sector_id),
            ).fetchone()
            old_max = int(row["max_threat"]) if row else 0
            conn.execute(
                "INSERT INTO sector_progress (telegram_id, sector_id, max_threat) VALUES (?, ?, ?) "
                "ON CONFLICT (telegram_id, sector_id) DO UPDATE SET "
                "max_threat = MAX(max_threat, excluded.max_threat)",
                (telegram_id, sector_id, threat),
            )
        return old_max < 100 <= threat
