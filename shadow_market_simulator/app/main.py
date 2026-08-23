from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .action_handlers import build_action_router
from .config import load_settings
from .db import Database
from .extended_handlers import build_extended_router
from .handlers import build_router
from .keyboards import notification_actions
from .nightshift import NightshiftSimulationEngine
from .recruitment_handlers import build_recruitment_router
from .recruitment_runtime import NightshiftRecruitmentService
from .services import FinalGameService
from .simulation import iso, utcnow
from .time_handlers import build_time_router


async def notification_loop(
    bot: Bot,
    db: Database,
    simulation: NightshiftSimulationEngine,
    game: FinalGameService,
    recruitment: NightshiftRecruitmentService,
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
                       WHERE status='open'
                         AND notified_at IS NULL
                         AND priority IN ('important','urgent')
                       ORDER BY created_at
                       LIMIT 50"""
                ).fetchall()
                for item in items:
                    marker = "🔴" if item["priority"] == "urgent" else "🟠"
                    try:
                        await bot.send_message(
                            item["player_id"],
                            f"<b>{marker} {item['title']}</b>\n\n{item['body']}",
                            reply_markup=notification_actions(item["id"]),
                        )
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
    simulation = NightshiftSimulationEngine(db, speed=settings.simulation_speed)
    simulation.seed_catalog()
    game = FinalGameService(db, simulation)
    recruitment = NightshiftRecruitmentService(db, speed=settings.simulation_speed)

    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()

    # Most specific routers go first; legacy handlers remain as compatibility fallbacks.
    dispatcher.include_router(
        build_time_router(db, simulation, recruitment, settings.admin_ids)
    )
    dispatcher.include_router(build_action_router(game))
    dispatcher.include_router(
        build_extended_router(
            db,
            game,
            simulation,
            recruitment,
            settings.admin_ids,
        )
    )
    dispatcher.include_router(
        build_recruitment_router(
            db,
            game,
            simulation,
            recruitment,
            settings.admin_ids,
        )
    )
    dispatcher.include_router(
        build_router(db, game, simulation, settings.admin_ids)
    )

    await bot.delete_webhook(drop_pending_updates=True)
    notifier = asyncio.create_task(
        notification_loop(
            bot,
            db,
            simulation,
            game,
            recruitment,
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
