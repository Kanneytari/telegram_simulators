from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .content import ARMORS, MAX_SKILL, SECTORS, WEAPONS
from .game import GameService


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def home() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("🧭 Вылазка", "menu:sectors"), ("🎒 Склад", "menu:inventory")],
            [("🧬 Персонаж", "menu:character"), ("🏪 Торговец", "menu:shop")],
            [("ℹ️ Как играть", "menu:rules")],
        ]
    )


def back_home() -> InlineKeyboardMarkup:
    return _kb([[("◀️ Меню", "menu:home")]])


def sectors(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    player = game.get_player(telegram_id)
    rows: list[list[tuple[str, str]]] = []
    for sector_id, sector in SECTORS.items():
        if game.sector_unlocked(player, sector_id):
            rows.append([(f"{sector['icon']} {sector['name']}", f"sector:{sector_id}")])
    rows.append([("◀️ Меню", "menu:home")])
    return _kb(rows)


def expedition() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("🔎 Искать добычу", "expedition:explore")],
            [("🎒 Рюкзак", "expedition:inventory"), ("↩️ Вернуться", "expedition:return")],
        ]
    )


def event() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("⚠️ Рискнуть", "event:try"), ("🚶 Обойти", "event:bypass")],
            [("🎒 Рюкзак", "expedition:inventory")],
        ]
    )


def combat() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("🔫 Выстрел", "combat:shoot"), ("🎯 Прицелиться", "combat:aim")],
            [("🔪 Ближний бой", "combat:melee"), ("🩹 Аптечка", "combat:medkit")],
            [("🏃 Отступить", "combat:flee")],
        ]
    )


def character(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    player = game.get_player(telegram_id)
    rows: list[list[tuple[str, str]]] = []
    if game.skill_points(player) > 0:
        if player["combat"] < MAX_SKILL:
            rows.append([("⬆️ Бой", "skill:combat")])
        if player["scavenging"] < MAX_SKILL:
            rows.append([("⬆️ Поиск", "skill:scavenging")])
        if player["survival"] < MAX_SKILL:
            rows.append([("⬆️ Выживание", "skill:survival")])
    rows.append([("◀️ Меню", "menu:home")])
    return _kb(rows)


def shop(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    player = game.get_player(telegram_id)
    rows: list[list[tuple[str, str]]] = [
        [("💰 Продать весь склад", "shop:sell")],
        [("🔫 Патроны ×6 · 24", "shop:ammo"), ("🩹 Аптечка · 32", "shop:medkit")],
    ]
    current_weapon_order = WEAPONS[player["weapon_id"]]["order"]
    for item_id, item in WEAPONS.items():
        if item["price"] and item["order"] > current_weapon_order:
            rows.append([(f"🔫 {item['name']} · {item['price']}", f"shop:{item_id}")])
            break
    current_armor_order = ARMORS[player["armor_id"]]["order"]
    for item_id, item in ARMORS.items():
        if item["price"] and item["order"] > current_armor_order:
            rows.append([(f"🦺 {item['name']} · {item['price']}", f"shop:{item_id}")])
            break
    rows.append([("◀️ Меню", "menu:home")])
    return _kb(rows)


def expedition_inventory() -> InlineKeyboardMarkup:
    return _kb([[("◀️ Назад", "expedition:back")]])
