from __future__ import annotations

from html import escape

from .content import ARMORS, BACKPACKS, GADGETS, HEADGEAR, WEAPONS
from .ui import level_up_notice


def character_screen(game, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    equipment = game.equipment(telegram_id)
    progress, required = game.xp_progress(player)

    lines = ["🧬 <b>ПЕРСОНАЖ</b>", "━━━━━━━━━━━━"]
    notice = level_up_notice(game, player)
    if notice:
        lines.append(notice)

    lines += [
        f"Уровень: <b>{game.level(player)}</b> · ❤️ {game.max_hp(player)} HP",
        f"Опыт: {progress}/{required}",
        f"Свободных очков: <b>{game.attribute_points(player)}</b>",
        "",
        f"💪: <b>{player['strength']}</b> · 🏃: <b>{player['agility']}</b> · 👁: <b>{player['perception']}</b> · 🧠: <b>{player['intelligence']}</b>",
        "",
        f"🔫 {escape(WEAPONS[player['weapon_id']]['name'])}",
        f"🦺 {escape(ARMORS[player['armor_id']]['name'])}",
        f"🎒 {escape(BACKPACKS[equipment['backpack_id']]['name'])}",
        f"🪖 {escape(HEADGEAR[equipment['headgear_id']]['name'])}",
        f"📡 {escape(GADGETS[equipment['gadget_id']]['name'])}",
    ]
    return "\n".join(lines)
