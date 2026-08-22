from __future__ import annotations

from html import escape

from .ui import level_up_notice


def sector_screen(game, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    location = game.location(telegram_id)
    lines = [
        f"🧭 <b>ВЫЛАЗКИ · {escape(location['name']).upper()}</b>",
        "━━━━━━━━━━━━",
    ]
    notice = level_up_notice(game, player)
    if notice:
        lines.append(notice)

    for sector_id, sector in game.local_sectors(telegram_id):
        unlocked = game.sector_unlocked(player, sector_id)
        mastered = game.sector_mastered(telegram_id, sector_id)
        status = "✅" if mastered else "🟢" if unlocked else "🔒"

        progress = ""
        if unlocked and not mastered:
            progress = f" · {game.sector_max_threat(telegram_id, sector_id)}%"

        lines += [
            f"{status} <b>{sector['icon']} {escape(sector['name'])}</b>{progress}",
            escape(sector["description"]),
            "",
        ]

    return "\n".join(lines).rstrip()
