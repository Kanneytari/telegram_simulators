from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..core.database import Database
from app.engine.simulation import iso, utcnow
from ..ui_common import normalize_text


def notification_markup(item) -> InlineKeyboardMarkup:
    kind = str(item["kind"])
    item_id = int(item["id"])
    if kind == "dispute":
        text = "⚖️ Разобрать"
        callback = f"inbox:dispute:{item_id}"
    elif kind == "recruitment_result":
        text = "👥 Кандидаты"
        callback = "team:candidates"
    else:
        text = "📂 Открыть"
        callback = f"inbox:item:{item_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📨 {text}", callback_data=callback)],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home")],
        ]
    )


async def notification_loop(
    bot: Bot,
    db: Database,
    simulation,
    game,
    recruitment,
    analytics,
    interval: int,
) -> None:
    """Advance background systems and deliver important inbox items."""
    while True:
        try:
            simulation.advance_all()
            recruitment.advance_all()
            game.process_payroll_all()
            with db.connect() as conn:
                items = conn.execute(
                    """SELECT * FROM inbox
                       WHERE status='open' AND notified_at IS NULL
                         AND priority IN ('important','urgent')
                       ORDER BY created_at LIMIT 50"""
                ).fetchall()
            for item in items:
                marker = "🔴" if item["priority"] == "urgent" else "🟡"
                body = str(item["body"] or "").strip().replace("\n\n", "\n")
                if len(body) > 220:
                    body = body[:217].rstrip() + "…"
                text = f"<b>{marker} {item['title']}</b>"
                if body:
                    text += f"\n\n{body}"
                try:
                    await bot.send_message(
                        item["player_id"],
                        normalize_text(text),
                        reply_markup=notification_markup(item),
                    )
                    try:
                        analytics.log_notification(
                            int(item["player_id"]),
                            int(item["id"]),
                            str(item["kind"]),
                            str(item["priority"]),
                        )
                    except Exception:
                        logging.exception("Failed to log notification %s", item["id"])
                    with db.connect() as conn:
                        conn.execute(
                            "UPDATE inbox SET notified_at=? WHERE id=? AND notified_at IS NULL",
                            (iso(utcnow()), item["id"]),
                        )
                except Exception:
                    logging.exception("Failed to deliver inbox item %s", item["id"])
        except Exception:
            logging.exception("Simulation loop failed")
        await asyncio.sleep(interval)
