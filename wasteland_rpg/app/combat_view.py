from __future__ import annotations

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .content import ENEMIES, WEAPONS
from .game import GameService
from .ui import level_up_notice


def combat_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    enemy = ENEMIES[player["enemy_id"]]
    weapon = WEAPONS[player["weapon_id"]]
    combat = game.combat_state(telegram_id)

    lines = [
        f"⚔️ <b>БОЙ · {escape(enemy['name']).upper()}</b>",
        "━━━━━━━━━━━━",
    ]
    notice = level_up_notice(game, player)
    if notice:
        lines.append(notice)

    lines.append(f"❤️ {player['hp']}/{game.max_hp(player)}")
    if combat["bleeding"]:
        lines.append(f"🩸 Кровотечение: {combat['bleeding']} HP/ход")
    lines.append(f"☠️ {player['enemy_hp']} HP")

    if int(combat["distance"]) <= 1:
        lines.append("⚠️ Противник вплотную — доступен ближний бой.")
    if combat["cover"]:
        lines.append("🧱 Ты в укрытии.")

    lines += [
        "",
        f"🔫 {escape(weapon['name'])} · {player['ammo']} патр.",
        f"🛡 Защита: {game.combat_damage_reduction(player)}",
        "",
        "<i>Стреляй, используй расходники или отходи. Ближний бой появляется только когда противник сам подошёл вплотную.</i>",
    ]
    return "\n".join(lines)


def combat_keyboard(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    player = game.get_player(telegram_id)
    enemy = ENEMIES[player["enemy_id"]]
    weapon = WEAPONS[player["weapon_id"]]
    combat = game.combat_state(telegram_id)

    rows: list[list[InlineKeyboardButton]] = []
    fire_row = [InlineKeyboardButton(text="🔫 Выстрел", callback_data="combat:shoot")]
    if "burst" in weapon.get("modes", ()):
        fire_row.append(InlineKeyboardButton(text="💥 Очередь ×3", callback_data="combat:burst"))
    rows.append(fire_row)

    if int(combat["distance"]) <= 1:
        rows.append([InlineKeyboardButton(text="🔪 Ближний бой", callback_data="combat:melee")])

    utility_row: list[InlineKeyboardButton] = []
    if str(enemy["style"]) == "ranged" and not combat["cover"]:
        utility_row.append(InlineKeyboardButton(text="🧱 В укрытие", callback_data="combat:cover"))
    utility_row.append(InlineKeyboardButton(text="🩹 Аптечка", callback_data="combat:medkit"))
    if utility_row:
        rows.append(utility_row)

    rows.append([InlineKeyboardButton(text="🏃 Отступить", callback_data="combat:flee")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
