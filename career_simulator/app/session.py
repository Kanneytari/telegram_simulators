from __future__ import annotations

import random
from typing import Any

from .game import GameError, GameService
from .session_content import INBOX_CARDS, INBOX_PER_DAY


class SessionService:
    """Short daily office situations layered on top of the core career loop."""

    def __init__(self, game: GameService) -> None:
        self.game = game
        self.db = game.db
        self._init_schema()

    def _init_schema(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inbox_items (
                    player_id INTEGER NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
                    day_key TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    card_id TEXT NOT NULL,
                    choice_index INTEGER,
                    PRIMARY KEY(player_id, day_key, slot)
                )
                """
            )

    def inbox_progress(self, telegram_id: int) -> dict[str, int]:
        player = self.game.get_player(telegram_id)
        self._ensure_inbox(player)
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN choice_index IS NOT NULL THEN 1 ELSE 0 END) AS resolved
                FROM inbox_items
                WHERE player_id = ? AND day_key = ?
                """,
                (telegram_id, player["day_key"]),
            ).fetchone()
        total = int(row["total"] or 0)
        resolved = int(row["resolved"] or 0)
        return {"total": total, "resolved": resolved, "unread": total - resolved}

    def next_inbox_item(self, telegram_id: int) -> dict[str, Any] | None:
        player = self.game.get_player(telegram_id)
        self._ensure_inbox(player)
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT slot, card_id
                FROM inbox_items
                WHERE player_id = ? AND day_key = ? AND choice_index IS NULL
                ORDER BY slot
                LIMIT 1
                """,
                (telegram_id, player["day_key"]),
            ).fetchone()
        if not row:
            return None
        card = self._inbox_card(row["card_id"])
        progress = self.inbox_progress(telegram_id)
        return {**card, "slot": row["slot"], **progress}

    def resolve_inbox(self, telegram_id: int, slot: int, choice_index: int) -> str:
        if choice_index not in {0, 1}:
            raise GameError("Некорректный выбор.")
        player = self.game.get_player(telegram_id)
        self._ensure_inbox(player)

        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM inbox_items
                WHERE player_id = ? AND day_key = ? AND slot = ?
                """,
                (telegram_id, player["day_key"], slot),
            ).fetchone()
            if not row:
                raise GameError("Это сообщение больше неактуально.")
            if row["choice_index"] is not None:
                raise GameError("Это сообщение уже разобрано.")

            card = self._inbox_card(row["card_id"])
            _, effects, result = card["choices"][choice_index]
            self.game._apply_changes(conn, telegram_id, effects)
            conn.execute(
                """
                UPDATE inbox_items SET choice_index = ?
                WHERE player_id = ? AND day_key = ? AND slot = ?
                """,
                (choice_index, telegram_id, player["day_key"], slot),
            )
            self.game._journal(
                conn,
                telegram_id,
                player["career_day"],
                "inbox",
                f"{card['title']}: {result}",
            )
        return result

    def _ensure_inbox(self, player: dict[str, Any]) -> None:
        with self.db.connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM inbox_items WHERE player_id = ? AND day_key = ? LIMIT 1",
                (player["telegram_id"], player["day_key"]),
            ).fetchone()
            if exists:
                return

            seed = f"{player['telegram_id']}:{player['career_day']}:{player['day_key']}"
            rng = random.Random(seed)
            cards = rng.sample(INBOX_CARDS, k=min(INBOX_PER_DAY, len(INBOX_CARDS)))
            conn.executemany(
                """
                INSERT INTO inbox_items (player_id, day_key, slot, card_id)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (player["telegram_id"], player["day_key"], slot, card["id"])
                    for slot, card in enumerate(cards, start=1)
                ],
            )

    @staticmethod
    def _inbox_card(card_id: str) -> dict[str, Any]:
        card = next((card for card in INBOX_CARDS if card["id"] == card_id), None)
        if not card:
            raise GameError("Неизвестное сообщение во входящих.")
        return card
