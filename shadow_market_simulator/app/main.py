from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .analytics_handlers import build_analytics_router
from .analytics_log import AnalyticsLogger, AnalyticsLoggingMiddleware
from .config import load_settings
from .courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from .courier_recruitment import CourierRecruitmentService
from .db import Database
from .inbox_lifecycle import install_inbox_lifecycle
from .simulation import iso, utcnow
from .time_handlers import build_time_router
from .ui_commerce import build_commerce_router
from .ui_disputes import build_dispute_router
from .ui_navigation import build_navigation_router
from .ui_staff import build_staff_router


def notification_markup(item) -> InlineKeyboardMarkup:
    kind = str(item["kind"])
    item_id = int(item["id"])
    if kind == "dispute":
        text = "Разобрать"
        callback = f"inbox:dispute:{item_id}"
    elif kind == "recruitment_result":
        text = "Кандидаты"
        callback = "team:candidates"
    else:
        text = "Открыть"
        callback = f"inbox:item:{item_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=callback)],
        [InlineKeyboardButton(text="Меню", callback_data="menu:home")],
    ])


async def notification_loop(
    bot: Bot,
    db: Database,
    simulation: CourierManagementSimulationEngine,
    game: CourierManagementGameService,
    recruitment: CourierRecruitmentService,
    analytics: AnalyticsLogger,
    interval: int,
) -> None:
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
                            text,
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
                        conn.execute(
                            "UPDATE inbox SET notified_at=? WHERE id=?",
                            (iso(utcnow()), item["id"]),
                        )
                    except Exception:
                        logging.exception("Failed to deliver inbox item %s", item["id"])
        except Exception:
            logging.exception("Simulation loop failed")
        await asyncio.sleep(interval)


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db = Database(settings.db_path)
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=settings.simulation_speed)
    simulation.seed_catalog()
    game = CourierManagementGameService(db, simulation)
    recruitment = CourierRecruitmentService(db, speed=settings.simulation_speed)
    install_inbox_lifecycle(db)

    analytics = AnalyticsLogger(db)
    analytics.install()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(AnalyticsLoggingMiddleware(analytics))
    dispatcher.callback_query.outer_middleware(AnalyticsLoggingMiddleware(analytics))

    # One canonical player-facing presentation layer. Legacy UI routers are no longer
    # registered, so identical entities cannot render through competing screen trees.
    dispatcher.include_router(build_navigation_router(db, game, simulation, settings.admin_ids))
    dispatcher.include_router(build_commerce_router(db, game, simulation))
    dispatcher.include_router(build_staff_router(game, simulation, recruitment))
    dispatcher.include_router(build_dispute_router(game))
    dispatcher.include_router(build_analytics_router(db, game, simulation))
    dispatcher.include_router(build_time_router(db, simulation, recruitment, game, settings.admin_ids))

    await bot.delete_webhook(drop_pending_updates=True)
    notifier = asyncio.create_task(
        notification_loop(
            bot,
            db,
            simulation,
            game,
            recruitment,
            analytics,
            settings.simulation_interval_seconds,
        )
    )
    try:
        await dispatcher.start_polling(bot)
    finally:
        notifier.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
