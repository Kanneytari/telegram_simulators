from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass

from .content import (
    ARMORS,
    ATTRIBUTES,
    BACKPACKS,
    ENEMIES,
    EXPEDITION_SCENES,
    GADGETS,
    HEADGEAR,
    ITEMS,
    LOCATIONS,
    ROUTES,
    SECTORS,
    WEAPONS,
    XP_PER_LEVEL,
)
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
            conn.execute("INSERT OR IGNORE INTO players (telegram_id, username) VALUES (?, ?)", (telegram_id, username))
            if username:
                conn.execute("UPDATE players SET username = ? WHERE telegram_id = ?", (username, telegram_id))
            conn.execute("INSERT OR IGNORE INTO player_world (telegram_id) VALUES (?)", (telegram_id,))
            conn.execute("INSERT OR IGNORE INTO visited_locations (telegram_id, location_id) VALUES (?, 'refuge7')", (telegram_id,))
            conn.execute("INSERT OR IGNORE INTO equipment (telegram_id) VALUES (?)", (telegram_id,))
            player = self._player(conn, telegram_id)
            if player["state"] == "base" and player["hp"] != self.max_hp(player):
                conn.execute("UPDATE players SET hp = ? WHERE telegram_id = ?", (self.max_hp(player), telegram_id))

    def get_player(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            return dict(self._player(conn, telegram_id))

    def level(self, player: sqlite3.Row | dict) -> int:
        return int(player["xp"]) // XP_PER_LEVEL + 1

    def max_hp(self, player: sqlite3.Row | dict) -> int:
        return 20 + self.level(player) * 20

    def attribute_points(self, player: sqlite3.Row | dict) -> int:
        earned = self.level(player) - 1
        spent = sum(int(player[key]) - 1 for key in ATTRIBUTES)
        return max(0, earned - spent)

    def effective_attribute(self, player: sqlite3.Row | dict, attribute: str) -> int:
        value = int(player[attribute])
        equipment = self.equipment(int(player["telegram_id"]))
        value += int(HEADGEAR[equipment["headgear_id"]].get("bonuses", {}).get(attribute, 0))
        value += int(GADGETS[equipment["gadget_id"]].get("bonuses", {}).get(attribute, 0))
        return value

    def upgrade_attribute(self, telegram_id: int, attribute: str) -> str:
        if attribute not in ATTRIBUTES:
            raise GameError("Неизвестная характеристика.")
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Распределять характеристики можно только в безопасном поселении.")
            if self.attribute_points(player) <= 0:
                raise GameError("Свободных очков характеристик нет.")
            conn.execute(f"UPDATE players SET {attribute} = {attribute} + 1 WHERE telegram_id = ?", (telegram_id,))
            value = int(player[attribute]) + 1
        return f"Характеристика «{ATTRIBUTES[attribute]['name']}» повышена до {value}."

    def location_id(self, telegram_id: int) -> str:
        with self.db.connect() as conn:
            return self._location_id(conn, telegram_id)

    def location(self, telegram_id: int) -> dict:
        return LOCATIONS[self.location_id(telegram_id)]

    def visited_locations(self, telegram_id: int) -> set[str]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT location_id FROM visited_locations WHERE telegram_id = ?", (telegram_id,)).fetchall()
        return {str(row["location_id"]) for row in rows}

    def connected_routes(self, telegram_id: int) -> list[dict]:
        current = self.location_id(telegram_id)
        player = self.get_player(telegram_id)
        rows = []
        for route_id, route in ROUTES.items():
            if current not in {route["a"], route["b"]}:
                continue
            target = route["b"] if current == route["a"] else route["a"]
            rows.append({"id": route_id, **route, "target": target, "unlocked": self.level(player) >= int(route["level"])})
        return rows

    def travel_state(self, telegram_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM travel WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return dict(row) if row else None

    def start_travel(self, telegram_id: int, route_id: str) -> str:
        if route_id not in ROUTES:
            raise GameError("Неизвестный маршрут.")
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Сначала закончи текущее действие.")
            current = self._location_id(conn, telegram_id)
            route = ROUTES[route_id]
            if current not in {route["a"], route["b"]}:
                raise GameError("Этот маршрут отсюда недоступен.")
            if self.level(player) < int(route["level"]):
                raise GameError(f"Для этого маршрута нужен уровень {route['level']}.")
            target = route["b"] if current == route["a"] else route["a"]
            conn.execute("INSERT OR REPLACE INTO travel (telegram_id, route_id, origin_id, target_id, step) VALUES (?, ?, ?, ?, 0)", (telegram_id, route_id, current, target))
            conn.execute("UPDATE players SET state = 'travel', pending_event = NULL, threat = 0, steps = 0 WHERE telegram_id = ?", (telegram_id,))
        return f"Ты вышел на маршрут «{route['name']}» в сторону {LOCATIONS[target]['name']}."

    def advance_travel(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "travel":
                raise GameError("Сейчас ты не в дороге.")
            travel = conn.execute("SELECT * FROM travel WHERE telegram_id = ?", (telegram_id,)).fetchone()
            if not travel:
                raise GameError("Маршрут не найден.")
            route = ROUTES[travel["route_id"]]
            if int(travel["step"]) >= int(route["stages"]):
                return self._arrive(conn, telegram_id, travel)
            step = int(travel["step"]) + 1
            conn.execute("UPDATE travel SET step = ? WHERE telegram_id = ?", (step, telegram_id))
            roll = self.rng.random()
            danger = int(route["danger"])
            if roll < 0.30 + danger * 0.06:
                enemy_pool = ["bone_dog", "scavenger"]
                if danger >= 2:
                    enemy_pool += ["crawler", "raider"]
                if danger >= 3:
                    enemy_pool += ["stitched"]
                enemy_id = self.rng.choice(enemy_pool)
                self._start_combat(conn, telegram_id, enemy_id, return_state="travel")
                return {"kind": "combat", "text": f"На {step}-м участке дорогу перекрыл {ENEMIES[enemy_id]['name']}."}
            if roll < 0.63:
                item_id = self.rng.choice(["scrap", "wire", "chem", "parts"])
                qty = self.rng.randint(1, 2)
                taken = self._add_cargo_item_conn(conn, player, item_id, qty)
                self._add_xp(conn, telegram_id, 1 if taken else 0)
                if taken:
                    return {"kind": "loot", "text": f"У дороги найдено: {ITEMS[item_id]['icon']} {ITEMS[item_id]['name']} ×{taken}."}
                return {"kind": "quiet", "text": "Нашлась полезная мелочь, но груз уже некуда класть."}
            self._add_xp(conn, telegram_id, 1)
            return {"kind": "quiet", "text": f"Участок {step}/{route['stages']} пройден без происшествий."}

    def _arrive(self, conn: sqlite3.Connection, telegram_id: int, travel: sqlite3.Row) -> dict:
        target = str(travel["target_id"])
        conn.execute("UPDATE player_world SET location_id = ? WHERE telegram_id = ?", (target, telegram_id))
        conn.execute("INSERT OR IGNORE INTO visited_locations (telegram_id, location_id) VALUES (?, ?)", (telegram_id, target))
        player = self._player(conn, telegram_id)
        conn.execute("UPDATE players SET state = 'base', hp = ?, pending_event = NULL, threat = 0, steps = 0 WHERE telegram_id = ?", (self.max_hp(player), telegram_id))
        conn.execute("DELETE FROM travel WHERE telegram_id = ?", (telegram_id,))
        return {"kind": "arrived", "arrived": True, "text": f"Маршрут завершён. Ты добрался до {LOCATIONS[target]['icon']} {LOCATIONS[target]['name']}."}

    def equipment(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM equipment WHERE telegram_id = ?", (telegram_id,)).fetchone()
            if not row:
                raise GameError("Экипировка персонажа не найдена.")
            return dict(row)

    def carry_capacity(self, player: sqlite3.Row | dict) -> int:
        equipment = self.equipment(int(player["telegram_id"]))
        return 8 + int(player["strength"]) * 3 + int(BACKPACKS[equipment["backpack_id"]].get("capacity", 0))

    def agility_resistance(self, player: sqlite3.Row | dict) -> int:
        return max(0, int(player["agility"]) - 1)

    def combat_damage_reduction(self, player: sqlite3.Row | dict) -> int:
        equipment = self.equipment(int(player["telegram_id"]))
        return self.agility_resistance(player) + int(ARMORS[player["armor_id"]]["reduction"]) + int(HEADGEAR[equipment["headgear_id"]].get("reduction", 0))

    def missing_requirements(self, player: sqlite3.Row | dict, item: dict) -> dict[str, int]:
        return {key: int(need) for key, need in item.get("requirements", {}).items() if int(player[key]) < int(need)}

    def inventory(self, telegram_id: int, *, secured: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT item_id, qty FROM inventory WHERE telegram_id = ? AND secured = ? AND qty > 0 ORDER BY item_id", (telegram_id, secured)).fetchall()
        return [dict(row) for row in rows]

    def cargo(self, telegram_id: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT item_id, qty FROM cargo WHERE telegram_id = ? AND qty > 0 ORDER BY item_id", (telegram_id,)).fetchall()
        return [dict(row) for row in rows]

    def field_weight(self, telegram_id: int) -> int:
        return self._inventory_weight(telegram_id, secured=0)

    def cargo_weight(self, telegram_id: int) -> int:
        return sum(int(row["qty"]) * ITEMS[row["item_id"]]["weight"] for row in self.cargo(telegram_id))

    def stash_value(self, telegram_id: int) -> int:
        market = LOCATIONS[self.location_id(telegram_id)]["market"]
        return sum(int(row["qty"]) * int(market.get(row["item_id"], {"sell": ITEMS[row["item_id"]]["value"]})["sell"]) for row in self.inventory(telegram_id, secured=1))

    def cargo_value_at(self, telegram_id: int, location_id: str | None = None) -> int:
        market = LOCATIONS[location_id or self.location_id(telegram_id)]["market"]
        return sum(int(row["qty"]) * int(market.get(row["item_id"], {"sell": ITEMS[row["item_id"]]["value"]})["sell"]) for row in self.cargo(telegram_id))

    def buy_trade_good(self, telegram_id: int, item_id: str) -> str:
        location_id = self.location_id(telegram_id)
        market = LOCATIONS[location_id]["market"]
        if item_id not in market:
            raise GameError("Этого товара здесь нет.")
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Торговать можно только в поселении.")
            if self._cargo_weight_conn(conn, telegram_id) + ITEMS[item_id]["weight"] > self.carry_capacity(player):
                raise GameError("Для этого товара не хватает места в грузе.")
            price = int(market[item_id]["buy"])
            self._charge(conn, player, price)
            self._change_cargo(conn, telegram_id, item_id, 1)
        return f"Куплено: {ITEMS[item_id]['name']} ×1 за {price} жет."

    def sell_cargo(self, telegram_id: int) -> str:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Продавать груз можно только в поселении.")
            market = LOCATIONS[self._location_id(conn, telegram_id)]["market"]
            rows = conn.execute("SELECT item_id, qty FROM cargo WHERE telegram_id = ? AND qty > 0", (telegram_id,)).fetchall()
            total = sum(int(row["qty"]) * int(market.get(row["item_id"], {"sell": ITEMS[row["item_id"]]["value"]})["sell"]) for row in rows)
            if total <= 0:
                raise GameError("Торгового груза нет.")
            conn.execute("DELETE FROM cargo WHERE telegram_id = ?", (telegram_id,))
            conn.execute("UPDATE players SET credits = credits + ? WHERE telegram_id = ?", (total, telegram_id))
        return f"Груз продан за {total} жет."

    def load_stash_to_cargo(self, telegram_id: int) -> str:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Перекладывать груз можно только в поселении.")
            rows = conn.execute("SELECT item_id, qty FROM inventory WHERE telegram_id = ? AND secured = 1 AND qty > 0 ORDER BY item_id", (telegram_id,)).fetchall()
            moved = 0
            for row in rows:
                item_id = str(row["item_id"])
                unit_weight = int(ITEMS[item_id]["weight"])
                free = self.carry_capacity(player) - self._cargo_weight_conn(conn, telegram_id)
                qty = min(int(row["qty"]), max(0, free // unit_weight))
                if qty <= 0:
                    continue
                self._change_cargo(conn, telegram_id, item_id, qty)
                self._change_item(conn, telegram_id, item_id, -qty, secured=1)
                moved += qty
        if not moved:
            raise GameError("Нечего загружать или груз уже заполнен.")
        return f"В груз перенесено предметов: {moved}."

    def unload_cargo(self, telegram_id: int) -> str:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Разгружаться можно только в поселении.")
            rows = conn.execute("SELECT item_id, qty FROM cargo WHERE telegram_id = ? AND qty > 0", (telegram_id,)).fetchall()
            moved = sum(int(row["qty"]) for row in rows)
            if moved <= 0:
                raise GameError("Груз пуст.")
            for row in rows:
                self._change_item(conn, telegram_id, str(row["item_id"]), int(row["qty"]), secured=1)
            conn.execute("DELETE FROM cargo WHERE telegram_id = ?", (telegram_id,))
        return f"Груз разгружен на склад: {moved} ед."

    def sell_all(self, telegram_id: int) -> str:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Торговать можно только в поселении.")
            market = LOCATIONS[self._location_id(conn, telegram_id)]["market"]
            rows = conn.execute("SELECT item_id, qty FROM inventory WHERE telegram_id = ? AND secured = 1 AND qty > 0", (telegram_id,)).fetchall()
            total = sum(int(row["qty"]) * int(market.get(row["item_id"], {"sell": ITEMS[row["item_id"]]["value"]})["sell"]) for row in rows)
            if total <= 0:
                raise GameError("На складе нет ресурсов для продажи.")
            conn.execute("DELETE FROM inventory WHERE telegram_id = ? AND secured = 1", (telegram_id,))
            conn.execute("UPDATE players SET credits = credits + ? WHERE telegram_id = ?", (total, telegram_id))
        return f"Склад продан по местным ценам за {total} жет."

    def sector_unlocked(self, player: sqlite3.Row | dict, sector_id: str) -> bool:
        sector = SECTORS[sector_id]
        return self.location_id(int(player["telegram_id"])) == sector["hub"] and int(player["successful_runs"]) >= int(sector["runs"]) and self.level(player) >= int(sector["level"])

    def local_sectors(self, telegram_id: int) -> list[tuple[str, dict]]:
        location_id = self.location_id(telegram_id)
        return [(sid, sector) for sid, sector in SECTORS.items() if sector["hub"] == location_id]

    def start_expedition(self, telegram_id: int, sector_id: str) -> str:
        if sector_id not in SECTORS:
            raise GameError("Неизвестный сектор.")
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Сначала закончи текущее действие.")
            if not self.sector_unlocked(player, sector_id):
                raise GameError("Этот сектор пока закрыт или находится в другом поселении.")
            conn.execute("UPDATE players SET state = 'expedition', sector_id = ?, hp = ?, threat = 0, steps = 0, pending_event = NULL, enemy_id = NULL, enemy_hp = NULL, aimed = 0 WHERE telegram_id = ?", (sector_id, self.max_hp(player), telegram_id))
            conn.execute("DELETE FROM inventory WHERE telegram_id = ? AND secured = 0", (telegram_id,))
        return f"Ты вышел в сектор «{SECTORS[sector_id]['name']}». Всё найденное до возвращения можно потерять."

    def explore(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "expedition":
                raise GameError("Сейчас нельзя исследовать сектор.")
            if player["pending_event"]:
                raise GameError("Сначала разберись с текущим событием.")
            threat = min(100, int(player["threat"]) + self.rng.randint(5, 9))
            steps = int(player["steps"]) + 1
            conn.execute("UPDATE players SET threat = ?, steps = ? WHERE telegram_id = ?", (threat, steps, telegram_id))
            player = self._player(conn, telegram_id)
            sector = SECTORS[player["sector_id"]]
            if self.rng.random() < 0.34:
                scene_id = self.rng.choice(list(EXPEDITION_SCENES))
                conn.execute("UPDATE players SET pending_event = ? WHERE telegram_id = ?", (f"scene:{scene_id}", telegram_id))
                return {"kind": "choice", "scene": scene_id, "text": "Впереди есть несколько вариантов пути."}
            enemy_weight = 24 + int(sector["danger"]) * 4 + threat // 7
            anomaly_weight = 10 + int(sector["danger"]) * 4 + threat // 12
            cache_weight = 12 + self.effective_attribute(player, "perception") * 2
            loot_weight = max(28, 54 - threat // 5)
            kind = self.rng.choices(["loot", "enemy", "anomaly", "cache", "quiet"], weights=[loot_weight, enemy_weight, anomaly_weight, cache_weight, 8], k=1)[0]
            if kind == "enemy":
                enemy_id = self.rng.choice(sector["enemies"])
                self._start_combat(conn, telegram_id, enemy_id, return_state="expedition")
                return {"kind": "enemy", "text": f"Шум впереди оказался не пустяком: {ENEMIES[enemy_id]['name']}."}
            if kind in {"anomaly", "cache"}:
                conn.execute("UPDATE players SET pending_event = ? WHERE telegram_id = ?", (kind, telegram_id))
                text = "Датчик ловит нестабильность под слоем мусора. Внутри может быть редкий материал." if kind == "anomaly" else "Под плитой виден герметичный технический ящик. Замок старый, но вокруг слишком тихо."
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

    def pending_scene(self, telegram_id: int) -> str | None:
        pending = self.get_player(telegram_id).get("pending_event")
        return str(pending).split(":", 1)[1] if pending and str(pending).startswith("scene:") else None

    def resolve_choice(self, telegram_id: int, action: str) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            pending = player["pending_event"]
            if player["state"] != "expedition" or not pending or not str(pending).startswith("scene:"):
                raise GameError("Сейчас нет такого выбора.")
            scene = str(pending).split(":", 1)[1]
            sector = SECTORS[player["sector_id"]]
            danger = int(sector["danger"])
            if action == "bypass":
                conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                return {"text": "Ты решил не рисковать и продолжил путь."}
            if scene == "warehouse" and action in {"careful", "force"}:
                if action == "careful":
                    chance = min(95, 35 + self.effective_attribute(player, "perception") * 9 + self.effective_attribute(player, "intelligence") * 4 - danger * 5)
                    conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                    if self.rng.randint(1, 100) <= chance:
                        result = self._roll_loot(conn, player, bonus_qty=1)
                        self._add_xp(conn, telegram_id, 5)
                        return {"text": f"Ловушка замечена вовремя. Добыча: {ITEMS[result.item_id]['icon']} {ITEMS[result.item_id]['name']} ×{result.taken}."}
                    return self._apply_hazard_damage(conn, player, self.rng.randint(8, 14) + danger, "Растяжку заметили слишком поздно")
                chance = min(90, 25 + int(player["strength"]) * 11 - danger * 4)
                conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                if self.rng.randint(1, 100) <= chance:
                    result = self._roll_loot(conn, player, bonus_qty=2)
                    self._add_xp(conn, telegram_id, 4)
                    return {"text": f"Ворота поддались. Внутри: {ITEMS[result.item_id]['icon']} {ITEMS[result.item_id]['name']} ×{result.taken}."}
                enemy_id = self.rng.choice(sector["enemies"])
                self._start_combat(conn, telegram_id, enemy_id, return_state="expedition")
                return {"text": f"Шум привлёк противника: {ENEMIES[enemy_id]['name']}.", "combat": True}
            if scene == "basement" and action in {"scan", "descend"}:
                if action == "scan":
                    chance = min(95, 30 + self.effective_attribute(player, "intelligence") * 10 + self.effective_attribute(player, "perception") * 4 - danger * 5)
                    conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                    if self.rng.randint(1, 100) <= chance:
                        item_id = "shard" if danger >= 2 and self.rng.random() < 0.25 else "chem"
                        taken = self._add_field_item(conn, player, item_id, 1)
                        self._add_xp(conn, telegram_id, 7)
                        return {"text": f"Сигнал расшифрован. Найдено: {ITEMS[item_id]['icon']} {ITEMS[item_id]['name']} ×{taken}."}
                    return self._apply_hazard_damage(conn, player, self.rng.randint(10, 17) + danger, "Датчик дал ложное безопасное окно")
                chance = min(92, 30 + self.effective_attribute(player, "agility") * 8 + self.effective_attribute(player, "perception") * 4 - danger * 5)
                conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                if self.rng.randint(1, 100) <= chance:
                    result = self._roll_loot(conn, player, bonus_qty=1)
                    self._add_xp(conn, telegram_id, 5)
                    return {"text": f"Спуск прошёл чисто. Добыча: {ITEMS[result.item_id]['icon']} {ITEMS[result.item_id]['name']} ×{result.taken}."}
                return self._apply_hazard_damage(conn, player, self.rng.randint(7, 13) + danger, "Лестница не выдержала")
            if scene == "gunfire" and action in {"observe", "ambush"}:
                if action == "observe":
                    chance = min(95, 35 + self.effective_attribute(player, "perception") * 10 - danger * 5)
                    conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                    if self.rng.randint(1, 100) <= chance:
                        ammo = self.rng.randint(3, 7)
                        conn.execute("UPDATE players SET ammo = ammo + ? WHERE telegram_id = ?", (ammo, telegram_id))
                        self._add_xp(conn, telegram_id, 4)
                        return {"text": f"Ты дождался конца перестрелки и подобрал 🔫 патроны ×{ammo}."}
                    self._start_combat(conn, telegram_id, "raider", return_state="expedition")
                    return {"text": "Тебя заметили первым. Мародёр открывает огонь.", "combat": True}
                chance = min(90, 25 + self.effective_attribute(player, "agility") * 8 + self.effective_attribute(player, "perception") * 5 - danger * 4)
                conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                self._start_combat(conn, telegram_id, "raider", return_state="expedition")
                if self.rng.randint(1, 100) <= chance:
                    conn.execute("UPDATE players SET enemy_hp = ? WHERE telegram_id = ?", (max(1, int(ENEMIES['raider']['hp']) - 18), telegram_id))
                    conn.execute("UPDATE combat_state SET cover = 1, distance = 2 WHERE telegram_id = ?", (telegram_id,))
                    return {"text": "Зайти сбоку удалось: противник ранен, а ты начинаешь бой из укрытия.", "combat": True}
                return {"text": "Обход сорвался. Приходится принимать бой без преимущества.", "combat": True}
            raise GameError("Для этого события такого действия нет.")

    def resolve_event(self, telegram_id: int, action: str) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "expedition" or player["pending_event"] not in {"anomaly", "cache"}:
                raise GameError("Здесь уже нечего решать.")
            event = str(player["pending_event"])
            sector = SECTORS[player["sector_id"]]
            if action == "bypass":
                conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                return {"text": "Ты не стал испытывать удачу и обошёл место по широкой дуге."}
            if event == "anomaly":
                chance = min(90, 36 + self.effective_attribute(player, "perception") * 6 + self.effective_attribute(player, "intelligence") * 5 - int(sector["danger"]) * 4)
                conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
                if self.rng.randint(1, 100) <= chance:
                    taken = self._add_field_item(conn, player, "shard", 1)
                    self._add_xp(conn, telegram_id, 12)
                    return {"text": f"Контур удалось снять чисто. В рюкзаке {ITEMS['shard']['icon']} {ITEMS['shard']['name']} ×{taken}.", "success": True}
                return self._apply_hazard_damage(conn, player, self.rng.randint(16, 25) + int(sector["danger"]) * 2, "Поле дёрнулось раньше, чем показал датчик")
            chance = min(94, 48 + self.effective_attribute(player, "perception") * 6 + self.effective_attribute(player, "intelligence") * 3 - int(sector["danger"]) * 4)
            conn.execute("UPDATE players SET pending_event = NULL WHERE telegram_id = ?", (telegram_id,))
            if self.rng.randint(1, 100) <= chance:
                item_id = self.rng.choice(sector["loot"])
                qty = self.rng.randint(1, 2) + (1 if self.rng.random() < 0.25 else 0)
                taken = self._add_field_item(conn, player, item_id, qty)
                ammo = self.rng.randint(2, 5)
                conn.execute("UPDATE players SET ammo = ammo + ? WHERE telegram_id = ?", (ammo, telegram_id))
                self._add_xp(conn, telegram_id, 7)
                return {"text": f"Ящик вскрыт без шума: {ITEMS[item_id]['icon']} {ITEMS[item_id]['name']} ×{taken} и 🔫 патроны ×{ammo}.", "success": True}
            return self._apply_hazard_damage(conn, player, self.rng.randint(7, 13) + int(sector["danger"]), "Сработала примитивная растяжка")

    def return_base(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "expedition":
                raise GameError("Сейчас нельзя завершить вылазку.")
            field_rows = conn.execute("SELECT item_id, qty FROM inventory WHERE telegram_id = ? AND secured = 0 AND qty > 0", (telegram_id,)).fetchall()
            for row in field_rows:
                self._change_item(conn, telegram_id, str(row["item_id"]), int(row["qty"]), secured=1)
            conn.execute("DELETE FROM inventory WHERE telegram_id = ? AND secured = 0", (telegram_id,))
            conn.execute("UPDATE players SET state = 'base', sector_id = NULL, threat = 0, steps = 0, pending_event = NULL, enemy_id = NULL, enemy_hp = NULL, aimed = 0, successful_runs = successful_runs + 1, hp = ? WHERE telegram_id = ?", (self.max_hp(player), telegram_id))
            self._add_xp(conn, telegram_id, 4)
        value = self.stash_value(telegram_id)
        return {"text": f"Вылазка завершена. Добыча закреплена на складе. Текущая местная стоимость склада: {value} жет.", "value": value}

    def combat_state(self, telegram_id: int) -> dict:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return dict(row) if row else {"return_state": "expedition", "distance": 2, "cover": 0, "bleeding": 0}

    def _start_combat(self, conn: sqlite3.Connection, telegram_id: int, enemy_id: str, *, return_state: str) -> None:
        enemy = ENEMIES[enemy_id]
        player = self._player(conn, telegram_id)
        enemy_hp = int(enemy["hp"]) + max(0, int(player["threat"]) - 35) // 5
        conn.execute("UPDATE players SET state = 'combat', enemy_id = ?, enemy_hp = ?, aimed = 0 WHERE telegram_id = ?", (enemy_id, enemy_hp, telegram_id))
        conn.execute("INSERT OR REPLACE INTO combat_state (telegram_id, return_state, distance, cover, bleeding) VALUES (?, ?, ?, 0, 0)", (telegram_id, return_state, int(enemy["start_distance"])))

    def combat_action(self, telegram_id: int, action: str) -> dict:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "combat" or not player["enemy_id"]:
                raise GameError("Бой уже закончен.")
            enemy = ENEMIES[player["enemy_id"]]
            weapon = WEAPONS[player["weapon_id"]]
            combat = conn.execute("SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)).fetchone()
            if not combat:
                raise GameError("Состояние боя потеряно.")
            lines = []
            if int(combat["bleeding"]) > 0:
                bleed_damage = int(combat["bleeding"])
                hp = int(player["hp"]) - bleed_damage
                lines.append(f"🩸 Кровотечение: -{bleed_damage} HP.")
                if hp <= 0:
                    lines.append(self._kill(conn, telegram_id))
                    return {"text": "\n".join(lines), "dead": True}
                conn.execute("UPDATE players SET hp = ? WHERE telegram_id = ?", (hp, telegram_id))
                player = self._player(conn, telegram_id)
            distance = int(combat["distance"])
            cover = bool(combat["cover"])
            if action == "shoot":
                if int(player["ammo"]) <= 0:
                    raise GameError("Патроны закончились.")
                conn.execute("UPDATE players SET ammo = ammo - 1, aimed = 0 WHERE telegram_id = ?", (telegram_id,))
                aimed_bonus = 20 if player["aimed"] else 0
                range_penalty = max(0, distance - int(weapon["range"])) * 18
                accuracy = min(95, max(15, int(weapon["accuracy"]) + self.effective_attribute(player, "agility") * 4 + aimed_bonus - range_penalty - (5 if cover else 0)))
                if self.rng.randint(1, 100) <= accuracy:
                    damage = max(1, int(weapon["damage"]) + self.effective_attribute(player, "agility") * 2 + self.rng.randint(-3, 4))
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
                conn.execute("UPDATE players SET ammo = ammo - 3, aimed = 0 WHERE telegram_id = ?", (telegram_id,))
                range_penalty = max(0, distance - int(weapon["range"])) * 16
                accuracy = min(88, max(12, int(weapon["accuracy"]) + self.effective_attribute(player, "agility") * 3 - 12 - range_penalty))
                hits = 0
                total = 0
                for _ in range(3):
                    if self.rng.randint(1, 100) <= accuracy:
                        hits += 1
                        total += max(1, int(weapon["damage"]) // 2 + self.effective_attribute(player, "agility") + self.rng.randint(-2, 3))
                if hits:
                    lines.append(f"Очередь: попаданий {hits}/3, урон -{total} HP.")
                    if self._damage_enemy(conn, telegram_id, total):
                        return self._finish_combat(conn, telegram_id, enemy, lines)
                else:
                    lines.append("Очередь прошла мимо цели.")
            elif action == "aim":
                if player["aimed"]:
                    raise GameError("Ты уже держишь цель на мушке.")
                conn.execute("UPDATE players SET aimed = 1 WHERE telegram_id = ?", (telegram_id,))
                lines.append("Ты выждал момент. Следующий одиночный выстрел получит +20% точности.")
            elif action == "cover":
                if cover:
                    raise GameError("Ты уже в укрытии.")
                conn.execute("UPDATE combat_state SET cover = 1 WHERE telegram_id = ?", (telegram_id,))
                lines.append("Ты занял укрытие. Дальний огонь противника станет менее опасным.")
            elif action == "approach":
                if distance <= 1:
                    raise GameError("Ты уже вплотную к противнику.")
                conn.execute("UPDATE combat_state SET distance = distance - 1, cover = 0 WHERE telegram_id = ?", (telegram_id,))
                lines.append("Ты сократил дистанцию.")
            elif action == "melee":
                if distance > 1:
                    raise GameError("Для ближнего боя нужно сначала сблизиться.")
                accuracy = min(92, 45 + self.effective_attribute(player, "agility") * 5)
                if self.rng.randint(1, 100) <= accuracy:
                    damage = 7 + int(player["strength"]) * 4 + self.rng.randint(0, 5)
                    lines.append(f"Удар вблизи: -{damage} HP.")
                    if self._damage_enemy(conn, telegram_id, damage):
                        return self._finish_combat(conn, telegram_id, enemy, lines)
                else:
                    lines.append("Удар не достиг цели.")
            elif action == "medkit":
                if int(player["medkits"]) <= 0:
                    raise GameError("Аптечек нет.")
                heal = 30 + self.effective_attribute(player, "intelligence") * 4
                hp = min(self.max_hp(player), int(player["hp"]) + heal)
                conn.execute("UPDATE players SET medkits = medkits - 1, hp = ? WHERE telegram_id = ?", (hp, telegram_id))
                conn.execute("UPDATE combat_state SET bleeding = 0 WHERE telegram_id = ?", (telegram_id,))
                lines.append(f"Аптечка: здоровье восстановлено до {hp}, кровотечение остановлено.")
            elif action == "flee":
                chance = max(15, min(88, 28 + self.effective_attribute(player, "agility") * 8 + (distance - 1) * 7 - int(player["threat"]) // 8))
                if self.rng.randint(1, 100) <= chance:
                    return_state = str(combat["return_state"])
                    conn.execute("UPDATE players SET state = ?, enemy_id = NULL, enemy_hp = NULL, aimed = 0 WHERE telegram_id = ?", (return_state, telegram_id))
                    conn.execute("DELETE FROM combat_state WHERE telegram_id = ?", (telegram_id,))
                    return {"text": f"Удалось оторваться. Шанс был {chance}%.", "fled": True}
                lines.append(f"Отступление сорвалось. Шанс был {chance}%.")
            else:
                raise GameError("Неизвестное боевое действие.")
            enemy_result = self._enemy_turn(conn, telegram_id, enemy)
            if enemy_result.get("text"):
                lines.append(enemy_result["text"])
            if enemy_result.get("dead"):
                return {"text": "\n".join(lines), "dead": True}
            return {"text": "\n".join(lines)}

    def _enemy_turn(self, conn: sqlite3.Connection, telegram_id: int, enemy: dict) -> dict:
        player = self._player(conn, telegram_id)
        combat = conn.execute("SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if not combat:
            return {}
        distance = int(combat["distance"])
        style = str(enemy["style"])
        if style == "melee" and distance > 1:
            conn.execute("UPDATE combat_state SET distance = distance - 1 WHERE telegram_id = ?", (telegram_id,))
            return {"text": f"{enemy['name']} быстро сближается."}
        if style == "ranged" and distance == 1 and self.rng.random() < 0.55:
            conn.execute("UPDATE combat_state SET distance = 2 WHERE telegram_id = ?", (telegram_id,))
            return {"text": f"{enemy['name']} отходит назад, разрывая дистанцию."}
        raw_damage = self.rng.randint(*enemy["damage"])
        if style == "ranged" and bool(combat["cover"]):
            raw_damage = max(1, raw_damage - 5)
        damage = max(1, raw_damage - self.combat_damage_reduction(player))
        new_hp = int(player["hp"]) - damage
        text = f"{enemy['name']} отвечает: -{damage} HP."
        if int(enemy.get("bleed", 0)) > 0 and self.rng.randint(1, 100) <= int(enemy["bleed"]):
            conn.execute("UPDATE combat_state SET bleeding = ? WHERE telegram_id = ?", (max(int(combat["bleeding"]), 2), telegram_id))
            text += " 🩸 Началось кровотечение."
        if new_hp <= 0:
            return {"text": f"{text}\n{self._kill(conn, telegram_id)}", "dead": True}
        conn.execute("UPDATE players SET hp = ? WHERE telegram_id = ?", (new_hp, telegram_id))
        return {"text": text}

    def _finish_combat(self, conn: sqlite3.Connection, telegram_id: int, enemy: dict, lines: list[str]) -> dict:
        player = self._player(conn, telegram_id)
        combat = conn.execute("SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return_state = str(combat["return_state"]) if combat else "expedition"
        loot_id = str(enemy["loot"])
        taken = self._add_cargo_item_conn(conn, player, loot_id, 1) if return_state == "travel" else self._add_field_item(conn, player, loot_id, 1)
        self._add_xp(conn, telegram_id, int(enemy["xp"]))
        conn.execute("UPDATE players SET state = ?, enemy_id = NULL, enemy_hp = NULL, aimed = 0 WHERE telegram_id = ?", (return_state, telegram_id))
        conn.execute("DELETE FROM combat_state WHERE telegram_id = ?", (telegram_id,))
        loot_text = f" Добыча: {ITEMS[loot_id]['icon']} {ITEMS[loot_id]['name']} ×{taken}." if taken else " Места для добычи не осталось."
        lines.append(f"Противник устранён. +{enemy['xp']} опыта.{loot_text}")
        return {"text": "\n".join(lines), "won": True}

    def _damage_enemy(self, conn: sqlite3.Connection, telegram_id: int, damage: int) -> bool:
        player = self._player(conn, telegram_id)
        hp = int(player["enemy_hp"]) - damage
        conn.execute("UPDATE players SET enemy_hp = ? WHERE telegram_id = ?", (max(0, hp), telegram_id))
        return hp <= 0

    def _kill(self, conn: sqlite3.Connection, telegram_id: int) -> str:
        player = self._player(conn, telegram_id)
        combat = conn.execute("SELECT * FROM combat_state WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return_state = str(combat["return_state"]) if combat else str(player["state"])
        if return_state == "travel":
            conn.execute("DELETE FROM cargo WHERE telegram_id = ?", (telegram_id,))
            conn.execute("DELETE FROM travel WHERE telegram_id = ?", (telegram_id,))
            loss = "Торговый груз потерян."
        else:
            conn.execute("DELETE FROM inventory WHERE telegram_id = ? AND secured = 0", (telegram_id,))
            loss = "Незакреплённая добыча потеряна."
        conn.execute("DELETE FROM combat_state WHERE telegram_id = ?", (telegram_id,))
        conn.execute("UPDATE players SET state = 'base', sector_id = NULL, hp = ?, threat = 0, steps = 0, pending_event = NULL, enemy_id = NULL, enemy_hp = NULL, aimed = 0, deaths = deaths + 1, ammo = MAX(3, ammo - 3), medkits = MAX(0, medkits - 1) WHERE telegram_id = ?", (self.max_hp(player), telegram_id))
        return f"Ты не вернулся своим ходом. {loss} Часть расходников тоже пропала."

    def _apply_hazard_damage(self, conn: sqlite3.Connection, player: sqlite3.Row, raw_damage: int, prefix: str) -> dict:
        damage = max(1, raw_damage - self.agility_resistance(player))
        new_hp = int(player["hp"]) - damage
        if new_hp <= 0:
            return {"text": f"{prefix}: -{damage} HP.\n{self._kill(conn, int(player['telegram_id']))}", "dead": True}
        conn.execute("UPDATE players SET hp = ? WHERE telegram_id = ?", (new_hp, player["telegram_id"]))
        return {"text": f"{prefix}: -{damage} HP.", "success": False}

    def buy(self, telegram_id: int, product: str) -> str:
        with self.db.connect() as conn:
            player = self._player(conn, telegram_id)
            if player["state"] != "base":
                raise GameError("Покупать можно только в поселении.")
            location = LOCATIONS[self._location_id(conn, telegram_id)]
            if product == "ammo":
                price = int(location["ammo_price"])
                self._charge(conn, player, price)
                conn.execute("UPDATE players SET ammo = ammo + 6 WHERE telegram_id = ?", (telegram_id,))
                return f"Куплено: Патроны ×6 за {price} жет."
            if product == "medkit":
                price = int(location["medkit_price"])
                self._charge(conn, player, price)
                conn.execute("UPDATE players SET medkits = medkits + 1 WHERE telegram_id = ?", (telegram_id,))
                return f"Куплено: Аптечка за {price} жет."
            catalogs = [(WEAPONS, "weapon_id"), (ARMORS, "armor_id"), (BACKPACKS, "backpack_id"), (HEADGEAR, "headgear_id"), (GADGETS, "gadget_id")]
            for catalog, field in catalogs:
                if product not in catalog:
                    continue
                item = catalog[product]
                missing = self.missing_requirements(player, item)
                if missing:
                    text = ", ".join(f"{ATTRIBUTES[key]['name']} {need}" for key, need in missing.items())
                    raise GameError(f"Не хватает характеристик: {text}.")
                current_id = str(player[field]) if field in {"weapon_id", "armor_id"} else str(conn.execute(f"SELECT {field} FROM equipment WHERE telegram_id = ?", (telegram_id,)).fetchone()[field])
                if int(item["order"]) <= int(catalog[current_id]["order"]):
                    raise GameError("Этот предмет не является улучшением текущего слота.")
                self._charge(conn, player, int(item["price"]))
                table = "players" if field in {"weapon_id", "armor_id"} else "equipment"
                conn.execute(f"UPDATE {table} SET {field} = ? WHERE telegram_id = ?", (product, telegram_id))
                return f"Куплено: {item['name']}. Предмет сразу экипирован."
            raise GameError("Неизвестный товар.")

    def _roll_loot(self, conn: sqlite3.Connection, player: sqlite3.Row, bonus_qty: int = 0) -> LootResult:
        sector = SECTORS[player["sector_id"]]
        pool = list(sector["loot"])
        perception = self.effective_attribute(player, "perception")
        if perception > 1 and int(sector["danger"]) >= 2:
            pool.extend(["parts"] * (perception - 1))
        if int(sector["danger"]) >= 3:
            pool.extend(["shard"] * max(0, perception - 2))
        item_id = self.rng.choice(pool)
        qty = 1 + bonus_qty + (1 if self.rng.random() < min(0.85, 0.30 + perception * 0.045) else 0)
        taken = self._add_field_item(conn, player, item_id, qty)
        return LootResult(item_id=item_id, qty=qty, taken=taken)

    def _add_field_item(self, conn: sqlite3.Connection, player: sqlite3.Row, item_id: str, qty: int) -> int:
        current_weight = self._inventory_weight_conn(conn, int(player["telegram_id"]), secured=0)
        unit_weight = int(ITEMS[item_id]["weight"])
        taken = min(qty, max(0, (self.carry_capacity(player) - current_weight) // unit_weight))
        if taken > 0:
            self._change_item(conn, int(player["telegram_id"]), item_id, taken, secured=0)
        return taken

    def _add_cargo_item_conn(self, conn: sqlite3.Connection, player: sqlite3.Row, item_id: str, qty: int) -> int:
        current_weight = self._cargo_weight_conn(conn, int(player["telegram_id"]))
        unit_weight = int(ITEMS[item_id]["weight"])
        taken = min(qty, max(0, (self.carry_capacity(player) - current_weight) // unit_weight))
        if taken > 0:
            self._change_cargo(conn, int(player["telegram_id"]), item_id, taken)
        return taken

    def _change_item(self, conn: sqlite3.Connection, telegram_id: int, item_id: str, qty: int, *, secured: int) -> None:
        conn.execute("INSERT INTO inventory (telegram_id, item_id, secured, qty) VALUES (?, ?, ?, ?) ON CONFLICT (telegram_id, item_id, secured) DO UPDATE SET qty = MAX(0, qty + excluded.qty)", (telegram_id, item_id, secured, qty))
        conn.execute("DELETE FROM inventory WHERE telegram_id = ? AND item_id = ? AND secured = ? AND qty <= 0", (telegram_id, item_id, secured))

    def _change_cargo(self, conn: sqlite3.Connection, telegram_id: int, item_id: str, qty: int) -> None:
        conn.execute("INSERT INTO cargo (telegram_id, item_id, qty) VALUES (?, ?, ?) ON CONFLICT (telegram_id, item_id) DO UPDATE SET qty = MAX(0, qty + excluded.qty)", (telegram_id, item_id, qty))
        conn.execute("DELETE FROM cargo WHERE telegram_id = ? AND item_id = ? AND qty <= 0", (telegram_id, item_id))

    def _inventory_weight(self, telegram_id: int, *, secured: int) -> int:
        with self.db.connect() as conn:
            return self._inventory_weight_conn(conn, telegram_id, secured=secured)

    def _inventory_weight_conn(self, conn: sqlite3.Connection, telegram_id: int, *, secured: int) -> int:
        rows = conn.execute("SELECT item_id, qty FROM inventory WHERE telegram_id = ? AND secured = ? AND qty > 0", (telegram_id, secured)).fetchall()
        return sum(int(row["qty"]) * int(ITEMS[row["item_id"]]["weight"]) for row in rows)

    def _cargo_weight_conn(self, conn: sqlite3.Connection, telegram_id: int) -> int:
        rows = conn.execute("SELECT item_id, qty FROM cargo WHERE telegram_id = ? AND qty > 0", (telegram_id,)).fetchall()
        return sum(int(row["qty"]) * int(ITEMS[row["item_id"]]["weight"]) for row in rows)

    def _add_xp(self, conn: sqlite3.Connection, telegram_id: int, amount: int) -> None:
        if amount <= 0:
            return
        player = self._player(conn, telegram_id)
        old_level = self.level(player)
        conn.execute("UPDATE players SET xp = xp + ? WHERE telegram_id = ?", (amount, telegram_id))
        updated = self._player(conn, telegram_id)
        if self.level(updated) > old_level:
            hp_gain = (self.level(updated) - old_level) * 20
            conn.execute("UPDATE players SET hp = MIN(?, hp + ?) WHERE telegram_id = ?", (self.max_hp(updated), hp_gain, telegram_id))

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

    @staticmethod
    def _location_id(conn: sqlite3.Connection, telegram_id: int) -> str:
        row = conn.execute("SELECT location_id FROM player_world WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if not row:
            raise GameError("Положение персонажа не найдено.")
        return str(row["location_id"])
