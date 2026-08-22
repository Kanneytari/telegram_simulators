from __future__ import annotations

import random
from typing import Any

from .game import GameError, GameService


TACTICS = {
    "fast": {
        "title": "⚡ Быстро",
        "hint": "много прогресса · риск растёт",
        "progress": (24, 30),
        "effects": {"stress": 9},
        "quality": 0,
        "risk": 18,
    },
    "careful": {
        "title": "🧠 Надёжно",
        "hint": "меньше прогресса · качество растёт",
        "progress": (16, 21),
        "effects": {"stress": 6},
        "quality": 16,
        "risk": -4,
    },
    "team": {
        "title": "🤝 С коллегами",
        "hint": "средний темп · снижает риск",
        "progress": (18, 24),
        "effects": {"stress": 5, "network": 1},
        "quality": 6,
        "risk": -8,
    },
}


class ProjectPlayService:
    def __init__(self, game: GameService, rng: random.Random | None = None) -> None:
        self.game = game
        self.db = game.db
        self.rng = rng or random.Random()
        self._ensure_columns()

    def _ensure_columns(self) -> None:
        with self.db.connect() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
            if "quality" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN quality INTEGER NOT NULL DEFAULT 0")
            if "risk" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN risk INTEGER NOT NULL DEFAULT 0")

    def state(self, telegram_id: int) -> dict[str, Any] | None:
        project = self.game.get_active_project(telegram_id)
        if not project:
            return None
        return project

    @staticmethod
    def quality_label(value: int) -> str:
        if value >= 35:
            return "отличное"
        if value >= 20:
            return "надёжное"
        if value >= 8:
            return "рабочее"
        return "сырое"

    @staticmethod
    def risk_label(value: int) -> str:
        if value >= 65:
            return "критический"
        if value >= 45:
            return "высокий"
        if value >= 20:
            return "средний"
        return "низкий"

    def work(self, telegram_id: int, tactic_id: str) -> str:
        tactic = TACTICS.get(tactic_id)
        if not tactic:
            raise GameError("Неизвестная тактика.")

        self.game._rollover_if_needed(telegram_id)
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            player = conn.execute(
                "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if not player:
                raise GameError("Игрок не найден.")
            if player["actions_left"] <= 0:
                raise GameError("Ключевые действия на сегодня закончились.")

            project = conn.execute(
                """
                SELECT * FROM projects
                WHERE player_id = ? AND status = 'active'
                ORDER BY id DESC LIMIT 1
                """,
                (telegram_id,),
            ).fetchone()
            if not project:
                project = self.game._create_project(conn, player)
                project = conn.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone()

            base = self.rng.randint(*tactic["progress"])
            if player["track"] == "expert" and player["rank"] >= 3:
                base += 3
            progress = max(1, round(base * self.game._stress_efficiency(player["stress"])))

            new_quality = max(0, min(100, project["quality"] + tactic["quality"]))
            new_risk = max(0, min(100, project["risk"] + tactic["risk"]))
            setback = 0
            complication = ""
            if new_risk >= 50:
                chance = min(0.45, (new_risk - 40) / 100)
                if self.rng.random() < chance:
                    setback = self.rng.randint(8, 15)
                    complication = (
                        f"\n⚠️ Риск сработал: пришлось переделывать часть работы (-{setback} прогресса)."
                    )

            new_progress = max(
                0,
                min(project["target"], project["progress"] + progress - setback),
            )
            conn.execute(
                "UPDATE projects SET progress = ?, quality = ?, risk = ? WHERE id = ?",
                (new_progress, new_quality, new_risk, project["id"]),
            )
            self.game._apply_changes(conn, telegram_id, tactic["effects"])
            if tactic_id == "careful" and self.rng.random() < 0.35:
                self.game._apply_changes(conn, telegram_id, {"skill": 1})

            conn.execute(
                "UPDATE players SET actions_left = actions_left - 1 WHERE telegram_id = ?",
                (telegram_id,),
            )
            conn.execute(
                """
                INSERT INTO action_log (player_id, career_day, day_key, action_type)
                VALUES (?, ?, ?, ?)
                """,
                (telegram_id, player["career_day"], player["day_key"], f"work:{tactic_id}"),
            )

            result = (
                f"{tactic['title']}: +{progress} прогресса. "
                f"Качество {self.quality_label(new_quality)}, риск {self.risk_label(new_risk)}."
                f"{complication}"
            )

            if new_progress >= project["target"]:
                result += "\n" + self._complete_project(conn, telegram_id, project["id"])

            after = conn.execute(
                "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if after["stress"] >= 100:
                conn.execute(
                    """
                    UPDATE players
                    SET stress = 72, reputation = MAX(0, reputation - 2), actions_left = 0
                    WHERE telegram_id = ?
                    """,
                    (telegram_id,),
                )
                result += "\n🔥 Перегруз: остаток дня потерян, репутация -2."

            return result

    def _complete_project(self, conn, telegram_id: int, project_id: int) -> str:
        project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        player = conn.execute(
            "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()

        bonus_money = 0
        bonus_rep = 0
        verdict = "Проект принят."
        if project["quality"] >= 35 and project["risk"] <= 30:
            bonus_money = round(project["reward_money"] * 0.25)
            bonus_rep = 2
            verdict = "Проект заметно превзошёл ожидания."
        elif project["quality"] >= 20 and project["risk"] <= 45:
            bonus_money = round(project["reward_money"] * 0.10)
            bonus_rep = 1
            verdict = "Проект закрыт уверенно и без неприятных сюрпризов."

        total_money = project["reward_money"] + bonus_money
        total_rep = project["reward_rep"] + bonus_rep
        conn.execute(
            "UPDATE projects SET status = 'completed', completed_day = ? WHERE id = ?",
            (player["career_day"], project_id),
        )
        self.game._apply_changes(
            conn,
            telegram_id,
            {
                "money": total_money,
                "reputation": total_rep,
                "visibility": 1,
                "projects_done": 1,
            },
        )
        fresh = conn.execute(
            "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        self.game._create_project(conn, fresh)

        reward = f"{total_money:,}".replace(",", " ")
        text = f"✅ {verdict} +{reward} ₽, репутация +{total_rep}."
        self.game._journal(
            conn,
            telegram_id,
            player["career_day"],
            "project_completed",
            text.replace("✅ ", ""),
        )
        return text
