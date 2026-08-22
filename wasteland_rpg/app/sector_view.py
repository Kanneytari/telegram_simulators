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
        lines += [
            f"{status} <b>{sector['icon']} {escape(sector['name'])}</b> · опасность {sector['danger']}/3",
            escape(sector["description"]),
        ]
        if mastered:
            lines.append("Освоено: достигнута угроза 100/100.")
        elif not unlocked:
            previous_name = game.sector_unlock_requirement(sector_id)
            lines.append(f"Нужно: достичь угрозы 100/100 в «{escape(previous_name)}».")
        else:
            max_threat = game.sector_max_threat(telegram_id, sector_id)
            if max_threat > 0:
                lines.append(f"Максимальная достигнутая угроза: {max_threat}/100.")
        lines.append("")

    return "\n".join(lines).rstrip()
