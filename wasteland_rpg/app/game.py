from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass

from .content import ARMORS, ENEMIES, ITEMS, MAX_SKILL, SECTORS, WEAPONS, XP_PER_SKILL_POINT
from .db import Database


class GameError(RuntimeError):
    pass


@dataclass(frozen=True)
class LootResult:
    item_id: str
    qty: int
    taken: int


class GameService:
    def __init__(self, db: Database, rng: random.Random | None = None):
        self.db = db
        self.rng = rng or random.Random()

    def ensure_player(self, telegram_id: int, username: str | None = None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO players (telegram_id, username) VALUES (?, ?)",
                (telegram_id, username),
            )
            if username:
                conn.execute("UPDATE players SET username = ? WHERE telegram_id = ?", (username, telegram_id))
            player = self._player(conn, telegram_id)
            max_hp = self.max_hp(player)
            if player["state"] == "base" and player["hp"] != max_hp:
                conn.execute("UPDATE players SET hp = ? WHERE telegram_id = ?", (max_hp, telegram_id))

    def get_player(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            return dict(self._player(conn, telegram_id))

    def max_hp(self, player: sqlite3.Row | dict) -> int:
        return 92 + int(player["survival"]) * 8

    def carry_capacity(self, player: sqlite3.Row | dict) -> int:
        return 10 + int(player["survival"]) * 3

    def skill_points(self, player: sqlite3.Row | dict) -> int:
        earned = int(player["xp"]) // XP_PER_SKILL_POINT
        spent = int(player["combat"]) + int(player["scavenging"]) + int(player["survival"]) - 3
        return max(0, earned - spent)

    def field_weight(self, telegram_id: int) -> int:
        return self._inventory_weight(telegram_id, secured=0)

    def stash_value(self, telegram_id: int) -> int:
        return sum(row["qty"] * ITEMS[row["item_id"]]["value"] for row in self.inventory(telegram_id, secured=1))

    def inventory(self, telegram_id: int, *, secured: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT item_id, qty FROM inventory WHERE telegram_id = ? AND secured = ? AND qty > 0 ORDER BY item_id",
                (telegram_id, secured),
            ).fetchall()
        return [dict(row) for row in rows]

    def sector_unlocked(self, player: sqlite3.Row | dict, sector_id: str) -> bool:
        sector = SECTORS[sector_id]
        return int(player["successful_runs"]) >= sector["runs"] and int(player["survival"]) >= sector["survival"]

    def start_expedition(self, telegram_id: int, sector_id: str) -> str:
        if sector_id not in SECTORS:
            raise GameError("Неизвестный сектор.")
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Сначала закончи текущую вылазку.")
            if not self.sector_unlocked(player, sector_id):
                raise GameError("Этот сектор пока закрыт.")
            max_hp = self.max_hp(player)
            conn.execute(
                """
                UPDATE players
                SET state = 'expedition', sector_id = ?, hp = ?, threat = 0, steps = 0,
                    pending_event = NULL, enemy_id = NULL, enemy_hp = NULL, aimed = 0
                WHERE telegram_id = ?
                """,
                (sector_id, max_hp, telegram_id),
            )
            conn.execute("DELETE FROM inventory WHERE telegram_id = ? AND secured = 0", (telegram_id,))
        return f"Ты вышел в сектор «{SECTORS[sector_id]['name']}». Всё, что найдёшь до возвращения, можно потерять."

    def explore(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "expedition":
                raise GameError("Сейчас нельзя исследовать сектор.")
            if player["pending_event"]:
                raise GameError("Сначала разберись с текущей находкой.")

            threat_gain = self.rng.randint(5, 9)
            threat = min(100, int(player["threat"]) + threat_gain)
            steps = int(player["steps"]) + 1
            conn.execute(
                "UPDATE players SET threat = ?, steps = ? WHERE telegram_id = ?",
                (threat, steps, telegram_id),
            )
            player = self._player(conn, telegram_id)
            sector = SECTORS[player["sector_id"]]

            enemy_weight = 24 + sector["danger"] * 4 + threat // 7
            anomaly_weight = 10 + sector["danger"] * 4 + threat // 12
            cache_weight = 12 + int(player["scavenging"]) * 2
            loot_weight = max(28, 54 - threat // 5)
            quiet_weight = 8
            kind = self.rng.choices(
                ["loot", "enemy", "anomaly", "cache", "quiet"],
                weights=[loot_weight, enemy_weight, anomaly_weight, cache_weight, quiet_weight],
                k=1,
            )[0]

            if kind == "enemy":
                enemy_id = self.rng.choice(sector["enemies"])
                enemy = ENEMIES[enemy_id]
                hp_bonus = max(0, threat - 35) // 5
                enemy_hp = enemy["hp"] + hp_bonus
                conn.execute(
                    "UPDATE players SET state = 'combat', enemy_id = ?, enemy_hp = ?, aimed = 0 WHERE telegram_id = ?",
                    (enemy_id, enemy_hp, telegram_id),
                )
                return {"kind": "enemy", "text": f"Шум впереди оказался не пустяком: {enemy['name']}."}

            if kind in {"anomaly", "cache"}:
                conn.execute("UPDATE players SET pending_event = ? WHERE telegram_id = ?", (kind, telegram_id))
                text = (
                    "Датчик ловит нестабильность под слоем мусора. Внутри может быть редкий материал."
                    if kind == "anomaly"
                    else "Под плитой виден герметичный технический ящик. Замок старый, но вокруг слишком тихо."
                )
                return {"kind": kind, "text": text}

            if kind == "quiet":
                self._add_xp(conn, telegram_id, 1)
                return {"kind": "quiet", "text": "Пустой участок. Только ветер и следы тех, кто прошёл раньше."}

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

    def resolve_event(self, telegram_id: int, action: str) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "expedition" or not player["pending_event"]:
                raise GameError("Здесь уже нечего решать.")
            event = player["pending_event"]
            sector = SECTORS[player["sector_id"]]

            if action == "bypass":
                conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                return {"text": "Ты не стал испытывать удачу и обошёл место по широкой дуге."}

            if event == "anomaly":
                chance = min(88, 43 + int(player["scavenging"]) * 7 + int(player["survival"]) * 4 - sector["danger"] * 4)
                if self.rng.randint(1, 100) <= chance:
                    taken = self._add_field_item(conn, player, "shard", 1)
                    conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                    self._add_xp(conn, telegram_id, 12)
                    if taken:
                        return {"text": f"Контур удалось снять чисто. В рюкзаке {ITEMS['shard']['icon']} {ITEMS['shard']['name']}.", "success": True}
                    return {"text": "Контур удалось снять, но рюкзак забит. Осколок пришлось оставить.", "success": True}
                damage = self.rng.randint(16, 25) + sector["danger"] * 2
                conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                return self._apply_hazard_damage(conn, player, damage, "Поле дёрнулось раньше, чем показал датчик")

            if event == "cache":
                chance = min(92, 54 + int(player["scavenging"]) * 7 - sector["danger"] * 4)
                conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                if self.rng.randint(1, 100) <= chance:
                    item_id = self.rng.choice(sector["loot"])
                    qty = self.rng.randint(1, 2) + (1 if self.rng.random() < 0.25 else 0)
                    taken = self._add_field_item(conn, player, item_id, qty)
                    ammo = self.rng.randint(2, 5)
                    conn.execute("UPDATE players SET ammo = ammo + ? WHERE telegram_id = ?", (ammo, telegram_id))
                    self._add_xp(conn, telegram_id, 7)
                    item = ITEMS[item_id]
                    return {"text": f"Ящик вскрыт без шума: {item['icon']} {item['name']} ×{taken} и 🔫 патроны ×{ammo}.", "success": True}
                damage = self.rng.randint(7, 13) + sector["danger"]
                return self._apply_hazard_damage(conn, player, damage, "Сработала примитивная растяжка")

            raise GameError("Неизвестное событие.")

    def combat_action(self, telegram_id: int, action: str) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "combat" or not player["enemy_id"]:
                raise GameError("Бой уже закончен.")
            enemy = ENEMIES[player["enemy_id"]]
            weapon = WEAPONS[player["weapon_id"]]
            sector = SECTORS[player["sector_id"]]
            lines: list[str] = []

            if action == "shoot":
                if int(player["ammo"]) <= 0:
                    raise GameError("Патроны закончились.")
                aimed_bonus = 20 if player["aimed"] else 0
                accuracy = min(95, weapon["accuracy"] + int(player["combat"]) * 4 + aimed_bonus - sector["danger"] * 3)
                conn.execute("UPDATE players SET ammo = ammo - 1, aimed = 0 WHERE telegram_id = ?", (telegram_id,))
                if self.rng.randint(1, 100) <= accuracy:
                    damage = max(1, weapon["damage"] + int(player["combat"]) * 2 + self.rng.randint(-3, 4))
                    lines.append(f"Выстрел попал: -{damage} HP.")
                    won = self._damage_enemy(conn, telegram_id, damage)
                    if won:
                        return self._finish_combat(conn, telegram_id, enemy, lines)
                else:
                    lines.append("Выстрел ушёл мимо.")

            elif action == "aim":
                if player["aimed"]:
                    raise GameError("Ты уже держишь цель на мушке.")
                conn.execute("UPDATE players SET aimed = 1 WHERE telegram_id = ?", (telegram_id,))
                lines.append("Ты выждал момент. Следующий выстрел получит +20% к точности.")

            elif action == "melee":
                accuracy = min(88, 52 + int(player["combat"]) * 5)
                if self.rng.randint(1, 100) <= accuracy:
                    damage = 7 + int(player["combat"]) * 3 + self.rng.randint(0, 5)
                    lines.append(f"Удар вблизи: -{damage} HP.")
                    won = self._damage_enemy(conn, telegram_id, damage)
                    if won:
                        return self._finish_combat(conn, telegram_id, enemy, lines)
                else:
                    lines.append("Подойти чисто не получилось.")

            elif action == "medkit":
                if int(player["medkits"]) <= 0:
                    raise GameError("Аптечек нет.")
                heal = 30 + int(player["survival"]) * 4
                hp = min(self.max_hp(player), int(player["hp"]) + heal)
                conn.execute("UPDATE players SET medkits = medkits - 1, hp = ? WHERE telegram_id = ?", (hp, telegram_id))
                lines.append(f"Аптечка: HP восстановлено до {hp}.")

            elif action == "flee":
                chance = max(15, min(82, 34 + int(player["survival"]) * 8 - sector["danger"] * 5 - int(player["threat"]) // 8))
                if self.rng.randint(1, 100) <= chance:
                    conn.execute(
                        "UPDATE players SET state = 'expedition', enemy_id = NULL, enemy_hp = NULL, aimed = 0, threat = MIN(100, threat + 5) WHERE telegram_id = ?",
                        (telegram_id,),
                    )
                    return {"text": f"Удалось оторваться. Шанс был {chance}%.", "fled": True}
                lines.append(f"Отступление сорвалось. Шанс был {chance}%.")

            else:
                raise GameError("Неизвестное боевое действие.")

            player = self._player(conn, telegram_id)
            enemy_damage = self.rng.randint(*enemy["damage"])
            reduction = ARMORS[player["armor_id"]]["reduction"]
            damage = max(1, enemy_damage - reduction)
            new_hp = int(player["hp"]) - damage
            lines.append(f"{enemy['name']} отвечает: -{damage} HP.")
            if new_hp <= 0:
                death_text = self._kill(conn, telegram_id)
                lines.append(death_text)
                return {"text": "\n".join(lines), "dead": True}
            conn.execute("UPDATE players SET hp = ? WHERE telegram_id = ?", (new_hp, telegram_id))
            return {"text": "\n".join(lines)}

    def return_base(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "expedition":
                raise GameError("Сейчас нельзя вернуться в Приют.")
            field_rows = conn.execute(
                "SELECT item_id, qty FROM inventory WHERE telegram_id = ? AND secured = 0 AND qty > 0",
                (telegram_id,),
            ).fetchall()
            value = sum(row["qty"] * ITEMS[row["item_id"]]["value"] for row in field_rows)
            for row in field_rows:
                self._change_item(conn, telegram_id, row["item_id"], int(row["qty"]), secured=1)
            conn.execute("DELETE FROM inventory WHERE telegram_id = ? AND secured = 0", (telegram_id,))
            max_hp = self.max_hp(player)
            conn.execute(
                """
                UPDATE players
                SET state = 'base', sector_id = NULL, threat = 0, steps = 0, pending_event = NULL,
                    enemy_id = NULL, enemy_hp = NULL, aimed = 0, successful_runs = successful_runs + 1, hp = ?
                WHERE telegram_id = ?
                """,
                (max_hp, telegram_id),
            )
            self._add_xp(conn, telegram_id, 4)
        return {"text": f"Вылазка завершена. Добыча закреплена на складе; её стоимость по текущему прайсу — {value} жет.", "value": value}

    def upgrade_skill(self, telegram_id: int, skill: str) -> str:
        if skill not in {"combat", "scavenging", "survival"}:
            raise GameError("Неизвестный навык.")
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Прокачиваться можно только в Приюте.")
            if self.skill_points(player) <= 0:
                raise GameError("Свободных очков навыков нет.")
            if int(player[skill]) >= MAX_SKILL:
                raise GameError("Навык уже на максимуме.")
            conn.execute(f"UPDATE players SET {skill} = {skill} + 1 WHERE telegram_id = ?", (telegram_id,))
            if skill == "survival":
                updated = self._player(conn, telegram_id)
                conn.execute("UPDATE players SET hp = ? WHERE telegram_id = ?", (self.max_hp(updated), telegram_id))
        names = {"combat": "Бой", "scavenging": "Поиск", "survival": "Выживание"}
        return f"Навык «{names[skill]}» повышен."

    def sell_all(self, telegram_id: int) -> str:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Торговать можно только в Приюте.")
            rows = conn.execute(
                "SELECT item_id, qty FROM inventory WHERE telegram_id = ? AND secured = 1 AND qty > 0",
                (telegram_id,),
            ).fetchall()
            total = sum(int(row["qty"]) * ITEMS[row["item_id"]]["value"] for row in rows)
            if total <= 0:
                raise GameError("На складе нет ресурсов для продажи.")
            conn.execute("DELETE FROM inventory WHERE telegram_id = ? AND secured = 1", (telegram_id,))
            conn.execute("UPDATE players SET credits = credits + ? WHERE telegram_id = ?", (total, telegram_id))
        return f"Склад продан за {total} жет."

    def buy(self, telegram_id: int, product: str) -> str:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Покупать можно только в Приюте.")

            if product == "ammo":
                price, qty, label = 24, 6, "Патроны ×6"
                self._charge(conn, player, price)
                conn.execute("UPDATE players SET ammo = ammo + ? WHERE telegram_id = ?", (qty, telegram_id))
                return f"Куплено: {label} за {price} жет."
            if product == "medkit":
                price, label = 32, "Аптечка"
                self._charge(conn, player, price)
                conn.execute("UPDATE players SET medkits = medkits + 1 WHERE telegram_id = ?", (telegram_id,))
                return f"Куплено: {label} за {price} жет."
            if product in WEAPONS:
                item = WEAPONS[product]
                if item["order"] <= WEAPONS[player["weapon_id"]]["order"]:
                    raise GameError("Это оружие не лучше текущего.")
                self._charge(conn, player, item["price"])
                conn.execute("UPDATE players SET weapon_id = ? WHERE telegram_id = ?", (product, telegram_id))
                return f"Куплено оружие: {item['name']}."
            if product in ARMORS:
                item = ARMORS[product]
                if item["order"] <= ARMORS[player["armor_id"]]["order"]:
                    raise GameError("Эта броня не лучше текущей.")
                self._charge(conn, player, item["price"])
                conn.execute("UPDATE players SET armor_id = ? WHERE telegram_id = ?", (product, telegram_id))
                return f"Куплена броня: {item['name']}."
            raise GameError("Неизвестный товар.")

    def _finish_combat(self, conn: sqlite3.Connection, telegram_id: int, enemy: dict, lines: list[str]) -> dict:
        player = self._player(conn, telegram_id)
        loot_id = enemy["loot"]
        taken = self._add_field_item(conn, player, loot_id, 1)
        self._add_xp(conn, telegram_id, enemy["xp"])
        conn.execute(
            "UPDATE players SET state = 'expedition', enemy_id = NULL, enemy_hp = NULL, aimed = 0 WHERE telegram_id = ?",
            (telegram_id,),
        )
        loot_text = f" Добыча: {ITEMS[loot_id]['icon']} {ITEMS[loot_id]['name']} ×{taken}." if taken else " Рюкзак забит — добычу пришлось оставить."
        lines.append(f"Противник устранён. +{enemy['xp']} опыта.{loot_text}")
        return {"text": "\n".join(lines), "won": True}

    def _damage_enemy(self, conn: sqlite3.Connection, telegram_id: int, damage: int) -> bool:
        player = self._player(conn, telegram_id)
        hp = int(player["enemy_hp"]) - damage
        conn.execute("UPDATE players SET enemy_hp = ? WHERE telegram_id = ?", (max(0, hp), telegram_id))
        return hp <= 0

    def _apply_hazard_damage(self, conn: sqlite3.Connection, player: sqlite3.Row, damage: int, prefix: str) -> dict:
        new_hp = int(player["hp"]) - damage
        if new_hp <= 0:
            death_text = self._kill(conn, int(player["telegram_id"]))
            return {"text": f"{prefix}: -{damage} HP.\n{death_text}", "dead": True}
        conn.execute("UPDATE players SET hp = ? WHERE telegram_id = ?", (new_hp, player["telegram_id"]))
        return {"text": f"{prefix}: -{damage} HP.", "success": False}

    def _kill(self, conn: sqlite3.Connection, telegram_id: int) -> str:
        player = self._player(conn, telegram_id)
        conn.execute("DELETE FROM inventory WHERE telegram_id = ? AND secured = 0", (telegram_id,))
        max_hp = self.max_hp(player)
        conn.execute(
            """
            UPDATE players
            SET state = 'base', sector_id = NULL, hp = ?, threat = 0, steps = 0,
                pending_event = NULL, enemy_id = NULL, enemy_hp = NULL, aimed = 0,
                deaths = deaths + 1, ammo = MAX(3, ammo - 3), medkits = MAX(0, medkits - 1)
            WHERE telegram_id = ?
            """,
            (max_hp, telegram_id),
        )
        return "Ты не вернулся своим ходом. Незакреплённая добыча потеряна; часть расходников тоже пропала."

    def _roll_loot(self, conn: sqlite3.Connection, player: sqlite3.Row) -> LootResult:
        sector = SECTORS[player["sector_id"]]
        pool = list(sector["loot"])
        rare_bonus = int(player["scavenging"]) - 1
        if rare_bonus > 0 and sector["danger"] >= 2:
            pool.extend(["parts"] * rare_bonus)
        if sector["danger"] >= 3:
            pool.extend(["shard"] * max(0, int(player["scavenging"]) - 2))
        item_id = self.rng.choice(pool)
        qty = 1 + (1 if self.rng.random() < 0.35 + int(player["scavenging"]) * 0.05 else 0)
        taken = self._add_field_item(conn, player, item_id, qty)
        return LootResult(item_id=item_id, qty=qty, taken=taken)

    def _add_field_item(self, conn: sqlite3.Connection, player: sqlite3.Row, item_id: str, qty: int) -> int:
        current_weight = self._inventory_weight_conn(conn, int(player["telegram_id"]), secured=0)
        capacity = self.carry_capacity(player)
        unit_weight = ITEMS[item_id]["weight"]
        can_take = max(0, (capacity - current_weight) // unit_weight)
        taken = min(qty, can_take)
        if taken > 0:
            self._change_item(conn, int(player["telegram_id"]), item_id, taken, secured=0)
        return taken

    def _change_item(self, conn: sqlite3.Connection, telegram_id: int, item_id: str, qty: int, *, secured: int) -> None:
        conn.execute(
            """
            INSERT INTO inventory (telegram_id, item_id, secured, qty) VALUES (?, ?, ?, ?)
            ON CONFLICT (telegram_id, item_id, secured)
            DO UPDATE SET qty = qty + excluded.qty
            """,
            (telegram_id, item_id, secured, qty),
        )

    def _inventory_weight(self, telegram_id: int, *, secured: int) -> int:
        with self.db.connect() as conn:
            return self._inventory_weight_conn(conn, telegram_id, secured=secured)

    def _inventory_weight_conn(self, conn: sqlite3.Connection, telegram_id: int, *, secured: int) -> int:
        rows = conn.execute(
            "SELECT item_id, qty FROM inventory WHERE telegram_id = ? AND secured = ? AND qty > 0",
            (telegram_id, secured),
        ).fetchall()
        return sum(int(row["qty"]) * ITEMS[row["item_id"]]["weight"] for row in rows)

    def _add_xp(self, conn: sqlite3.Connection, telegram_id: int, amount: int) -> None:
        if amount > 0:
            conn.execute("UPDATE players SET xp = xp + ? WHERE telegram_id = ?", (amount, telegram_id))

    def _charge(self, conn: sqlite3.Connection, player: sqlite3.Row, price: int) -> None:
        if int(player["credits"]) < price:
            raise GameError("Не хватает жетонов.")
        conn.execute("UPDATE players SET credits = credits - ? WHERE telegram_id = ?", (price, player["telegram_id"]))

    @staticmethod
    def _player(conn: sqlite3.Connection, telegram_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if not row:
            raise GameError("Персонаж не найден. Нажми /start.")
        return row
