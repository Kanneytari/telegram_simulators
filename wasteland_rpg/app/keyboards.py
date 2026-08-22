from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .content import ARMORS, ATTRIBUTES, SECTORS, WEAPONS
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
    if game.attribute_points(player) > 0:
        buttons = [
            (f"⬆️ {meta['icon']}", f"attribute:{key}")
            for key, meta in ATTRIBUTES.items()
        ]
        rows.extend([buttons[:2], buttons[2:]])
    rows.append([("◀️ Меню", "menu:home")])
    return _kb(rows)


def shop() -> InlineKeyboardMarkup:
    return _kb(
        [
            [("🔫 Оружие", "shopcat:weapons"), ("🦺 Экипировка", "shopcat:equipment")],
            [("🩹 Медицина", "shopcat:medicine")],
            [("💰 Продать весь склад", "shop:sell")],
            [("◀️ Меню", "menu:home")],
        ]
    )


def _shop_navigation() -> list[list[tuple[str, str]]]:
    return [
        [("🔫 Оружие", "shopcat:weapons"), ("🦺 Экипировка", "shopcat:equipment")],
        [("🩹 Медицина", "shopcat:medicine"), ("◀️ Торговец", "menu:shop")],
    ]


def shop_weapons(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    player = game.get_player(telegram_id)
    rows: list[list[tuple[str, str]]] = [
        [("🔫 Патроны ×6 · 24", "shopbuy:weapons:ammo")],
    ]
    current_order = WEAPONS[player["weapon_id"]]["order"]
    for item_id, item in WEAPONS.items():
        if item["price"] and item["order"] > current_order:
            lock = "🔒 " if game.missing_requirements(player, item) else ""
            rows.append(
                [(f"{lock}🔫 {item['name']} · {item['price']}", f"shopbuy:weapons:{item_id}")]
            )
    rows.extend(_shop_navigation())
    return _kb(rows)


def shop_equipment(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    player = game.get_player(telegram_id)
    rows: list[list[tuple[str, str]]] = []
    current_order = ARMORS[player["armor_id"]]["order"]
    for item_id, item in ARMORS.items():
        if item["price"] and item["order"] > current_order:
            lock = "🔒 " if game.missing_requirements(player, item) else ""
            rows.append(
                [(f"{lock}🦺 {item['name']} · {item['price']}", f"shopbuy:equipment:{item_id}")]
            )
    rows.extend(_shop_navigation())
    return _kb(rows)


def shop_medicine() -> InlineKeyboardMarkup:
    rows = [
        [("🩹 Аптечка · 32", "shopbuy:medicine:medkit")],
        *_shop_navigation(),
    ]
    return _kb(rows)


def expedition_inventory() -> InlineKeyboardMarkup:
    return _kb([[("◀️ Назад", "expedition:back")]])
