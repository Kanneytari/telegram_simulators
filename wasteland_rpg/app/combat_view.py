from __future__ import annotations

import math
import time
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .combat_rules import PLAYER_ACTION_LABELS, PLAYER_ACTION_SECONDS
from .content import ENEMIES, WEAPONS
from .ui import level_up_notice


def _seconds_left(due_at: float | None, now: float) -> int:
    if due_at is None:
        return 0
    return max(0, int(math.ceil(float(due_at) - now)))


def _enemy_intent(enemy: dict, action: str) -> str:
    if action == "approach":
        return f"🏃 {enemy['name']} приближается"
    if action == "retreat":
        return f"↩️ {enemy['name']} отходит"
    if action == "ranged_attack":
        return f"🔫 {enemy['name']} готовит выстрел"
    return f"🔪 {enemy['name']} готовит атаку"


def _queued_button_text(action: str, text: str, queued: str | None) -> str:
    return f"✓ {text}" if queued == action else text


def combat_screen(game, telegram_id: int) -> str:
    now = time.time()
    player = game.get_player(telegram_id)
    enemy = ENEMIES[player["enemy_id"]]
    weapon = WEAPONS[player["weapon_id"]]
    combat = game.combat_state(telegram_id)
    timeline = game.combat_timeline(telegram_id)
    queued = game.combat_queued_action(telegram_id)
    log = game.combat_log(telegram_id)

    lines = [
        f"⚔️ <b>БОЙ · {escape(enemy['name']).upper()}</b>",
        "━━━━━━━━━━━━",
    ]

    if log:
        log_text = "\n".join(f"• {escape(entry)}" for entry in log)
        lines += [f"<blockquote>{log_text}</blockquote>", ""]

    notice = level_up_notice(game, player)
    if notice:
        lines.append(notice)

    lines.append(f"❤️ {player['hp']}/{game.max_hp(player)} · 🔫 {player['ammo']} патр.")
    lines.append(f"☠️ {player['enemy_hp']} HP")
    if combat["bleeding"]:
        lines.append(f"🩸 Кровотечение: {combat['bleeding']} HP/сек")
    if combat["cover"]:
        lines.append("🧱 Ты в укрытии.")
    if timeline and float(timeline["stim_until"]) > now:
        lines.append("💉 Стимулятор восстанавливает здоровье.")
    if int(combat["distance"]) <= 1:
        lines.append("⚠️ Противник вплотную.")

    lines += ["", f"🔫 {escape(weapon['name'])}"]

    if timeline:
        player_action = timeline["player_action"]
        if player_action:
            label = PLAYER_ACTION_LABELS.get(str(player_action), str(player_action))
            left = _seconds_left(timeline["player_action_due"], now)
            lines.append(f"Ты: {label} · {left}с")
        else:
            lines.append("Ты: готов к действию")

        if queued:
            lines.append(f"Следующее: {PLAYER_ACTION_LABELS.get(queued, queued)}")

        enemy_action = str(timeline["enemy_action"])
        enemy_left = _seconds_left(timeline["enemy_action_due"], now)
        lines.append(f"Противник: {_enemy_intent(enemy, enemy_action)} · {enemy_left}с")

        opportunity = str(timeline["opportunity_kind"] or "")
        if float(timeline["opportunity_until"]) > now:
            if opportunity == "cover":
                lines += ["", "🧱 Есть возможность занять укрытие."]
            elif opportunity == "stim":
                lines += ["", "💉 Рядом найден стимулятор."]

    return "\n".join(lines)


def combat_keyboard(game, telegram_id: int) -> InlineKeyboardMarkup:
    now = time.time()
    player = game.get_player(telegram_id)
    weapon = WEAPONS[player["weapon_id"]]
    combat = game.combat_state(telegram_id)
    timeline = game.combat_timeline(telegram_id)
    queued = game.combat_queued_action(telegram_id)

    ammo, medkits = game.combat_queue_resources(telegram_id)
    distance = int(combat["distance"])
    rows: list[list[InlineKeyboardButton]] = []

    if ammo > 0:
        rows.append([
            InlineKeyboardButton(
                text=_queued_button_text(
                    "shoot",
                    f"🔫 Выстрел · {int(PLAYER_ACTION_SECONDS['shoot'])}с",
                    queued,
                ),
                callback_data="combat:shoot",
            ),
            InlineKeyboardButton(
                text=_queued_button_text(
                    "aimed_shot",
                    f"🎯 Прицельный · {int(PLAYER_ACTION_SECONDS['aimed_shot'])}с",
                    queued,
                ),
                callback_data="combat:aimed_shot",
            ),
        ])
        if "burst" in weapon.get("modes", ()) and ammo >= 3:
            rows.append([
                InlineKeyboardButton(
                    text=_queued_button_text(
                        "burst",
                        f"💥 Очередь ×3 · {int(PLAYER_ACTION_SECONDS['burst'])}с",
                        queued,
                    ),
                    callback_data="combat:burst",
                )
            ])

    if distance <= 1:
        rows.append([
            InlineKeyboardButton(
                text=_queued_button_text(
                    "melee",
                    f"🔪 Ближний бой · {int(PLAYER_ACTION_SECONDS['melee'])}с",
                    queued,
                ),
                callback_data="combat:melee",
            )
        ])

    if timeline and float(timeline["opportunity_until"]) > now:
        opportunity = str(timeline["opportunity_kind"] or "")
        if opportunity == "cover":
            rows.append([
                InlineKeyboardButton(
                    text=_queued_button_text(
                        "cover",
                        f"🧱 В укрытие · {int(PLAYER_ACTION_SECONDS['cover'])}с",
                        queued,
                    ),
                    callback_data="combat:cover",
                )
            ])
        elif opportunity == "stim":
            rows.append([
                InlineKeyboardButton(
                    text=_queued_button_text(
                        "stim",
                        f"💉 Стимулятор · {int(PLAYER_ACTION_SECONDS['stim'])}с",
                        queued,
                    ),
                    callback_data="combat:stim",
                )
            ])

    utility_row: list[InlineKeyboardButton] = []
    if medkits > 0:
        utility_row.append(
            InlineKeyboardButton(
                text=_queued_button_text(
                    "medkit",
                    f"🩹 Аптечка · {int(PLAYER_ACTION_SECONDS['medkit'])}с",
                    queued,
                ),
                callback_data="combat:medkit",
            )
        )
    utility_row.append(
        InlineKeyboardButton(
            text=_queued_button_text(
                "flee",
                f"🏃 Отступить · {int(PLAYER_ACTION_SECONDS['flee'])}с",
                queued,
            ),
            callback_data="combat:flee",
        )
    )
    rows.append(utility_row)

    return InlineKeyboardMarkup(inline_keyboard=rows)
