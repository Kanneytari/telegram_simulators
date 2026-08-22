from __future__ import annotations

from html import escape

from .content import ARMORS, BACKPACKS, GADGETS, HEADGEAR, WEAPONS
from .ui import _level_line


def main_screen(game, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    location = game.location(telegram_id)
    equipment = game.equipment(telegram_id)
    stash = sum(row["qty"] for row in game.inventory(telegram_id, secured=1))
    cargo = sum(row["qty"] for row in game.cargo(telegram_id))

    return (
        f"{location['icon']} <b>{escape(location['name']).upper()}</b> · уровень {game.level(player)}\n"
        "━━━━━━━━━━━━\n"
        f"{_level_line(game, player)}"
        f"❤️ {player['hp']}/{game.max_hp(player)} · 🔫 {player['ammo']} · 🩹 {player['medkits']}\n"
        f"💰 {player['credits']} жет. · 📦 склад {stash} · 🚚 груз {cargo}\n\n"
        f"🔫 {escape(WEAPONS[player['weapon_id']]['name'])}\n"
        f"🦺 {escape(ARMORS[player['armor_id']]['name'])} · 🎒 {escape(BACKPACKS[equipment['backpack_id']]['name'])}\n"
        f"🪖 {escape(HEADGEAR[equipment['headgear_id']]['name'])} · 📡 {escape(GADGETS[equipment['gadget_id']]['name'])}\n\n"
        f"💪 {player['strength']} · 🏃 {player['agility']} · 👁 {player['perception']} · 🧠 {player['intelligence']}\n"
        f"✨ Опыт {player['xp']}"
    )
