from __future__ import annotations

import random
from typing import Any

from .game import GameError, GameService
from .session_content import FOCUS_RUNS_PER_DAY, FOCUS_STEPS, INBOX_CARDS, INBOX_PER_DAY


class SessionService:
    """Active-session mechanics layered on top of the core career loop."""

    def __init__(self, game: GameService, rng: random.Random | None = None) -> None:
        self.game = game
        self.db = game.db
        self.rng = rng or random.Random()
        self._init_schema()

    def _init_schema(self) -> None:
        with self.db.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS inbox_items (
                    player_id INTEGER NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
                    day_key TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    card_id TEXT NOT NULL,
                    choice_index INTEGER,
                    PRIMARY KEY(player_id, day_key, slot)
                );

                CREATE TABLE IF NOT EXISTS focus_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
                    day_key TEXT NOT NULL,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    step INTEGER NOT NULL DEFAULT 0,
                    progress_gain INTEGER NOT NULL DEFAULT 0,
                    stress_gain INTEGER NOT NULL DEFAULT 0,
                    skill_gain INTEGER NOT NULL DEFAULT 0,
                    reputation_gain INTEGER NOT NULL DEFAULT 0,
                    visibility_gain INTEGER NOT NULL DEFAULT 0,
                    network_gain INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_focus_player_day
                    ON focus_runs(player_id, day_key);
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

    def focus_runs_left(self, telegram_id: int) -> int:
        player = self.game.get_player(telegram_id)
        with self.db.connect() as conn:
            count = conn.execute(
                """
                SELECT COUNT(*) AS amount FROM focus_runs
                WHERE player_id = ? AND day_key = ?
                """,
                (telegram_id, player["day_key"]),
            ).fetchone()["amount"]
        return max(0, FOCUS_RUNS_PER_DAY - int(count))

    def active_focus(self, telegram_id: int) -> dict[str, Any] | None:
        player = self.game.get_player(telegram_id)
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM focus_runs
                WHERE player_id = ? AND day_key = ? AND active = 1
                ORDER BY id DESC LIMIT 1
                """,
                (telegram_id, player["day_key"]),
            ).fetchone()
        return dict(row) if row else None

    def focus_view(self, telegram_id: int) -> dict[str, Any] | None:
        run = self.active_focus(telegram_id)
        if not run or run["step"] >= len(FOCUS_STEPS):
            return None
        return {
            "run": run,
            "step": FOCUS_STEPS[run["step"]],
            "step_number": run["step"] + 1,
            "step_total": len(FOCUS_STEPS),
        }

    def start_focus(self, telegram_id: int) -> dict[str, Any]:
        player = self.game.get_player(telegram_id)
        active = self.active_focus(telegram_id)
        if active:
            return active
        if self.focus_runs_left(telegram_id) <= 0:
            raise GameError("Сегодня фокус-сессии уже использованы.")
        if player["actions_left"] <= 0:
            raise GameError("На сегодня ключевые действия закончились.")

        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            player_row = conn.execute(
                "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if player_row["actions_left"] <= 0:
                raise GameError("На сегодня ключевые действия закончились.")

            project = conn.execute(
                """
                SELECT * FROM projects
                WHERE player_id = ? AND status = 'active'
                ORDER BY id DESC LIMIT 1
                """,
                (telegram_id,),
            ).fetchone()
            if not project:
                project = self.game._create_project(conn, player_row)

            conn.execute(
                "UPDATE players SET actions_left = actions_left - 1 WHERE telegram_id = ?",
                (telegram_id,),
            )
            cur = conn.execute(
                """
                INSERT INTO focus_runs (player_id, day_key, project_id)
                VALUES (?, ?, ?)
                """,
                (telegram_id, player_row["day_key"], project["id"]),
            )
            conn.execute(
                """
                INSERT INTO action_log (player_id, career_day, day_key, action_type)
                VALUES (?, ?, ?, 'focus')
                """,
                (telegram_id, player_row["career_day"], player_row["day_key"]),
            )
            row = conn.execute(
                "SELECT * FROM focus_runs WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        return dict(row)

    def resolve_focus(self, telegram_id: int, choice_index: int) -> dict[str, Any]:
        if choice_index not in {0, 1, 2}:
            raise GameError("Некорректный выбор.")
        player = self.game.get_player(telegram_id)

        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run = conn.execute(
                """
                SELECT * FROM focus_runs
                WHERE player_id = ? AND day_key = ? AND active = 1
                ORDER BY id DESC LIMIT 1
                """,
                (telegram_id, player["day_key"]),
            ).fetchone()
            if not run:
                raise GameError("Активной фокус-сессии нет.")
            if run["step"] >= len(FOCUS_STEPS):
                raise GameError("Фокус-сессия уже завершена.")

            step = FOCUS_STEPS[run["step"]]
            _, progress_range, effects, result = step["choices"][choice_index]
            progress = self.rng.randint(*progress_range)
            gains = {
                "progress_gain": run["progress_gain"] + progress,
                "stress_gain": run["stress_gain"] + effects.get("stress", 0),
                "skill_gain": run["skill_gain"] + effects.get("skill", 0),
                "reputation_gain": run["reputation_gain"] + effects.get("reputation", 0),
                "visibility_gain": run["visibility_gain"] + effects.get("visibility", 0),
                "network_gain": run["network_gain"] + effects.get("network", 0),
            }
            next_step = run["step"] + 1
            finished = next_step >= len(FOCUS_STEPS)

            conn.execute(
                """
                UPDATE focus_runs
                SET step = ?, progress_gain = ?, stress_gain = ?, skill_gain = ?,
                    reputation_gain = ?, visibility_gain = ?, network_gain = ?, active = ?
                WHERE id = ?
                """,
                (
                    next_step,
                    gains["progress_gain"],
                    gains["stress_gain"],
                    gains["skill_gain"],
                    gains["reputation_gain"],
                    gains["visibility_gain"],
                    gains["network_gain"],
                    0 if finished else 1,
                    run["id"],
                ),
            )

            if not finished:
                return {"finished": False, "notice": result, "progress": progress}

            self.game._apply_changes(
                conn,
                telegram_id,
                {
                    "stress": gains["stress_gain"],
                    "skill": gains["skill_gain"],
                    "reputation": gains["reputation_gain"],
                    "visibility": gains["visibility_gain"],
                    "network": gains["network_gain"],
                },
            )
            completion = self._apply_project_progress(
                conn, telegram_id, run["project_id"], gains["progress_gain"]
            )
            burnout = self._apply_burnout_if_needed(conn, telegram_id)

            summary = f"Фокус-сессия завершена: +{gains['progress_gain']} к проекту."
            if completion:
                summary += f"\n{completion}"
            if burnout:
                summary += f"\n{burnout}"
            self.game._journal(
                conn,
                telegram_id,
                player["career_day"],
                "focus",
                summary,
            )
            return {
                "finished": True,
                "notice": f"{result}\n{summary}",
                "progress": gains["progress_gain"],
            }

    def _apply_project_progress(
        self,
        conn,
        telegram_id: int,
        project_id: int,
        progress: int,
    ) -> str | None:
        project = conn.execute(
            "SELECT * FROM projects WHERE id = ? AND player_id = ?",
            (project_id, telegram_id),
        ).fetchone()
        if not project or project["status"] != "active":
            return None

        new_progress = min(project["target"], project["progress"] + progress)
        conn.execute(
            "UPDATE projects SET progress = ? WHERE id = ?",
            (new_progress, project_id),
        )
        if new_progress < project["target"]:
            return None

        player = conn.execute(
            "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        conn.execute(
            """
            UPDATE projects
            SET status = 'completed', completed_day = ?
            WHERE id = ?
            """,
            (player["career_day"], project_id),
        )
        self.game._apply_changes(
            conn,
            telegram_id,
            {
                "money": project["reward_money"],
                "reputation": project["reward_rep"],
                "visibility": 1,
                "projects_done": 1,
            },
        )
        fresh = conn.execute(
            "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        self.game._create_project(conn, fresh)
        reward = f"{project['reward_money']:,}".replace(",", " ")
        return f"Проект закрыт: +{reward} ₽ и +{project['reward_rep']} к репутации."

    @staticmethod
    def _apply_burnout_if_needed(conn, telegram_id: int) -> str | None:
        player = conn.execute(
            "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if player["stress"] < 100:
            return None
        conn.execute(
            """
            UPDATE players
            SET stress = 72,
                reputation = MAX(0, reputation - 2),
                actions_left = 0
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        )
        return "Перегруз: остаток дня потерян, репутация немного пострадала."
