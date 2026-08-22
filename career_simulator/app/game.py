from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .content import (
    EVENTS,
    INVESTMENTS,
    PROJECT_TITLES,
    PROMOTION_REQUIREMENTS,
    RANKS_BY_TRACK,
    RANKS_COMMON,
    SALARIES,
)
from .db import Database

MOSCOW = ZoneInfo("Europe/Moscow")
ACTIONS_PER_DAY = 5
RESET_HOUR = 4
MAX_RANK = 5


class GameError(Exception):
    pass


class GameService:
    def __init__(self, db: Database, rng: random.Random | None = None):
        self.db = db
        self.rng = rng or random.Random()

    @staticmethod
    def game_day_key(now: datetime | None = None) -> str:
        current = now.astimezone(MOSCOW) if now else datetime.now(MOSCOW)
        return (current - timedelta(hours=RESET_HOUR)).date().isoformat()

    @staticmethod
    def rank_name(rank: int, track: str) -> str:
        if rank in RANKS_COMMON:
            return RANKS_COMMON[rank]
        return RANKS_BY_TRACK.get(track, RANKS_BY_TRACK["expert"]).get(rank, "Карьерист")

    @staticmethod
    def salary(rank: int) -> int:
        return SALARIES[min(max(rank, 0), MAX_RANK)]

    def ensure_player(self, telegram_id: int, username: str | None = None) -> dict[str, Any]:
        day_key = self.game_day_key()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if not row:
                conn.execute(
                    """
                    INSERT INTO players (telegram_id, username, day_key)
                    VALUES (?, ?, ?)
                    """,
                    (telegram_id, username, day_key),
                )
                player = conn.execute(
                    "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
                ).fetchone()
                self._create_project(conn, player)
                self._journal(
                    conn,
                    telegram_id,
                    1,
                    "start",
                    "Первый рабочий день. Пока никто не знает, на что ты способен. Включая тебя.",
                )
            else:
                conn.execute(
                    "UPDATE players SET username = ?, last_seen = CURRENT_TIMESTAMP WHERE telegram_id = ?",
                    (username, telegram_id),
                )

        self._rollover_if_needed(telegram_id)
        return self.get_player(telegram_id, rollover=False)

    def get_player(self, telegram_id: int, rollover: bool = True) -> dict[str, Any]:
        if rollover:
            self._rollover_if_needed(telegram_id)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if not row:
                raise GameError("Игрок не найден. Нажми /start.")
            return dict(row)

    def get_active_project(self, telegram_id: int) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM projects
                WHERE player_id = ? AND status = 'active'
                ORDER BY id DESC LIMIT 1
                """,
                (telegram_id,),
            ).fetchone()
            return dict(row) if row else None

    def dashboard(self, telegram_id: int) -> str:
        p = self.get_player(telegram_id)
        project = self.get_active_project(telegram_id)
        rank = self.rank_name(p["rank"], p["track"])
        stress_icon = "🟢" if p["stress"] < 55 else "🟡" if p["stress"] < 80 else "🔴"
        promo = "\n🚀 Повышение доступно в разделе «Карьера»." if p["promotion_ready"] else ""

        if project:
            project_line = (
                f"📌 {project['title']}\n"
                f"   {project['progress']}/{project['target']} · дедлайн: день {project['deadline_day']}"
            )
        else:
            project_line = "📌 Активного проекта нет"

        return (
            f"💼 <b>{rank}</b> · день {p['career_day']}\n"
            f"💰 {p['money']:,} ₽ · ⚡ {p['actions_left']}/{ACTIONS_PER_DAY}\n"
            f"🧠 Навык {p['skill']} · ⭐ Репутация {p['reputation']}\n"
            f"👀 Заметность {p['visibility']} · 🤝 Связи {p['network']}\n"
            f"{stress_icon} Стресс {p['stress']}/100\n\n"
            f"{project_line}{promo}"
        ).replace(",", " ")

    def perform_action(self, telegram_id: int, action: str) -> str:
        if action not in {"work", "learn", "network", "show", "rest"}:
            raise GameError("Неизвестное действие.")

        self._rollover_if_needed(telegram_id)
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            p = conn.execute(
                "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if not p:
                raise GameError("Игрок не найден.")
            if p["actions_left"] <= 0:
                raise GameError("На сегодня рабочий день закончен. Новые действия появятся после 04:00 МСК.")

            changes: dict[str, int] = {}
            result = ""

            if action == "work":
                project = conn.execute(
                    """
                    SELECT * FROM projects
                    WHERE player_id = ? AND status = 'active'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (telegram_id,),
                ).fetchone()
                if not project:
                    project = self._create_project(conn, p)

                base = self.rng.randint(18, 24)
                if p["track"] == "expert" and p["rank"] >= 3:
                    base += 3
                efficiency = self._stress_efficiency(p["stress"])
                progress = max(1, round(base * efficiency))
                stress = self.rng.randint(7, 10)
                changes["stress"] = stress
                if self.rng.random() < 0.30:
                    changes["skill"] = 1

                new_progress = min(project["target"], project["progress"] + progress)
                conn.execute(
                    "UPDATE projects SET progress = ? WHERE id = ?",
                    (new_progress, project["id"]),
                )
                result = f"Ты продвинул проект на {progress} пунктов."

                if new_progress >= project["target"]:
                    conn.execute(
                        """
                        UPDATE projects
                        SET status = 'completed', completed_day = ?
                        WHERE id = ?
                        """,
                        (p["career_day"], project["id"]),
                    )
                    changes["money"] = changes.get("money", 0) + project["reward_money"]
                    changes["reputation"] = changes.get("reputation", 0) + project["reward_rep"]
                    changes["visibility"] = changes.get("visibility", 0) + 1
                    changes["projects_done"] = 1
                    result += (
                        f"\n✅ Проект закрыт: +{project['reward_money']:,} ₽, "
                        f"+{project['reward_rep']} к репутации."
                    ).replace(",", " ")

            elif action == "learn":
                gain = self.rng.randint(2, 3)
                if p["track"] == "expert" and p["rank"] >= 3:
                    gain += 1
                changes = {"skill": gain, "stress": 4}
                result = f"Разобрался в полезной теме: +{gain} к навыку."

            elif action == "network":
                gain = self.rng.randint(2, 3)
                if p["track"] == "manager" and p["rank"] >= 3:
                    gain += 1
                changes = {"network": gain, "visibility": 1, "stress": 3}
                result = f"Нужные люди начали узнавать тебя: +{gain} к связям."

            elif action == "show":
                project = conn.execute(
                    """
                    SELECT * FROM projects
                    WHERE player_id = ? AND status = 'active'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (telegram_id,),
                ).fetchone()
                enough_work = project and project["progress"] >= project["target"] * 0.35
                if enough_work:
                    gain = self.rng.randint(2, 4)
                    if p["track"] == "manager" and p["rank"] >= 3:
                        gain += 1
                    changes = {"visibility": gain, "reputation": 1, "stress": 3}
                    result = f"Ты показал конкретный результат: +{gain} к заметности."
                else:
                    changes = {"visibility": 1, "reputation": -1, "stress": 2}
                    result = "Показать пока было особо нечего. Тебя заметили, но не совсем так, как хотелось."

            elif action == "rest":
                recovery = self.rng.randint(14, 20)
                changes = {"stress": -recovery}
                result = f"Ты действительно выдохнул: -{recovery} стресса."

            self._apply_changes(conn, telegram_id, changes)
            conn.execute(
                "UPDATE players SET actions_left = actions_left - 1 WHERE telegram_id = ?",
                (telegram_id,),
            )
            conn.execute(
                """
                INSERT INTO action_log (player_id, career_day, day_key, action_type)
                VALUES (?, ?, ?, ?)
                """,
                (telegram_id, p["career_day"], p["day_key"], action),
            )

            after = conn.execute(
                "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if after["stress"] >= 100:
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
                result += "\n🔥 Перегруз. Остаток дня выпал, репутация немного пострадала. Стресс откатился до 72."

            if action == "work":
                active = conn.execute(
                    "SELECT 1 FROM projects WHERE player_id = ? AND status = 'active' LIMIT 1",
                    (telegram_id,),
                ).fetchone()
                if not active:
                    latest = conn.execute(
                        "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
                    ).fetchone()
                    self._create_project(conn, latest)
                    result += "\n📌 Тебе сразу прилетел следующий проект. Карьера не умеет останавливаться."

            return result

    def get_daily_event(self, telegram_id: int) -> dict[str, Any]:
        self._rollover_if_needed(telegram_id)
        p = self.get_player(telegram_id, rollover=False)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM daily_events WHERE player_id = ? AND day_key = ?",
                (telegram_id, p["day_key"]),
            ).fetchone()
            if not row:
                event = self.rng.choice(EVENTS)
                conn.execute(
                    "INSERT INTO daily_events (player_id, day_key, event_id) VALUES (?, ?, ?)",
                    (telegram_id, p["day_key"], event["id"]),
                )
                choice_index = None
                event_id = event["id"]
            else:
                event_id = row["event_id"]
                choice_index = row["choice_index"]

        event = next(e for e in EVENTS if e["id"] == event_id)
        return {**event, "choice_index": choice_index}

    def resolve_event(self, telegram_id: int, event_id: str, choice_index: int) -> str:
        if choice_index not in {0, 1}:
            raise GameError("Некорректный выбор.")
        p = self.get_player(telegram_id)
        event = next((e for e in EVENTS if e["id"] == event_id), None)
        if not event:
            raise GameError("Событие больше недоступно.")

        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM daily_events WHERE player_id = ? AND day_key = ?",
                (telegram_id, p["day_key"]),
            ).fetchone()
            if not row or row["event_id"] != event_id:
                raise GameError("Это событие уже неактуально.")
            if row["choice_index"] is not None:
                raise GameError("Сегодняшнее событие уже разыграно.")

            _, effects, result = event["choices"][choice_index]
            self._apply_changes(conn, telegram_id, effects)
            conn.execute(
                """
                UPDATE daily_events SET choice_index = ?
                WHERE player_id = ? AND day_key = ?
                """,
                (choice_index, telegram_id, p["day_key"]),
            )
            self._journal(conn, telegram_id, p["career_day"], "event", result)
            return result

    def buy_investment(self, telegram_id: int, investment_id: str) -> str:
        item = INVESTMENTS.get(investment_id)
        if not item:
            raise GameError("Неизвестная покупка.")
        p = self.get_player(telegram_id)

        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            bought = conn.execute(
                "SELECT 1 FROM purchases WHERE player_id = ? AND day_key = ?",
                (telegram_id, p["day_key"]),
            ).fetchone()
            if bought:
                raise GameError("Сегодня ты уже вложился в карьеру. Следующая инвестиция — завтра.")
            if p["money"] < item["price"]:
                raise GameError("Не хватает денег.")

            conn.execute(
                "UPDATE players SET money = money - ? WHERE telegram_id = ?",
                (item["price"], telegram_id),
            )
            self._apply_changes(conn, telegram_id, item["effects"])
            conn.execute(
                """
                INSERT INTO purchases (player_id, day_key, investment_id, price)
                VALUES (?, ?, ?, ?)
                """,
                (telegram_id, p["day_key"], investment_id, item["price"]),
            )
            return item["result"]

    def career_status(self, telegram_id: int) -> str:
        p = self.get_player(telegram_id)
        current = self.rank_name(p["rank"], p["track"])
        if p["rank"] >= MAX_RANK:
            next_part = "🏆 Ты уже на вершине текущей карьерной лестницы."
        else:
            reqs = PROMOTION_REQUIREMENTS[p["rank"]]
            labels = {
                "skill": "Навык",
                "reputation": "Репутация",
                "visibility": "Заметность",
                "network": "Связи",
                "projects_done": "Проекты",
            }
            rows = []
            for key, need in reqs.items():
                value = p[key]
                mark = "✅" if value >= need else "▫️"
                rows.append(f"{mark} {labels[key]}: {value}/{need}")
            next_part = "До следующего уровня:\n" + "\n".join(rows)

        promo = "\n\n🚀 Повышение уже одобрено." if p["promotion_ready"] else ""
        track = ""
        if p["track"] != "general":
            track = f"\nТрек: {'Экспертный' if p['track'] == 'expert' else 'Управленческий'}"
        return (
            f"📒 <b>Карьера</b>\n\n"
            f"Сейчас: {current}{track}\n"
            f"Ставка за активный день: {self.salary(p['rank']):,} ₽\n"
            f"Закрыто проектов: {p['projects_done']}\n"
            f"Провалено проектов: {p['projects_failed']}\n\n"
            f"{next_part}{promo}"
        ).replace(",", " ")

    def claim_promotion(self, telegram_id: int, track: str | None = None) -> str:
        p = self.get_player(telegram_id)
        if not p["promotion_ready"]:
            raise GameError("Повышение пока не одобрено.")
        if p["rank"] >= MAX_RANK:
            raise GameError("Выше текущей карьерной лестницы пока некуда.")

        next_rank = p["rank"] + 1
        next_track = p["track"]
        if next_rank == 3 and p["track"] == "general":
            if track not in {"expert", "manager"}:
                raise GameError("На этом уровне нужно выбрать карьерный трек.")
            next_track = track

        bonus = self.salary(next_rank) * 2
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE players
                SET rank = ?, track = ?, money = money + ?,
                    promotion_ready = 0, stress = MIN(100, stress + 5)
                WHERE telegram_id = ?
                """,
                (next_rank, next_track, bonus, telegram_id),
            )
            title = self.rank_name(next_rank, next_track)
            self._journal(
                conn,
                telegram_id,
                p["career_day"],
                "promotion",
                f"Повышение: {title}. Разовый бонус {bonus:,} ₽.".replace(",", " "),
            )
        return f"🚀 Повышение! Теперь ты — <b>{self.rank_name(next_rank, next_track)}</b>.\nБонус: {bonus:,} ₽.".replace(",", " ")

    def recent_history(self, telegram_id: int, limit: int = 8) -> str:
        p = self.get_player(telegram_id)
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT career_day, text FROM journal
                WHERE player_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (telegram_id, limit),
            ).fetchall()
        if not rows:
            return "История пока пустая."
        items = [f"День {r['career_day']}: {r['text']}" for r in rows]
        return "🗂 <b>Последние события</b>\n\n" + "\n\n".join(items)

    def _rollover_if_needed(self, telegram_id: int) -> None:
        today = self.game_day_key()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            p = conn.execute(
                "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if not p or p["day_key"] == today:
                return

            if p["career_day"] % 5 == 0:
                self._run_review(conn, p)
                p = conn.execute(
                    "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
                ).fetchone()

            new_day = p["career_day"] + 1
            salary = self.salary(p["rank"])
            conn.execute(
                """
                UPDATE players
                SET career_day = ?, day_key = ?, actions_left = ?,
                    money = money + ?, stress = MAX(0, stress - 8),
                    last_seen = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
                """,
                (new_day, today, ACTIONS_PER_DAY, salary, telegram_id),
            )

            project = conn.execute(
                """
                SELECT * FROM projects
                WHERE player_id = ? AND status = 'active'
                ORDER BY id DESC LIMIT 1
                """,
                (telegram_id,),
            ).fetchone()
            if project and new_day > project["deadline_day"]:
                conn.execute(
                    "UPDATE projects SET status = 'failed', completed_day = ? WHERE id = ?",
                    (new_day, project["id"]),
                )
                conn.execute(
                    """
                    UPDATE players
                    SET projects_failed = projects_failed + 1,
                        reputation = MAX(0, reputation - 2),
                        stress = MIN(100, stress + 8)
                    WHERE telegram_id = ?
                    """,
                    (telegram_id,),
                )
                self._journal(
                    conn,
                    telegram_id,
                    new_day,
                    "project_failed",
                    f"Дедлайн проекта «{project['title']}» сорван. -2 к репутации.",
                )

            active = conn.execute(
                "SELECT 1 FROM projects WHERE player_id = ? AND status = 'active' LIMIT 1",
                (telegram_id,),
            ).fetchone()
            if not active:
                fresh = conn.execute(
                    "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
                ).fetchone()
                self._create_project(conn, fresh)

            self._journal(
                conn,
                telegram_id,
                new_day,
                "new_day",
                f"Новый активный день. Начислено {salary:,} ₽.".replace(",", " "),
            )

    def _run_review(self, conn, p) -> None:
        if p["rank"] >= MAX_RANK:
            self._journal(conn, p["telegram_id"], p["career_day"], "review", "Ревью пройдено. Ты уже на вершине текущей лестницы.")
            return
        if p["promotion_ready"]:
            return

        reqs = PROMOTION_REQUIREMENTS[p["rank"]]
        missing = [key for key, need in reqs.items() if p[key] < need]
        if not missing:
            conn.execute(
                "UPDATE players SET promotion_ready = 1 WHERE telegram_id = ?",
                (p["telegram_id"],),
            )
            self._journal(
                conn,
                p["telegram_id"],
                p["career_day"],
                "review",
                "Карьерное ревью пройдено: повышение одобрено.",
            )
        else:
            labels = {
                "skill": "навык",
                "reputation": "репутация",
                "visibility": "заметность",
                "network": "связи",
                "projects_done": "закрытые проекты",
            }
            human = ", ".join(labels[x] for x in missing)
            self._journal(
                conn,
                p["telegram_id"],
                p["career_day"],
                "review",
                f"Карьерное ревью: повышения пока нет. Проседают: {human}.",
            )

    def _create_project(self, conn, p):
        rank = min(p["rank"], MAX_RANK)
        target = 70 + rank * 12 + self.rng.randint(0, 15)
        deadline_day = p["career_day"] + 2
        reward_money = self.salary(rank) * 2 + target * 20
        reward_rep = 2 + rank
        title = self.rng.choice(PROJECT_TITLES[rank])
        cur = conn.execute(
            """
            INSERT INTO projects (
                player_id, title, target, deadline_day,
                reward_money, reward_rep, created_day
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p["telegram_id"],
                title,
                target,
                deadline_day,
                reward_money,
                reward_rep,
                p["career_day"],
            ),
        )
        return conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()

    @staticmethod
    def _stress_efficiency(stress: int) -> float:
        if stress >= 80:
            return 0.65
        if stress >= 60:
            return 0.85
        return 1.0

    @staticmethod
    def _apply_changes(conn, telegram_id: int, changes: dict[str, int]) -> None:
        allowed = {"money", "skill", "reputation", "visibility", "network", "stress", "projects_done", "projects_failed"}
        for key, delta in changes.items():
            if key not in allowed or not delta:
                continue
            if key == "stress":
                conn.execute(
                    f"UPDATE players SET {key} = MIN(100, MAX(0, {key} + ?)) WHERE telegram_id = ?",
                    (delta, telegram_id),
                )
            elif key in {"reputation", "visibility", "network", "skill", "projects_done", "projects_failed"}:
                conn.execute(
                    f"UPDATE players SET {key} = MAX(0, {key} + ?) WHERE telegram_id = ?",
                    (delta, telegram_id),
                )
            else:
                conn.execute(
                    f"UPDATE players SET {key} = {key} + ? WHERE telegram_id = ?",
                    (delta, telegram_id),
                )

    @staticmethod
    def _journal(conn, telegram_id: int, career_day: int, kind: str, text: str) -> None:
        conn.execute(
            """
            INSERT INTO journal (player_id, career_day, kind, text)
            VALUES (?, ?, ?, ?)
            """,
            (telegram_id, career_day, kind, text),
        )
