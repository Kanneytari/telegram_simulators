from __future__ import annotations

import random
from typing import Any

from .game import GameError, GameService
from .opportunity_content import OPPORTUNITIES, OPPORTUNITIES_PER_DAY, OPPORTUNITY_RUNS_PER_DAY


STAT_LABELS = {
    "skill": "Навык",
    "reputation": "Репутация",
    "visibility": "Заметность",
    "network": "Связи",
}


class OpportunityService:
    def __init__(self, game: GameService, rng: random.Random | None = None) -> None:
        self.game = game
        self.db = game.db
        self.rng = rng or random.Random()
        self._init_schema()

    def _init_schema(self) -> None:
        with self.db.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS opportunity_board (
                    player_id INTEGER NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
                    day_key TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    opportunity_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    PRIMARY KEY(player_id, day_key, slot)
                );

                CREATE TABLE IF NOT EXISTS opportunity_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
                    day_key TEXT NOT NULL,
                    opportunity_id TEXT NOT NULL,
                    stage INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_opportunity_runs_player_day
                    ON opportunity_runs(player_id, day_key);

                CREATE TABLE IF NOT EXISTS career_wins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
                    career_day INTEGER NOT NULL,
                    opportunity_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    successes INTEGER NOT NULL,
                    reward_money INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def _ensure_board(self, telegram_id: int) -> dict[str, Any]:
        player = self.game.get_player(telegram_id)
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM opportunity_board
                WHERE player_id = ? AND day_key = ?
                ORDER BY slot
                """,
                (telegram_id, player["day_key"]),
            ).fetchall()
            if rows:
                return player

            seed = f"opportunities:{telegram_id}:{player['career_day']}:{player['day_key']}"
            rng = random.Random(seed)
            chosen = rng.sample(
                OPPORTUNITIES,
                k=min(OPPORTUNITIES_PER_DAY, len(OPPORTUNITIES)),
            )
            conn.executemany(
                """
                INSERT INTO opportunity_board (player_id, day_key, slot, opportunity_id)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (telegram_id, player["day_key"], slot, item["id"])
                    for slot, item in enumerate(chosen, start=1)
                ],
            )
        return player

    @staticmethod
    def _content(opportunity_id: str) -> dict[str, Any]:
        item = next((x for x in OPPORTUNITIES if x["id"] == opportunity_id), None)
        if not item:
            raise GameError("Неизвестная возможность.")
        return item

    def runs_left(self, telegram_id: int) -> int:
        player = self._ensure_board(telegram_id)
        with self.db.connect() as conn:
            count = conn.execute(
                """
                SELECT COUNT(*) AS amount FROM opportunity_runs
                WHERE player_id = ? AND day_key = ?
                """,
                (telegram_id, player["day_key"]),
            ).fetchone()["amount"]
        return max(0, OPPORTUNITY_RUNS_PER_DAY - int(count))

    def active_run(self, telegram_id: int) -> dict[str, Any] | None:
        player = self._ensure_board(telegram_id)
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM opportunity_runs
                WHERE player_id = ? AND day_key = ? AND active = 1
                ORDER BY id DESC LIMIT 1
                """,
                (telegram_id, player["day_key"]),
            ).fetchone()
        return dict(row) if row else None

    def board(self, telegram_id: int) -> list[dict[str, Any]]:
        player = self._ensure_board(telegram_id)
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM opportunity_board
                WHERE player_id = ? AND day_key = ?
                ORDER BY slot
                """,
                (telegram_id, player["day_key"]),
            ).fetchall()
        result = []
        for row in rows:
            content = self._content(row["opportunity_id"])
            result.append({**content, "slot": row["slot"], "status": row["status"]})
        return result

    def start(self, telegram_id: int, slot: int) -> dict[str, Any]:
        player = self._ensure_board(telegram_id)
        if self.active_run(telegram_id):
            raise GameError("Сначала закончи текущую возможность.")
        if self.runs_left(telegram_id) <= 0:
            raise GameError("Сегодня ты уже использовал две карьерные возможности.")
        if player["actions_left"] <= 0:
            raise GameError("Нужно одно ключевое действие, а на сегодня они закончились.")

        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM opportunity_board
                WHERE player_id = ? AND day_key = ? AND slot = ?
                """,
                (telegram_id, player["day_key"], slot),
            ).fetchone()
            if not row or row["status"] != "open":
                raise GameError("Эта возможность уже недоступна.")

            current = conn.execute(
                "SELECT actions_left FROM players WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            if not current or current["actions_left"] <= 0:
                raise GameError("Ключевые действия на сегодня закончились.")

            conn.execute(
                "UPDATE players SET actions_left = actions_left - 1 WHERE telegram_id = ?",
                (telegram_id,),
            )
            conn.execute(
                """
                UPDATE opportunity_board SET status = 'used'
                WHERE player_id = ? AND day_key = ? AND slot = ?
                """,
                (telegram_id, player["day_key"], slot),
            )
            cur = conn.execute(
                """
                INSERT INTO opportunity_runs (player_id, day_key, opportunity_id)
                VALUES (?, ?, ?)
                """,
                (telegram_id, player["day_key"], row["opportunity_id"]),
            )
            conn.execute(
                """
                INSERT INTO action_log (player_id, career_day, day_key, action_type)
                VALUES (?, ?, ?, 'opportunity')
                """,
                (telegram_id, player["career_day"], player["day_key"]),
            )
            run = conn.execute(
                "SELECT * FROM opportunity_runs WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        return dict(run)

    def current(self, telegram_id: int) -> dict[str, Any] | None:
        run = self.active_run(telegram_id)
        if not run:
            return None
        content = self._content(run["opportunity_id"])
        if run["stage"] >= len(content["stages"]):
            return None
        player = self.game.get_player(telegram_id)
        stage = content["stages"][run["stage"]]
        choices = []
        for index, choice in enumerate(stage["choices"]):
            title, stat, difficulty, success_effects, fail_effects, *_ = choice
            chance = self.success_chance(player[stat], difficulty)
            choices.append(
                {
                    "index": index,
                    "title": title,
                    "stat": stat,
                    "stat_label": STAT_LABELS[stat],
                    "chance": chance,
                    "success_effects": success_effects,
                    "fail_effects": fail_effects,
                }
            )
        return {
            "run": run,
            "content": content,
            "stage": stage,
            "stage_number": run["stage"] + 1,
            "stage_total": len(content["stages"]),
            "choices": choices,
        }

    @staticmethod
    def success_chance(stat_value: int, difficulty: int) -> int:
        return max(25, min(90, 55 + (stat_value - difficulty) * 4))

    def resolve(self, telegram_id: int, choice_index: int) -> dict[str, Any]:
        view = self.current(telegram_id)
        if not view:
            raise GameError("Активной карьерной возможности нет.")
        if choice_index < 0 or choice_index >= len(view["stage"]["choices"]):
            raise GameError("Некорректный выбор.")

        player = self.game.get_player(telegram_id)
        choice = view["stage"]["choices"][choice_index]
        title, stat, difficulty, success_effects, fail_effects, success_text, fail_text = choice
        chance = self.success_chance(player[stat], difficulty)
        success = self.rng.randint(1, 100) <= chance

        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run = conn.execute(
                "SELECT * FROM opportunity_runs WHERE id = ? AND active = 1",
                (view["run"]["id"],),
            ).fetchone()
            if not run:
                raise GameError("Эта возможность уже завершена.")

            self.game._apply_changes(
                conn,
                telegram_id,
                success_effects if success else fail_effects,
            )
            next_stage = run["stage"] + 1
            successes = run["successes"] + int(success)
            finished = next_stage >= len(view["content"]["stages"])
            conn.execute(
                """
                UPDATE opportunity_runs
                SET stage = ?, successes = ?, active = ?
                WHERE id = ?
                """,
                (next_stage, successes, 0 if finished else 1, run["id"]),
            )

            outcome = success_text if success else fail_text
            if not finished:
                return {
                    "finished": False,
                    "success": success,
                    "chance": chance,
                    "choice": title,
                    "text": outcome,
                }

            final = self._finish(
                conn,
                telegram_id,
                player["career_day"],
                view["content"],
                successes,
            )
            return {
                "finished": True,
                "success": success,
                "chance": chance,
                "choice": title,
                "text": outcome,
                **final,
            }

    def _finish(
        self,
        conn,
        telegram_id: int,
        career_day: int,
        content: dict[str, Any],
        successes: int,
    ) -> dict[str, Any]:
        if successes >= 3:
            tier = "Прорыв"
            multiplier = 1.5
            final_effects = {"reputation": 2, "visibility": 2}
        elif successes == 2:
            tier = "Успех"
            multiplier = 1.2
            final_effects = {"reputation": 1, "visibility": 1}
        elif successes == 1:
            tier = "Смешанный результат"
            multiplier = 0.8
            final_effects = {}
        else:
            tier = "Не вышло"
            multiplier = 0.4
            final_effects = {"stress": 4}

        reward = round(content["reward_money"] * multiplier)
        self.game._apply_changes(conn, telegram_id, {**final_effects, "money": reward})
        conn.execute(
            """
            INSERT INTO career_wins (
                player_id, career_day, opportunity_id, title, tier, successes, reward_money
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_id,
                career_day,
                content["id"],
                content["title"],
                tier,
                successes,
                reward,
            ),
        )
        reward_text = f"{reward:,}".replace(",", " ")
        summary = f"{content['title']}: {tier}. {successes}/3 успешных решений, +{reward_text} ₽."
        self.game._journal(conn, telegram_id, career_day, "opportunity", summary)
        return {"tier": tier, "successes": successes, "reward": reward, "summary": summary}

    def portfolio(self, telegram_id: int, limit: int = 10) -> list[dict[str, Any]]:
        self.game.get_player(telegram_id)
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM career_wins
                WHERE player_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (telegram_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]
