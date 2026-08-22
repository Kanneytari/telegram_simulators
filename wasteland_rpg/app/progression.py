from __future__ import annotations

import sqlite3

from .content import (
    ARMORS,
    ATTRIBUTES,
    MAX_ATTRIBUTE,
    SECTORS,
    WEAPONS,
    XP_PER_LEVEL,
)
from .game import GameError, GameService


class ProgressionGameService(GameService):
    """Player-facing level/attribute layer over the compact base game engine."""

    def ensure_player(self, telegram_id: int, username: str | None = None) -> None:
        super().ensure_player(telegram_id, username)
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            conn.execute(
                """
                UPDATE players
                SET combat = agility, scavenging = perception, survival = endurance
                WHERE telegram_id = ?
                """,
                (telegram_id,),
            )
            if player["state"] == "base":
                conn.execute(
                    "UPDATE players SET hp = ? WHERE telegram_id = ?",
                    (self.max_hp(player), telegram_id),
                )

    def level(self, player: sqlite3.Row | dict) -> int:
        return int(player["xp"]) // XP_PER_LEVEL + 1

    def max_hp(self, player: sqlite3.Row | dict) -> int:
        return 20 + self.level(player) * 20

    def attribute_points(self, player: sqlite3.Row | dict) -> int:
        earned = self.level(player) - 1
        spent = sum(int(player[key]) - 1 for key in ATTRIBUTES)
        return max(0, earned - spent)

    def carry_capacity(self, player: sqlite3.Row | dict) -> int:
        return 8 + int(player["strength"]) * 3

    def sector_unlocked(self, player: sqlite3.Row | dict, sector_id: str) -> bool:
        sector = SECTORS[sector_id]
        return (
            int(player["successful_runs"]) >= sector["runs"]
            and self.level(player) >= sector["level"]
        )

    def missing_requirements(
        self,
        player: sqlite3.Row | dict,
        item: dict,
    ) -> dict[str, int]:
        return {
            key: need
            for key, need in item.get("requirements", {}).items()
            if int(player[key]) < int(need)
        }

    def upgrade_attribute(self, telegram_id: int, attribute: str) -> str:
        if attribute not in ATTRIBUTES:
            raise GameError("Неизвестная характеристика.")
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Распределять характеристики можно только в Приюте.")
            if self.attribute_points(player) <= 0:
                raise GameError("Свободных очков характеристик нет.")
            if int(player[attribute]) >= MAX_ATTRIBUTE:
                raise GameError("Характеристика уже на максимуме.")
            conn.execute(
                f"UPDATE players SET {attribute} = {attribute} + 1 WHERE telegram_id = ?",
                (telegram_id,),
            )
            conn.execute(
                """
                UPDATE players
                SET combat = agility, scavenging = perception, survival = endurance
                WHERE telegram_id = ?
                """,
                (telegram_id,),
            )
            value = int(player[attribute]) + 1
        return f"{ATTRIBUTES[attribute]['name']} повышена до {value}."

    # Existing Telegram handler uses the old callback name; keep it as a thin alias.
    def upgrade_skill(self, telegram_id: int, skill: str) -> str:
        return self.upgrade_attribute(telegram_id, skill)

    def buy(self, telegram_id: int, product: str) -> str:
        catalog = WEAPONS if product in WEAPONS else ARMORS if product in ARMORS else None
        if catalog:
            with self.db.connect() as conn:
                player = self._player(conn, telegram_id)
                missing = self.missing_requirements(player, catalog[product])
                if missing:
                    text = ", ".join(
                        f"{ATTRIBUTES[key]['name']} {need}"
                        for key, need in missing.items()
                    )
                    raise GameError(f"Не хватает характеристик: {text}.")
        return super().buy(telegram_id, product)

    def _add_xp(self, conn: sqlite3.Connection, telegram_id: int, amount: int) -> None:
        if amount <= 0:
            return
        player = self._player(conn, telegram_id)
        old_level = self.level(player)
        super()._add_xp(conn, telegram_id, amount)
        updated = self._player(conn, telegram_id)
        new_level = self.level(updated)
        if new_level > old_level:
            hp_gain = (new_level - old_level) * 20
            conn.execute(
                "UPDATE players SET hp = MIN(?, hp + ?) WHERE telegram_id = ?",
                (self.max_hp(updated), hp_gain, telegram_id),
            )
