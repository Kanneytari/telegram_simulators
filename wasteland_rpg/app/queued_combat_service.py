from __future__ import annotations

import sqlite3
import time

from .combat_rules import PLAYER_ACTION_LABELS, PLAYER_ACTION_SECONDS
from .content import WEAPONS
from .game import GameError
from .service import GameService as RealtimeGameService


class GameService(RealtimeGameService):
    """Realtime combat service with one replaceable queued player action."""

    def combat_queued_action(self, telegram_id: int) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT action FROM combat_queue WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
        return str(row["action"]) if row else None

    def combat_queue_resources(self, telegram_id: int) -> tuple[int, int]:
        """Resources still available for the next action after the current one resolves."""
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            timeline = conn.execute(
                "SELECT player_action FROM combat_timeline WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            current = str(timeline["player_action"] or "") if timeline else ""
            ammo = int(player["ammo"]) - self._ammo_cost(current)
            medkits = int(player["medkits"]) - (1 if current == "medkit" else 0)
        return max(0, ammo), max(0, medkits)

    @staticmethod
    def _ammo_cost(action: str) -> int:
        if action in {"shoot", "aimed_shot"}:
            return 1
        if action == "burst":
            return 3
        return 0

    def _validate_next_action_conn(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        action: str,
        now: float,
        *,
        reserve_current: bool,
    ) -> None:
        if action in {"wait", "aim", "approach"}:
            raise GameError("Это действие больше не используется в новой системе боя.")
        if action not in PLAYER_ACTION_SECONDS:
            raise GameError("Неизвестное боевое действие.")

        player = self._player(conn, telegram_id)
        if player["state"] != "combat" or not player["enemy_id"]:
            raise GameError("Бой уже закончен.")

        timeline = conn.execute(
            "SELECT * FROM combat_timeline WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        combat = conn.execute(
            "SELECT * FROM combat_state WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if not timeline or not combat:
            raise GameError("Состояние боя потеряно.")

        current = str(timeline["player_action"] or "") if reserve_current else ""
        ammo = int(player["ammo"]) - self._ammo_cost(current)
        medkits = int(player["medkits"]) - (1 if current == "medkit" else 0)
        weapon = WEAPONS[player["weapon_id"]]

        if action in {"shoot", "aimed_shot"} and ammo < 1:
            raise GameError("После текущего действия патронов не останется.")
        if action == "burst":
            if "burst" not in weapon.get("modes", ()):
                raise GameError("Это оружие не умеет стрелять очередью.")
            if ammo < 3:
                raise GameError("После текущего действия не хватит патронов для очереди.")
        if action == "medkit" and medkits < 1:
            raise GameError("После текущего действия аптечек не останется.")
        if action == "melee" and int(combat["distance"]) > 1:
            raise GameError("Противник ещё не подошёл вплотную.")

        opportunity = str(timeline["opportunity_kind"] or "")
        opportunity_valid = float(timeline["opportunity_until"]) > now
        if action == "cover" and (opportunity != "cover" or not opportunity_valid):
            raise GameError("Возможность занять укрытие уже исчезла.")
        if action == "stim" and (opportunity != "stim" or not opportunity_valid):
            raise GameError("Стимулятор уже недоступен.")

    def combat_action(
        self,
        telegram_id: int,
        action: str,
        *,
        now: float | None = None,
    ) -> dict:
        now = time.time() if now is None else float(now)
        schedule_now = False

        with self.db.connect() as conn:
            self._ensure_combat_timeline_conn(conn, telegram_id)
            pre_result = self._tick_combat_conn(conn, telegram_id, now)
            player = self._player(conn, telegram_id)
            if player["state"] != "combat" or not player["enemy_id"]:
                return pre_result or {"text": "Бой уже завершён.", "finished": True}

            timeline = conn.execute(
                "SELECT * FROM combat_timeline WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            if not timeline:
                raise GameError("Состояние боя потеряно.")

            if not timeline["player_action"]:
                conn.execute("DELETE FROM combat_queue WHERE telegram_id = ?", (telegram_id,))
                schedule_now = True
            else:
                self._validate_next_action_conn(
                    conn,
                    telegram_id,
                    action,
                    now,
                    reserve_current=True,
                )
                previous = conn.execute(
                    "SELECT action FROM combat_queue WHERE telegram_id = ?",
                    (telegram_id,),
                ).fetchone()
                conn.execute(
                    "INSERT INTO combat_queue (telegram_id, action, queued_at) VALUES (?, ?, ?) "
                    "ON CONFLICT (telegram_id) DO UPDATE SET action = excluded.action, queued_at = excluded.queued_at",
                    (telegram_id, action, now),
                )
                label = PLAYER_ACTION_LABELS[action]
                return {
                    "text": f"Следующее действие: {label}.",
                    "queued": True,
                    "replaced": bool(previous),
                }

        if schedule_now:
            return super().combat_action(telegram_id, action, now=now)
        raise GameError("Не удалось поставить действие в очередь.")

    def _execute_player_action_conn(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        event_at: float,
    ) -> dict:
        result = super()._execute_player_action_conn(conn, telegram_id, event_at)

        player = self._player(conn, telegram_id)
        if result.get("finished") or player["state"] != "combat":
            return result

        queued = conn.execute(
            "SELECT action FROM combat_queue WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        if not queued:
            return result

        action = str(queued["action"])
        conn.execute("DELETE FROM combat_queue WHERE telegram_id = ?", (telegram_id,))

        try:
            self._validate_next_action_conn(
                conn,
                telegram_id,
                action,
                event_at,
                reserve_current=False,
            )
        except GameError as exc:
            self._log_conn(
                conn,
                telegram_id,
                f"⏭ {PLAYER_ACTION_LABELS.get(action, action)} отменено: {exc}",
            )
            return result

        if action in {"cover", "stim"}:
            conn.execute(
                "UPDATE combat_timeline SET opportunity_kind = NULL, opportunity_until = 0 "
                "WHERE telegram_id = ?",
                (telegram_id,),
            )

        conn.execute(
            "UPDATE combat_timeline SET player_action = ?, player_action_due = ? "
            "WHERE telegram_id = ?",
            (action, event_at + PLAYER_ACTION_SECONDS[action], telegram_id),
        )
        return result

    def _cleanup_combat_runtime_conn(self, conn: sqlite3.Connection, telegram_id: int) -> None:
        super()._cleanup_combat_runtime_conn(conn, telegram_id)
        conn.execute("DELETE FROM combat_queue WHERE telegram_id = ?", (telegram_id,))

    def _start_combat(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        enemy_id: str,
        *,
        return_state: str,
    ) -> None:
        super()._start_combat(conn, telegram_id, enemy_id, return_state=return_state)
        conn.execute("DELETE FROM combat_queue WHERE telegram_id = ?", (telegram_id,))
