from __future__ import annotations

import sqlite3
import time

from .combat_rules import (
    COMBAT_LOG_SIZE,
    ENEMY_ACTION_SECONDS,
    OPPORTUNITY_CHANCE,
    OPPORTUNITY_COOLDOWN_SECONDS,
    OPPORTUNITY_DURATION_SECONDS,
    PLAYER_ACTION_LABELS,
    PLAYER_ACTION_SECONDS,
    STIM_DURATION_SECONDS,
    STIM_HEAL_PER_SECOND,
)
from .content import ENEMIES, SECTORS, WEAPONS
from .game import GameError
from .gameplay import GameService as GameplayService
from .progression import level_from_xp, progress_from_xp, xp_required_for_next
from .sector_progression import SECTOR_NEXT, SECTOR_PREVIOUS


class GameService(GameplayService):
    """Runtime service with progression, sector mastery and realtime combat."""

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

    # --- realtime combat -------------------------------------------------

    def combat_action_seconds(self, action: str) -> float:
        if action not in PLAYER_ACTION_SECONDS:
            raise GameError("Неизвестное боевое действие.")
        return float(PLAYER_ACTION_SECONDS[action])

    def combat_action_label(self, action: str) -> str:
        return PLAYER_ACTION_LABELS.get(action, action)

    def combat_timeline(self, telegram_id: int) -> dict | None:
        with self.db.connect() as conn:
            self._ensure_combat_timeline_conn(conn, telegram_id)
            row = conn.execute(
                "SELECT * FROM combat_timeline WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
        return dict(row) if row else None

    def combat_log(self, telegram_id: int) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT text FROM ("
                "SELECT id, text FROM combat_log WHERE telegram_id = ? ORDER BY id DESC LIMIT ?"
                ") ORDER BY id",
                (telegram_id, COMBAT_LOG_SIZE),
            ).fetchall()
        return [str(row["text"]) for row in rows]

    def bind_combat_message(self, telegram_id: int, chat_id: int, message_id: int) -> None:
        with self.db.connect() as conn:
            self._ensure_combat_timeline_conn(conn, telegram_id)
            conn.execute(
                "UPDATE combat_timeline SET chat_id = ?, message_id = ? WHERE telegram_id = ?",
                (chat_id, message_id, telegram_id),
            )

    def combat_message_targets(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT telegram_id, chat_id, message_id FROM combat_timeline "
                "WHERE chat_id IS NOT NULL AND message_id IS NOT NULL"
            ).fetchall()
        return [dict(row) for row in rows]

    def tick_all_combats(self, now: float | None = None) -> dict[int, dict]:
        now = time.time() if now is None else float(now)
        results: dict[int, dict] = {}
        with self.db.connect() as conn:
            rows = conn.execute("SELECT telegram_id FROM combat_timeline").fetchall()
            for row in rows:
                telegram_id = int(row["telegram_id"])
                result = self._tick_combat_conn(conn, telegram_id, now)
                if result:
                    results[telegram_id] = result
        return results

    def _start_combat(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        enemy_id: str,
        *,
        return_state: str,
    ) -> None:
        super()._start_combat(conn, telegram_id, enemy_id, return_state=return_state)
        now = time.time()
        enemy = ENEMIES[enemy_id]
        enemy_action = self._choose_enemy_action_conn(conn, telegram_id, enemy)
        conn.execute("DELETE FROM combat_log WHERE telegram_id = ?", (telegram_id,))
        conn.execute(
            "INSERT OR REPLACE INTO combat_timeline ("
            "telegram_id, player_last_action_at, player_action, player_action_due, "
            "enemy_action, enemy_action_due, periodic_last_at, stim_until, "
            "opportunity_kind, opportunity_until, opportunity_cooldown_until, chat_id, message_id"
            ") VALUES (?, ?, NULL, NULL, ?, ?, ?, 0, NULL, 0, ?, NULL, NULL)",
            (
                telegram_id,
                now,
                enemy_action,
                now + ENEMY_ACTION_SECONDS[enemy_action],
                now,
                now + 5.0,
            ),
        )
        self._log_conn(conn, telegram_id, f"⚔️ Бой начался: {enemy['name']}.")

    def _ensure_combat_timeline_conn(self, conn: sqlite3.Connection, telegram_id: int) -> None:
        row = conn.execute(
            "SELECT 1 FROM combat_timeline WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if row:
            return
        player = self._player(conn, telegram_id)
        if player["state"] != "combat" or not player["enemy_id"]:
            return
        combat = conn.execute(
            "SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not combat:
            return
        now = time.time()
        enemy = ENEMIES[player["enemy_id"]]
        enemy_action = self._choose_enemy_action_conn(conn, telegram_id, enemy)
        conn.execute(
            "INSERT INTO combat_timeline ("
            "telegram_id, player_last_action_at, enemy_action, enemy_action_due, "
            "periodic_last_at, opportunity_cooldown_until"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                telegram_id,
                now,
                enemy_action,
                now + ENEMY_ACTION_SECONDS[enemy_action],
                now,
                now + 5.0,
            ),
        )
        self._log_conn(conn, telegram_id, f"⚔️ Бой продолжается: {enemy['name']}.")

    def _log_conn(self, conn: sqlite3.Connection, telegram_id: int, text: str) -> None:
        text = " ".join(str(text).splitlines()).strip()
        if not text:
            return
        conn.execute(
            "INSERT INTO combat_log (telegram_id, text) VALUES (?, ?)",
            (telegram_id, text),
        )
        conn.execute(
            "DELETE FROM combat_log WHERE telegram_id = ? AND id NOT IN ("
            "SELECT id FROM combat_log WHERE telegram_id = ? ORDER BY id DESC LIMIT ?"
            ")",
            (telegram_id, telegram_id, COMBAT_LOG_SIZE),
        )

    def _cleanup_combat_runtime_conn(self, conn: sqlite3.Connection, telegram_id: int) -> None:
        conn.execute("DELETE FROM combat_timeline WHERE telegram_id = ?", (telegram_id,))
        conn.execute("DELETE FROM combat_log WHERE telegram_id = ?", (telegram_id,))

    def _finish_combat(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        enemy: dict,
        lines: list[str],
    ) -> dict:
        result = super()._finish_combat(conn, telegram_id, enemy, lines)
        self._cleanup_combat_runtime_conn(conn, telegram_id)
        return result

    def _kill(self, conn: sqlite3.Connection, telegram_id: int) -> str:
        text = super()._kill(conn, telegram_id)
        self._cleanup_combat_runtime_conn(conn, telegram_id)
        return text

    def combat_action(
        self,
        telegram_id: int,
        action: str,
        *,
        now: float | None = None,
    ) -> dict:
        if action in {"wait", "aim", "approach"}:
            raise GameError("Это действие больше не используется в новой системе боя.")
        if action not in PLAYER_ACTION_SECONDS:
            raise GameError("Неизвестное боевое действие.")

        now = time.time() if now is None else float(now)
        with self.db.connect() as conn:
            self._ensure_combat_timeline_conn(conn, telegram_id)
            pre_result = self._tick_combat_conn(conn, telegram_id, now)
            player = self._player(conn, telegram_id)
            if player["state"] != "combat" or not player["enemy_id"]:
                return pre_result or {"text": "Бой уже завершён.", "finished": True}

            timeline = conn.execute(
                "SELECT * FROM combat_timeline WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            combat = conn.execute(
                "SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if not timeline or not combat:
                raise GameError("Состояние боя потеряно.")
            if timeline["player_action"]:
                raise GameError("Предыдущее действие ещё выполняется.")

            weapon = WEAPONS[player["weapon_id"]]
            ammo = int(player["ammo"])
            distance = int(combat["distance"])
            opportunity = str(timeline["opportunity_kind"] or "")
            opportunity_valid = float(timeline["opportunity_until"]) > now

            if action in {"shoot", "aimed_shot"} and ammo <= 0:
                raise GameError("Патроны закончились.")
            if action == "burst":
                if "burst" not in weapon.get("modes", ()):
                    raise GameError("Это оружие не умеет стрелять очередью.")
                if ammo < 3:
                    raise GameError("Для очереди нужно минимум 3 патрона.")
            if action == "melee" and distance > 1:
                raise GameError("Противник ещё не подошёл вплотную.")
            if action == "medkit" and int(player["medkits"]) <= 0:
                raise GameError("Аптечек нет.")
            if action == "cover" and (opportunity != "cover" or not opportunity_valid):
                raise GameError("Возможность занять укрытие уже исчезла.")
            if action == "stim" and (opportunity != "stim" or not opportunity_valid):
                raise GameError("Стимулятор уже недоступен.")

            duration = PLAYER_ACTION_SECONDS[action]
            due = max(now, float(timeline["player_last_action_at"]) + duration)
            if action in {"cover", "stim"}:
                conn.execute(
                    "UPDATE combat_timeline SET opportunity_kind = NULL, opportunity_until = 0 "
                    "WHERE telegram_id = ?",
                    (telegram_id,),
                )
            conn.execute(
                "UPDATE combat_timeline SET player_action = ?, player_action_due = ? "
                "WHERE telegram_id = ?",
                (action, due, telegram_id),
            )

            result = self._tick_combat_conn(conn, telegram_id, now)
            if result and result.get("finished"):
                return result
            remaining = max(0.0, due - now)
            return {
                "text": f"{PLAYER_ACTION_LABELS[action]}: {remaining:.1f} сек.",
                "scheduled": True,
            }

    def _tick_combat_conn(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        now: float,
    ) -> dict:
        player = self._player(conn, telegram_id)
        if player["state"] != "combat" or not player["enemy_id"]:
            self._cleanup_combat_runtime_conn(conn, telegram_id)
            return {"finished": True}

        self._ensure_combat_timeline_conn(conn, telegram_id)
        last_result: dict = {}
        for _ in range(100):
            timeline = conn.execute(
                "SELECT * FROM combat_timeline WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if not timeline:
                break

            candidates: list[tuple[float, str]] = [
                (float(timeline["periodic_last_at"]) + 1.0, "periodic"),
                (float(timeline["enemy_action_due"]), "enemy"),
            ]
            if timeline["player_action"] and timeline["player_action_due"] is not None:
                candidates.append((float(timeline["player_action_due"]), "player"))

            due_at, event_type = min(candidates, key=lambda item: item[0])
            if due_at > now:
                break

            if event_type == "periodic":
                conn.execute(
                    "UPDATE combat_timeline SET periodic_last_at = ? WHERE telegram_id = ?",
                    (due_at, telegram_id),
                )
                result = self._process_periodic_conn(conn, telegram_id, due_at)
            elif event_type == "player":
                result = self._execute_player_action_conn(conn, telegram_id, due_at)
            else:
                result = self._execute_enemy_action_conn(conn, telegram_id, due_at)

            if result:
                last_result = result
            player = self._player(conn, telegram_id)
            if player["state"] != "combat":
                return result or {"finished": True}

        timeline = conn.execute(
            "SELECT opportunity_until FROM combat_timeline WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if timeline and float(timeline["opportunity_until"]) <= now:
            conn.execute(
                "UPDATE combat_timeline SET opportunity_kind = NULL, opportunity_until = 0 "
                "WHERE telegram_id = ?",
                (telegram_id,),
            )
        return last_result

    def _process_periodic_conn(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        tick_at: float,
    ) -> dict:
        player = self._player(conn, telegram_id)
        combat = conn.execute(
            "SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        timeline = conn.execute(
            "SELECT * FROM combat_timeline WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not combat or not timeline:
            return {}

        if float(timeline["stim_until"]) >= tick_at and int(player["hp"]) < self.max_hp(player):
            old_hp = int(player["hp"])
            new_hp = min(self.max_hp(player), old_hp + STIM_HEAL_PER_SECOND)
            conn.execute(
                "UPDATE players SET hp = ? WHERE telegram_id = ?", (new_hp, telegram_id)
            )
            self._log_conn(conn, telegram_id, f"💉 Стимулятор: +{new_hp - old_hp} HP.")
            player = self._player(conn, telegram_id)

        bleeding = int(combat["bleeding"])
        if bleeding > 0:
            new_hp = int(player["hp"]) - bleeding
            self._log_conn(conn, telegram_id, f"🩸 Кровотечение: -{bleeding} HP.")
            if new_hp <= 0:
                death = self._kill(conn, telegram_id)
                return {"text": death, "dead": True, "finished": True}
            conn.execute(
                "UPDATE players SET hp = ? WHERE telegram_id = ?", (new_hp, telegram_id)
            )
        return {}

    def _execute_player_action_conn(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        event_at: float,
    ) -> dict:
        player = self._player(conn, telegram_id)
        timeline = conn.execute(
            "SELECT * FROM combat_timeline WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        combat = conn.execute(
            "SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not timeline or not combat or not timeline["player_action"]:
            return {}

        action = str(timeline["player_action"])
        conn.execute(
            "UPDATE combat_timeline SET player_last_action_at = ?, player_action = NULL, "
            "player_action_due = NULL WHERE telegram_id = ?",
            (event_at, telegram_id),
        )
        enemy = ENEMIES[player["enemy_id"]]
        weapon = WEAPONS[player["weapon_id"]]
        distance = int(combat["distance"])

        if action in {"shoot", "aimed_shot"}:
            if int(player["ammo"]) <= 0:
                self._log_conn(conn, telegram_id, "🔫 Выстрел сорвался: патронов нет.")
            else:
                conn.execute(
                    "UPDATE players SET ammo = ammo - 1 WHERE telegram_id = ?", (telegram_id,)
                )
                aimed_bonus = 20 if action == "aimed_shot" else 0
                accuracy = min(
                    97 if action == "aimed_shot" else 95,
                    max(
                        15,
                        int(weapon["accuracy"])
                        + self.effective_attribute(player, "agility") * 4
                        + aimed_bonus,
                    ),
                )
                if self.rng.randint(1, 100) <= accuracy:
                    damage = max(
                        1,
                        int(weapon["damage"])
                        + self.effective_attribute(player, "agility") * 2
                        + self.rng.randint(-3, 4),
                    )
                    if action == "aimed_shot":
                        damage = max(1, round(damage * 1.1))
                    text = (
                        f"🎯 Прицельный выстрел: -{damage} HP."
                        if action == "aimed_shot"
                        else f"🔫 Выстрел: -{damage} HP."
                    )
                    self._log_conn(conn, telegram_id, text)
                    if self._damage_enemy(conn, telegram_id, damage):
                        return self._finish_combat(conn, telegram_id, enemy, [text]) | {"finished": True}
                else:
                    text = "🎯 Прицельный выстрел мимо." if action == "aimed_shot" else "🔫 Выстрел мимо."
                    self._log_conn(conn, telegram_id, text)

        elif action == "burst":
            if int(player["ammo"]) < 3:
                self._log_conn(conn, telegram_id, "💥 Очередь сорвалась: не хватает патронов.")
            else:
                conn.execute(
                    "UPDATE players SET ammo = ammo - 3 WHERE telegram_id = ?", (telegram_id,)
                )
                accuracy = min(
                    88,
                    max(
                        12,
                        int(weapon["accuracy"])
                        + self.effective_attribute(player, "agility") * 3
                        - 12,
                    ),
                )
                hits = 0
                total = 0
                for _ in range(3):
                    if self.rng.randint(1, 100) <= accuracy:
                        hits += 1
                        total += max(
                            1,
                            int(weapon["damage"]) // 2
                            + self.effective_attribute(player, "agility")
                            + self.rng.randint(-2, 3),
                        )
                if hits:
                    text = f"💥 Очередь: {hits}/3 попаданий, -{total} HP."
                    self._log_conn(conn, telegram_id, text)
                    if self._damage_enemy(conn, telegram_id, total):
                        return self._finish_combat(conn, telegram_id, enemy, [text]) | {"finished": True}
                else:
                    self._log_conn(conn, telegram_id, "💥 Очередь прошла мимо.")

        elif action == "melee":
            if distance > 1:
                self._log_conn(conn, telegram_id, "🔪 Удар сорвался: противник уже далеко.")
            else:
                accuracy = min(92, 45 + self.effective_attribute(player, "agility") * 5)
                if self.rng.randint(1, 100) <= accuracy:
                    damage = 7 + int(player["strength"]) * 4 + self.rng.randint(0, 5)
                    text = f"🔪 Ближний бой: -{damage} HP."
                    self._log_conn(conn, telegram_id, text)
                    if self._damage_enemy(conn, telegram_id, damage):
                        return self._finish_combat(conn, telegram_id, enemy, [text]) | {"finished": True}
                else:
                    self._log_conn(conn, telegram_id, "🔪 Удар не достиг цели.")

        elif action == "cover":
            conn.execute(
                "UPDATE combat_state SET cover = 1 WHERE telegram_id = ?", (telegram_id,)
            )
            self._log_conn(conn, telegram_id, "🧱 Ты занял укрытие.")

        elif action == "stim":
            conn.execute(
                "UPDATE combat_timeline SET stim_until = ? WHERE telegram_id = ?",
                (event_at + STIM_DURATION_SECONDS, telegram_id),
            )
            self._log_conn(conn, telegram_id, "💉 Стимулятор введён. Регенерация началась.")

        elif action == "medkit":
            if int(player["medkits"]) <= 0:
                self._log_conn(conn, telegram_id, "🩹 Аптечка сорвалась: аптечек нет.")
            else:
                heal = 30 + self.effective_attribute(player, "intelligence") * 4
                hp = min(self.max_hp(player), int(player["hp"]) + heal)
                restored = hp - int(player["hp"])
                conn.execute(
                    "UPDATE players SET medkits = medkits - 1, hp = ? WHERE telegram_id = ?",
                    (hp, telegram_id),
                )
                conn.execute(
                    "UPDATE combat_state SET bleeding = 0 WHERE telegram_id = ?", (telegram_id,)
                )
                self._log_conn(conn, telegram_id, f"🩹 Аптечка: +{restored} HP, кровь остановлена.")

        elif action == "flee":
            chance = max(
                15,
                min(
                    88,
                    28
                    + self.effective_attribute(player, "agility") * 8
                    - int(player["threat"]) // 8,
                ),
            )
            if self.rng.randint(1, 100) <= chance:
                return_state = str(combat["return_state"])
                conn.execute(
                    "UPDATE players SET state = ?, enemy_id = NULL, enemy_hp = NULL, aimed = 0 "
                    "WHERE telegram_id = ?",
                    (return_state, telegram_id),
                )
                conn.execute("DELETE FROM combat_state WHERE telegram_id = ?", (telegram_id,))
                self._cleanup_combat_runtime_conn(conn, telegram_id)
                return {"text": "Удалось оторваться.", "fled": True, "finished": True}
            self._log_conn(conn, telegram_id, "🏃 Отступление сорвалось.")

        self._maybe_spawn_opportunity_conn(conn, telegram_id, event_at)
        return {}

    def _execute_enemy_action_conn(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        event_at: float,
    ) -> dict:
        player = self._player(conn, telegram_id)
        timeline = conn.execute(
            "SELECT * FROM combat_timeline WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        combat = conn.execute(
            "SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not timeline or not combat:
            return {}

        enemy = ENEMIES[player["enemy_id"]]
        action = str(timeline["enemy_action"])
        distance = int(combat["distance"])

        if action == "approach":
            new_distance = max(1, distance - 1)
            conn.execute(
                "UPDATE combat_state SET distance = ?, cover = CASE WHEN ? <= 1 THEN 0 ELSE cover END "
                "WHERE telegram_id = ?",
                (new_distance, new_distance, telegram_id),
            )
            self._log_conn(conn, telegram_id, f"🏃 {enemy['name']} приблизился.")

        elif action == "retreat":
            new_distance = min(3, distance + 1)
            conn.execute(
                "UPDATE combat_state SET distance = ? WHERE telegram_id = ?",
                (new_distance, telegram_id),
            )
            self._log_conn(conn, telegram_id, f"↩️ {enemy['name']} увеличил дистанцию.")

        else:
            raw_damage = self.rng.randint(*enemy["damage"])
            if action == "ranged_attack" and bool(combat["cover"]):
                raw_damage = max(1, raw_damage - 5)
            damage = max(1, raw_damage - self.combat_damage_reduction(player))
            new_hp = int(player["hp"]) - damage
            icon = "🔫" if action == "ranged_attack" else "🔪"
            self._log_conn(conn, telegram_id, f"{icon} {enemy['name']}: -{damage} HP.")

            if int(enemy.get("bleed", 0)) > 0 and self.rng.randint(1, 100) <= int(enemy["bleed"]):
                conn.execute(
                    "UPDATE combat_state SET bleeding = MAX(bleeding, 2) WHERE telegram_id = ?",
                    (telegram_id,),
                )
                self._log_conn(conn, telegram_id, "🩸 Началось кровотечение.")

            if new_hp <= 0:
                death = self._kill(conn, telegram_id)
                return {"text": death, "dead": True, "finished": True}
            conn.execute(
                "UPDATE players SET hp = ? WHERE telegram_id = ?", (new_hp, telegram_id)
            )

        self._maybe_spawn_opportunity_conn(conn, telegram_id, event_at)
        player = self._player(conn, telegram_id)
        if player["state"] != "combat":
            return {"finished": True}
        next_action = self._choose_enemy_action_conn(conn, telegram_id, enemy)
        conn.execute(
            "UPDATE combat_timeline SET enemy_action = ?, enemy_action_due = ? WHERE telegram_id = ?",
            (next_action, event_at + ENEMY_ACTION_SECONDS[next_action], telegram_id),
        )
        return {}

    def _choose_enemy_action_conn(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        enemy: dict,
    ) -> str:
        combat = conn.execute(
            "SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not combat:
            return "melee_attack"
        distance = int(combat["distance"])
        if str(enemy["style"]) == "melee":
            return "approach" if distance > 1 else "melee_attack"
        if distance <= 1 and self.rng.random() < 0.55:
            return "retreat"
        return "ranged_attack"

    def _maybe_spawn_opportunity_conn(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        event_at: float,
    ) -> None:
        timeline = conn.execute(
            "SELECT * FROM combat_timeline WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not timeline:
            return
        if timeline["opportunity_kind"] and float(timeline["opportunity_until"]) > event_at:
            return
        if float(timeline["opportunity_cooldown_until"]) > event_at:
            return

        player = self._player(conn, telegram_id)
        combat = conn.execute(
            "SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not combat:
            return
        enemy = ENEMIES[player["enemy_id"]]
        choices: list[str] = []
        if str(enemy["style"]) == "ranged" and not bool(combat["cover"]):
            choices.append("cover")
        if int(player["hp"]) < self.max_hp(player):
            choices.append("stim")

        if not choices or self.rng.random() > OPPORTUNITY_CHANCE:
            conn.execute(
                "UPDATE combat_timeline SET opportunity_cooldown_until = ? WHERE telegram_id = ?",
                (event_at + 3.0, telegram_id),
            )
            return

        kind = self.rng.choice(choices)
        conn.execute(
            "UPDATE combat_timeline SET opportunity_kind = ?, opportunity_until = ?, "
            "opportunity_cooldown_until = ? WHERE telegram_id = ?",
            (
                kind,
                event_at + OPPORTUNITY_DURATION_SECONDS,
                event_at + OPPORTUNITY_COOLDOWN_SECONDS,
                telegram_id,
            ),
        )
        if kind == "cover":
            self._log_conn(conn, telegram_id, "🧱 Открылся удобный момент, чтобы занять укрытие.")
        else:
            self._log_conn(conn, telegram_id, "💉 Рядом найден уцелевший стимулятор.")
