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

    gear_lines = [
        "<b>Снаряжение:</b>",
        f"🪖 {escape(HEADGEAR[equipment['headgear_id']]['name'])}",
        f"🦺 {escape(ARMORS[player['armor_id']]['name'])}",
        f"🎒 {escape(BACKPACKS[equipment['backpack_id']]['name'])}",
        f"🔫 {escape(WEAPONS[player['weapon_id']]['name'])}",
    ]
    if equipment["gadget_id"] != "none":
        gear_lines.append(f"📡 {escape(GADGETS[equipment['gadget_id']]['name'])}")
    gear = "\n".join(gear_lines)

    return (
        f"{location['icon']} <b>{escape(location['name']).upper()}</b> · уровень {game.level(player)}\n"
        "━━━━━━━━━━━━\n"
        f"{_level_line(game, player)}"
        f"❤️ {player['hp']}/{game.max_hp(player)} · 🔫 {player['ammo']} · 🩹 {player['medkits']}\n"
        f"💰 {player['credits']} жет. · 📦 склад {stash} · 🚚 груз {cargo}\n"
        f"✨ Опыт {player['xp']}\n\n"
        f"{gear}\n\n"
        f"💪 {player['strength']} · 🏃 {player['agility']} · 👁 {player['perception']} · 🧠 {player['intelligence']}"
    )
