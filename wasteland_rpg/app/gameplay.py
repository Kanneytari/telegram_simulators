from __future__ import annotations

import sqlite3

from .content import ENEMIES, EXPEDITION_SCENES, ITEMS, ROUTES, SECTORS, WEAPONS
from .event_pools import EXPEDITION_EVENTS, ROAD_EVENTS
from .game import GameError, GameService as BaseGameService


class GameService(BaseGameService):
    """Current gameplay rules layered over the stable core service."""

    def start_expedition(self, telegram_id: int, sector_id: str) -> str:
        message = super().start_expedition(telegram_id, sector_id)
        self._reset_event_rotation(telegram_id, "expedition")
        return message

    def start_travel(self, telegram_id: int, route_id: str) -> str:
        message = super().start_travel(telegram_id, route_id)
        self._reset_event_rotation(telegram_id, "travel")
        return message

    def event_weights(self, telegram_id: int, context: str) -> dict[str, int]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT event_key, current_weight FROM event_weights "
                "WHERE telegram_id = ? AND context = ? ORDER BY event_key",
                (telegram_id, context),
            ).fetchall()
        return {str(row["event_key"]): int(row["current_weight"]) for row in rows}

    def _reset_event_rotation(self, telegram_id: int, context: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "DELETE FROM event_weights WHERE telegram_id = ? AND context = ?",
                (telegram_id, context),
            )

    def _pick_rotating_event(
        self,
        conn: sqlite3.Connection,
        telegram_id: int,
        context: str,
        pool: dict[str, dict[str, int]],
        *,
        modifiers: dict[str, int] | None = None,
    ) -> str:
        for event_key, meta in pool.items():
            conn.execute(
                "INSERT OR IGNORE INTO event_weights "
                "(telegram_id, context, event_key, current_weight) VALUES (?, ?, ?, ?)",
                (telegram_id, context, event_key, int(meta["base"])),
            )

        rows = conn.execute(
            "SELECT event_key, current_weight FROM event_weights "
            "WHERE telegram_id = ? AND context = ?",
            (telegram_id, context),
        ).fetchall()
        current = {str(row["event_key"]): int(row["current_weight"]) for row in rows}

        keys = list(pool)
        effective: list[int] = []
        for key in keys:
            weight = current.get(key, int(pool[key]["base"]))
            if weight <= 0:
                effective.append(0)
                continue
            effective.append(max(1, weight + int((modifiers or {}).get(key, 0))))

        if sum(effective) <= 0:
            # Защитный fallback для изменённого в будущем слишком маленького пула.
            effective = [int(pool[key]["base"]) for key in keys]

        selected = self.rng.choices(keys, weights=effective, k=1)[0]

        # Восстановление происходит ПОСЛЕ выбора. Поэтому событие, которое
        # выпало на прошлом шаге, имеет вес 0 на текущем и не может повториться
        # два шага подряд. После пропущенного шага оно начинает возвращаться.
        for key in keys:
            if key == selected:
                new_weight = 0
            else:
                new_weight = min(
                    int(pool[key]["base"]),
                    current.get(key, int(pool[key]["base"])) + int(pool[key]["recovery"]),
                )
            conn.execute(
                "UPDATE event_weights SET current_weight = ? "
                "WHERE telegram_id = ? AND context = ? AND event_key = ?",
                (new_weight, telegram_id, context, key),
            )
        return selected

    def explore(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "expedition":
                raise GameError("Сейчас нельзя исследовать сектор.")
            if player["pending_event"]:
                raise GameError("Сначала разберись с текущим событием.")

            threat = min(100, int(player["threat"]) + self.rng.randint(5, 9))
            steps = int(player["steps"]) + 1
            conn.execute(
                "UPDATE players SET threat = ?, steps = ? WHERE telegram_id = ?",
                (threat, steps, telegram_id),
            )
            player = self._player(conn, telegram_id)
            sector = SECTORS[player["sector_id"]]
            danger = int(sector["danger"])

            modifiers = {
                "enemy": danger * 3 + threat // 18,
                "anomaly": danger * 2,
                "cache": self.effective_attribute(player, "perception"),
                "loot": -(threat // 15),
            }
            event_key = self._pick_rotating_event(
                conn,
                telegram_id,
                "expedition",
                EXPEDITION_EVENTS,
                modifiers=modifiers,
            )

            if event_key.startswith("scene:"):
                scene_id = event_key.split(":", 1)[1]
                if scene_id not in EXPEDITION_SCENES:
                    raise GameError("Неизвестная сценарная встреча.")
                conn.execute(
                    "UPDATE players SET pending_event = ? WHERE telegram_id = ?",
                    (event_key, telegram_id),
                )
                return {
                    "kind": "choice",
                    "scene": scene_id,
                    "text": "Впереди есть несколько вариантов пути.",
                }

            if event_key == "enemy":
                enemy_id = self.rng.choice(sector["enemies"])
                self._start_combat(conn, telegram_id, enemy_id, return_state="expedition")
                return {
                    "kind": "enemy",
                    "text": f"Шум впереди оказался не пустяком: {ENEMIES[enemy_id]['name']}.",
                }

            if event_key in {"anomaly", "cache"}:
                conn.execute(
                    "UPDATE players SET pending_event = ? WHERE telegram_id = ?",
                    (event_key, telegram_id),
                )
                text = (
                    "Датчик ловит нестабильность под слоем мусора. Внутри может быть редкий материал."
                    if event_key == "anomaly"
                    else "Под плитой виден герметичный технический ящик. Замок старый, но вокруг слишком тихо."
                )
                return {"kind": event_key, "text": text}

            if event_key == "quiet":
                self._add_xp(conn, telegram_id, 1)
                return {
                    "kind": "quiet",
                    "text": "Пустой участок. Только ветер и следы тех, кто прошёл раньше.",
                }

            result = self._roll_loot(conn, player)
            item = ITEMS[result.item_id]
            self._add_xp(conn, telegram_id, 2 if result.taken else 0)
            if result.taken == 0:
                text = f"Нашёл: {item['icon']} {item['name']} ×{result.qty}, но рюкзак уже забит."
            elif result.taken < result.qty:
                text = f"Нашёл: {item['icon']} {item['name']} ×{result.qty}. Влезло только ×{result.taken}."
            else:
                text = f"Нашёл: {item['icon']} {item['name']} ×{result.taken}."
            return {"kind": "loot", "text": text}

    def advance_travel(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "travel":
                raise GameError("Сейчас ты не в дороге.")
            travel = conn.execute(
                "SELECT * FROM travel WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if not travel:
                raise GameError("Маршрут не найден.")

            route = ROUTES[travel["route_id"]]
            if int(travel["step"]) >= int(route["stages"]):
                return self._arrive(conn, telegram_id, travel)

            step = int(travel["step"]) + 1
            conn.execute(
                "UPDATE travel SET step = ? WHERE telegram_id = ?", (step, telegram_id)
            )
            danger = int(route["danger"])
            event_key = self._pick_rotating_event(
                conn,
                telegram_id,
                "travel",
                ROAD_EVENTS,
                modifiers={"enemy": danger * 4},
            )

            if event_key == "enemy":
                enemy_pool = ["bone_dog", "scavenger"]
                if danger >= 2:
                    enemy_pool += ["crawler", "raider"]
                if danger >= 3:
                    enemy_pool += ["stitched"]
                enemy_id = self.rng.choice(enemy_pool)
                self._start_combat(conn, telegram_id, enemy_id, return_state="travel")
                return {
                    "kind": "combat",
                    "text": f"На {step}-м участке дорогу перекрыл {ENEMIES[enemy_id]['name']}.",
                }

            if event_key == "loot":
                item_id = self.rng.choice(["scrap", "wire", "chem", "parts"])
                qty = self.rng.randint(1, 2)
                taken = self._add_cargo_item_conn(conn, player, item_id, qty)
                self._add_xp(conn, telegram_id, 1 if taken else 0)
                if taken:
                    return {
                        "kind": "loot",
                        "text": f"У дороги найдено: {ITEMS[item_id]['icon']} {ITEMS[item_id]['name']} ×{taken}.",
                    }
                return {
                    "kind": "quiet",
                    "text": "Нашлась полезная мелочь, но груз уже некуда класть.",
                }

            if event_key == "wreck":
                item_id = self.rng.choice(["scrap", "wire", "parts"])
                qty = self.rng.randint(2, 3)
                taken = self._add_cargo_item_conn(conn, player, item_id, qty)
                self._add_xp(conn, telegram_id, 2 if taken else 0)
                if taken:
                    return {
                        "kind": "wreck",
                        "text": f"У обочины найден брошенный транспорт. Из него удалось снять {ITEMS[item_id]['icon']} {ITEMS[item_id]['name']} ×{taken}.",
                    }
                return {
                    "kind": "wreck",
                    "text": "Брошенный транспорт оказался полезным, но для находок уже нет места в грузе.",
                }

            if event_key == "supply_cache":
                ammo = self.rng.randint(3, 6)
                conn.execute(
                    "UPDATE players SET ammo = ammo + ? WHERE telegram_id = ?",
                    (ammo, telegram_id),
                )
                item_id = self.rng.choice(["chem", "parts"])
                taken = self._add_cargo_item_conn(conn, player, item_id, 1)
                medkit = 1 if self.rng.random() < 0.35 else 0
                if medkit:
                    conn.execute(
                        "UPDATE players SET medkits = medkits + 1 WHERE telegram_id = ?",
                        (telegram_id,),
                    )
                self._add_xp(conn, telegram_id, 4)
                extras = f", 🩹 аптечка ×1" if medkit else ""
                cargo_text = (
                    f", {ITEMS[item_id]['icon']} {ITEMS[item_id]['name']} ×{taken}"
                    if taken
                    else ""
                )
                return {
                    "kind": "supply_cache",
                    "text": f"Редкая находка: запечатанный аварийный ящик. 🔫 патроны ×{ammo}{cargo_text}{extras}.",
                }

            self._add_xp(conn, telegram_id, 1)
            return {
                "kind": "quiet",
                "text": f"Участок {step}/{route['stages']} пройден без происшествий.",
            }

    def combat_action(self, telegram_id: int, action: str) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "combat" or not player["enemy_id"]:
                raise GameError("Бой уже закончен.")
            enemy = ENEMIES[player["enemy_id"]]
            weapon = WEAPONS[player["weapon_id"]]
            combat = conn.execute(
                "SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if not combat:
                raise GameError("Состояние боя потеряно.")

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
                player = self._player(conn, telegram_id)

            distance = int(combat["distance"])
            cover = bool(combat["cover"])

            if action == "shoot":
                if int(player["ammo"]) <= 0:
                    raise GameError("Патроны закончились.")
                conn.execute(
                    "UPDATE players SET ammo = ammo - 1, aimed = 0 WHERE telegram_id = ?",
                    (telegram_id,),
                )
                accuracy = min(
                    95,
                    max(
                        15,
                        int(weapon["accuracy"])
                        + self.effective_attribute(player, "agility") * 4,
                    ),
                )
                if self.rng.randint(1, 100) <= accuracy:
                    damage = max(
                        1,
                        int(weapon["damage"])
                        + self.effective_attribute(player, "agility") * 2
                        + self.rng.randint(-3, 4),
                    )
                    lines.append(f"Выстрел попал: -{damage} HP.")
                    if self._damage_enemy(conn, telegram_id, damage):
                        return self._finish_combat(conn, telegram_id, enemy, lines)
                else:
                    lines.append("Выстрел ушёл мимо.")

            elif action == "burst":
                if "burst" not in weapon.get("modes", ()):
                    raise GameError("Это оружие не умеет стрелять очередью.")
                if int(player["ammo"]) < 3:
                    raise GameError("Для очереди нужно минимум 3 патрона.")
                conn.execute(
                    "UPDATE players SET ammo = ammo - 3, aimed = 0 WHERE telegram_id = ?",
                    (telegram_id,),
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
                    lines.append(f"Очередь: попаданий {hits}/3, урон -{total} HP.")
                    if self._damage_enemy(conn, telegram_id, total):
                        return self._finish_combat(conn, telegram_id, enemy, lines)
                else:
                    lines.append("Очередь прошла мимо цели.")

            elif action == "melee":
                if distance > 1:
                    raise GameError("Противник ещё не подошёл вплотную.")
                accuracy = min(92, 45 + self.effective_attribute(player, "agility") * 5)
                if self.rng.randint(1, 100) <= accuracy:
                    damage = 7 + int(player["strength"]) * 4 + self.rng.randint(0, 5)
                    lines.append(f"Удар вблизи: -{damage} HP.")
                    if self._damage_enemy(conn, telegram_id, damage):
                        return self._finish_combat(conn, telegram_id, enemy, lines)
                else:
                    lines.append("Удар не достиг цели.")

            elif action == "cover":
                if str(enemy["style"]) != "ranged":
                    raise GameError("Против этого врага укрытие почти не поможет.")
                if cover:
                    raise GameError("Ты уже в укрытии.")
                conn.execute(
                    "UPDATE combat_state SET cover = 1 WHERE telegram_id = ?",
                    (telegram_id,),
                )
                lines.append("Ты занял укрытие. Огонь стрелка станет менее опасным.")

            elif action == "medkit":
                if int(player["medkits"]) <= 0:
                    raise GameError("Аптечек нет.")
                heal = 30 + self.effective_attribute(player, "intelligence") * 4
                hp = min(self.max_hp(player), int(player["hp"]) + heal)
                conn.execute(
                    "UPDATE players SET medkits = medkits - 1, hp = ? WHERE telegram_id = ?",
                    (hp, telegram_id),
                )
                conn.execute(
                    "UPDATE combat_state SET bleeding = 0 WHERE telegram_id = ?",
                    (telegram_id,),
                )
                lines.append(
                    f"Аптечка: здоровье восстановлено до {hp}, кровотечение остановлено."
                )

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
                    conn.execute(
                        "DELETE FROM combat_state WHERE telegram_id = ?", (telegram_id,)
                    )
                    return {
                        "text": f"Удалось оторваться. Шанс был {chance}%.",
                        "fled": True,
                    }
                lines.append(f"Отступление сорвалось. Шанс был {chance}%.")

            elif action in {"aim", "approach"}:
                raise GameError("Это действие больше не используется в новой системе боя.")
            else:
                raise GameError("Неизвестное боевое действие.")

            enemy_result = self._enemy_turn(conn, telegram_id, enemy)
            if enemy_result.get("text"):
                lines.append(enemy_result["text"])
            if enemy_result.get("dead"):
                return {"text": "\n".join(lines), "dead": True}
            return {"text": "\n".join(lines)}
