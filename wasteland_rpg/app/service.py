from __future__ import annotations

import sqlite3

from .content import ENEMIES, SECTORS
from .game import GameError
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
                result["progress_notice"] = (
                    f"Сектор пройден\nОткрыта новая локация: {next_sector['name']}"
                )
            else:
                result["progress_notice"] = "Сектор пройден"
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

    def _change_item(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        item_id: str,
        qty: int,
        *,
        secured: int,
    ) -> None:
        """Change inventory quantity without ever inserting a negative CHECK value."""
        qty = int(qty)
        if qty > 0:
            conn.execute(
                "INSERT INTO inventory (telegram_id, item_id, secured, qty) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (telegram_id, item_id, secured) DO UPDATE SET qty = qty + excluded.qty",
                (telegram_id, item_id, secured, qty),
            )
        elif qty < 0:
            conn.execute(
                "UPDATE inventory SET qty = MAX(0, qty + ?) "
                "WHERE telegram_id = ? AND item_id = ? AND secured = ?",
                (qty, telegram_id, item_id, secured),
            )
        conn.execute(
            "DELETE FROM inventory WHERE telegram_id = ? AND item_id = ? AND secured = ? AND qty <= 0",
            (telegram_id, item_id, secured),
        )

    def _change_cargo(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        item_id: str,
        qty: int,
    ) -> None:
        """Change cargo quantity without violating the non-negative CHECK constraint."""
        qty = int(qty)
        if qty > 0:
            conn.execute(
                "INSERT INTO cargo (telegram_id, item_id, qty) VALUES (?, ?, ?) "
                "ON CONFLICT (telegram_id, item_id) DO UPDATE SET qty = qty + excluded.qty",
                (telegram_id, item_id, qty),
            )
        elif qty < 0:
            conn.execute(
                "UPDATE cargo SET qty = MAX(0, qty + ?) WHERE telegram_id = ? AND item_id = ?",
                (qty, telegram_id, item_id),
            )
        conn.execute(
            "DELETE FROM cargo WHERE telegram_id = ? AND item_id = ? AND qty <= 0",
            (telegram_id, item_id),
        )

    def combat_action(self, telegram_id: int, action: str) -> dict:
        if action != "wait":
            return super().combat_action(telegram_id, action)

        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "combat" or not player["enemy_id"]:
                raise GameError("Бой уже закончен.")

            combat = conn.execute(
                "SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if not combat:
                raise GameError("Состояние боя потеряно.")
            if int(player["ammo"]) > 0:
                raise GameError("Ждать можно только когда закончились патроны.")
            if int(combat["distance"]) <= 1:
                raise GameError("Противник уже вплотную — используй ближний бой.")

            lines: list[str] = []
            if int(combat["bleeding"]) > 0:
                bleed_damage = int(combat["bleeding"])
                hp = int(player["hp"]) - bleed_damage
                lines.append(f"🩸 Кровотечение: -{bleed_damage} HP.")
                if hp <= 0:
                    lines.append(self._kill(conn, telegram_id))
                    return {"text": "\n".join(lines), "dead": True}
                conn.execute(
                    "UPDATE players SET hp = ? WHERE telegram_id = ?", (hp, telegram_id)
                )

            enemy = ENEMIES[player["enemy_id"]]
            new_distance = max(1, int(combat["distance"]) - 1)
            conn.execute(
                "UPDATE combat_state SET distance = ?, cover = 0 WHERE telegram_id = ?",
                (new_distance, telegram_id),
            )
            lines.append(f"Ты выжидаешь. {enemy['name']} сокращает дистанцию.")
            if new_distance == 1:
                lines.append("Противник подошёл вплотную — теперь доступен ближний бой.")
            return {"text": "\n".join(lines)}
