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


def _duration_text(seconds: float) -> str:
    return str(int(math.ceil(float(seconds))))


def _button_text(action: str, text: str, queued: str | None, available: bool) -> str:
    if queued == action:
        return f"🕒 {text}"
    if not available:
        return f"▫️ {text}"
    return text


def combat_screen(game, telegram_id: int) -> str:
    now = time.time()
    player = game.get_player(telegram_id)
    enemy = ENEMIES[player["enemy_id"]]
    weapon = WEAPONS[player["weapon_id"]]
    combat = game.combat_state(telegram_id)
    timeline = game.combat_timeline(telegram_id)
    log = [entry for entry in game.combat_log(telegram_id) if "готовит" not in entry.lower()]

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
    opportunity = str(timeline["opportunity_kind"] or "") if timeline else ""
    opportunity_valid = bool(timeline and float(timeline["opportunity_until"]) > now)

    availability = {
        "shoot": ammo >= 1,
        "aimed_shot": ammo >= 1,
        "burst": "burst" in weapon.get("modes", ()) and ammo >= 3,
        "melee": distance <= 1,
        "cover": opportunity_valid and opportunity == "cover",
        "stim": opportunity_valid and opportunity == "stim",
        "medkit": medkits >= 1,
        "flee": True,
    }

    def button(action: str, label: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=_button_text(action, label, queued, availability[action]),
            callback_data=f"combat:{action}",
        )

    rows = [
        [
            button("shoot", f"🔫 Выстрел · {_duration_text(PLAYER_ACTION_SECONDS['shoot'])}с"),
            button(
                "aimed_shot",
                f"🎯 Прицельный · {_duration_text(PLAYER_ACTION_SECONDS['aimed_shot'])}с",
            ),
        ],
        [
            button("burst", f"💥 Очередь ×3 · {_duration_text(PLAYER_ACTION_SECONDS['burst'])}с"),
            button("melee", f"🔪 Ближний бой · {_duration_text(PLAYER_ACTION_SECONDS['melee'])}с"),
        ],
        [
            button("cover", f"🧱 Укрытие · {_duration_text(PLAYER_ACTION_SECONDS['cover'])}с"),
            button("stim", f"💉 Стимулятор · {_duration_text(PLAYER_ACTION_SECONDS['stim'])}с"),
        ],
        [
            button("medkit", f"🩹 Аптечка · {_duration_text(PLAYER_ACTION_SECONDS['medkit'])}с"),
            button("flee", f"🏃 Отступить · {_duration_text(PLAYER_ACTION_SECONDS['flee'])}с"),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)
