from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .action_handlers import build_action_router
from .analytics_handlers import build_analytics_router
from .analytics_log import AnalyticsLogger, AnalyticsLoggingMiddleware
from .config import load_settings
from .db import Database
from .dispute_handlers import build_dispute_router
from .extended_handlers import build_extended_router
from .handlers import build_router
from .keyboards import notification_actions
from .operations_handlers import build_operations_router
from .procurement_handlers import build_procurement_router
from .procurement_market import ProcurementMarketGameService, ProcurementMarketSimulationEngine
from .recruitment_handlers import build_recruitment_router
from .recruitment_runtime import NightshiftRecruitmentService
from .simulation import iso, utcnow
from .storefront_handlers import build_storefront_router
from .time_handlers import build_time_router
from .workflow_allocation_handlers import build_workflow_allocation_router
from .workflow_dashboard_handlers import build_workflow_dashboard_router
from .workflow_handlers import build_workflow_router
from .workflow_reassign_handlers import build_workflow_reassign_router


async def notification_loop(
    bot: Bot,
    db: Database,
    simulation: ProcurementMarketSimulationEngine,
    game: ProcurementMarketGameService,
    recruitment: NightshiftRecruitmentService,
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
                    marker = "🔴" if item["priority"] == "urgent" else "🟠"
                    try:
                        await bot.send_message(
                            item["player_id"],
                            f"<b>{marker} {item['title']}</b>\n\n{item['body']}",
                            reply_markup=notification_actions(item["id"]),
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
                        conn.execute("UPDATE inbox SET notified_at=? WHERE id=?", (iso(utcnow()), item["id"]))
                    except Exception:
                        logging.exception("Failed to deliver inbox item %s", item["id"])
        except Exception:
            logging.exception("Simulation loop failed")
        await asyncio.sleep(interval)


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db = Database(settings.db_path)
    db.init()
    simulation = ProcurementMarketSimulationEngine(db, speed=settings.simulation_speed)
    simulation.seed_catalog()
    game = ProcurementMarketGameService(db, simulation)
    recruitment = NightshiftRecruitmentService(db, speed=settings.simulation_speed)

    # Install after all feature schemas so triggers can reference workflow/recruitment tables.
    analytics = AnalyticsLogger(db)
    analytics.install()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()

    dispatcher.message.outer_middleware(AnalyticsLoggingMiddleware(analytics))
    dispatcher.callback_query.outer_middleware(AnalyticsLoggingMiddleware(analytics))

    dispatcher.include_router(build_workflow_dashboard_router(db, game, simulation, settings.admin_ids))
    dispatcher.include_router(build_workflow_reassign_router(game))
    dispatcher.include_router(build_workflow_allocation_router(game))
    dispatcher.include_router(build_workflow_router(game))
    dispatcher.include_router(build_procurement_router(game))
    dispatcher.include_router(build_operations_router(game))
    dispatcher.include_router(build_dispute_router(game))
    dispatcher.include_router(build_storefront_router(db, game, simulation))
    dispatcher.include_router(build_analytics_router(db, game, simulation))
    dispatcher.include_router(build_time_router(db, simulation, recruitment, game, settings.admin_ids))
    dispatcher.include_router(build_action_router(game))
    dispatcher.include_router(build_extended_router(db, game, simulation, recruitment, settings.admin_ids))
    dispatcher.include_router(build_recruitment_router(db, game, simulation, recruitment, settings.admin_ids))
    dispatcher.include_router(build_router(db, game, simulation, settings.admin_ids))

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
