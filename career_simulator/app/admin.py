from __future__ import annotations

from collections.abc import Iterable

from .db import Database
from .game import GameError, GameService


class AdminError(GameError):
    pass


class AdminService:
    def __init__(
        self,
        db: Database,
        game: GameService,
        admin_ids: Iterable[int] = (),
    ) -> None:
        self.db = db
        self.game = game
        self.admin_ids = frozenset(admin_ids)
        self._init_schema()

    def _init_schema(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_settings (
                    telegram_id INTEGER PRIMARY KEY,
                    fast_mode INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_ids

    def _require_admin(self, telegram_id: int) -> None:
        if not self.is_admin(telegram_id):
            raise AdminError("Команда доступна только администратору.")

    def is_fast_mode(self, telegram_id: int) -> bool:
        if not self.is_admin(telegram_id):
            return False
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT fast_mode FROM admin_settings WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
        return bool(row["fast_mode"]) if row else False

    def set_fast_mode(self, telegram_id: int, enabled: bool) -> bool:
        self._require_admin(telegram_id)
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO admin_settings (telegram_id, fast_mode)
                VALUES (?, ?)
                ON CONFLICT(telegram_id)
                DO UPDATE SET fast_mode = excluded.fast_mode
                """,
                (telegram_id, int(enabled)),
            )
        return enabled

    def toggle_fast_mode(self, telegram_id: int) -> bool:
        return self.set_fast_mode(telegram_id, not self.is_fast_mode(telegram_id))

    def reset_player(self, telegram_id: int) -> bool:
        self._require_admin(telegram_id)
        with self.db.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM players WHERE telegram_id = ?",
                (telegram_id,),
            )
        return cursor.rowcount > 0

    def advance_day(self, telegram_id: int) -> str:
        self._require_admin(telegram_id)
        if not self.is_fast_mode(telegram_id):
            raise AdminError("Сначала включи быстрый режим.")

        player = self.game.get_player(telegram_id)
        if player["actions_left"] > 0:
            raise AdminError(
                f"Сначала потрать дневные действия. Осталось: {player['actions_left']}."
            )

        current_key = player["day_key"]
        archive_key = f"fast:{player['career_day']}"
        forced_key = f"__fast_rollover__:{player['career_day']}"

        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for table in ("daily_events", "purchases", "inbox_items", "focus_runs"):
                conn.execute(
                    f"UPDATE {table} SET day_key = ? WHERE player_id = ? AND day_key = ?",
                    (archive_key, telegram_id, current_key),
                )
            conn.execute(
                "UPDATE players SET day_key = ? WHERE telegram_id = ?",
                (forced_key, telegram_id),
            )

        self.game._rollover_if_needed(telegram_id)
        after = self.game.get_player(telegram_id, rollover=False)
        return (
            f"Начался карьерный день {after['career_day']}. "
            f"Доступно {after['actions_left']} действий."
        )
