from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .analytics_handlers import build_analytics_router
from .analytics_log import AnalyticsLogger, AnalyticsLoggingMiddleware
from .bot import OneShotCallbackMiddleware, notification_loop
from .core import Database, load_settings
from .courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from .courier_recruitment import CourierRecruitmentService
from .gameplay_updates import apply_gameplay_updates
from .handoff_copy_update import apply_handoff_copy_update
from .inbox_lifecycle import install_inbox_lifecycle
from .product_ui_update import apply_product_ui_update
from .release_fixes import apply_release_fixes
from .tutorial import apply_tutorial_updates, build_tutorial_router
from .tutorial_copy_update import apply_tutorial_copy_update
from .tutorial_runtime import apply_tutorial_runtime_fixes
from .ui_admin import build_admin_router
from .ui_commerce import build_commerce_router
from .ui_disputes import build_dispute_router
from .ui_navigation import build_navigation_router
from .ui_staff_handlers import build_staff_router


async def main() -> None:
    apply_gameplay_updates()
    apply_handoff_copy_update()
    apply_product_ui_update()
    settings = load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db = Database(settings.db_path)
    db.init()
    apply_tutorial_updates()
    apply_tutorial_runtime_fixes()
    apply_tutorial_copy_update()
    apply_release_fixes()

    simulation = CourierManagementSimulationEngine(db, speed=settings.simulation_speed)
    simulation.seed_catalog()
    game = CourierManagementGameService(db, simulation)
    recruitment = CourierRecruitmentService(db, speed=settings.simulation_speed)
    install_inbox_lifecycle(db)

    analytics = AnalyticsLogger(db)
    analytics.install()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.callback_query.outer_middleware(OneShotCallbackMiddleware())
    dispatcher.message.outer_middleware(AnalyticsLoggingMiddleware(analytics))
    dispatcher.callback_query.outer_middleware(AnalyticsLoggingMiddleware(analytics))

    dispatcher.include_router(
        build_navigation_router(db, game, simulation, settings.admin_ids)
    )
    dispatcher.include_router(build_tutorial_router(db, game, simulation))
    dispatcher.include_router(build_commerce_router(db, game, simulation))
    dispatcher.include_router(build_staff_router(game, simulation, recruitment))
    dispatcher.include_router(
        build_dispute_router(db, game, simulation, settings.admin_ids)
    )
    dispatcher.include_router(build_analytics_router(db, game, simulation))
    dispatcher.include_router(
        build_admin_router(db, simulation, recruitment, game, settings.admin_ids)
    )

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
        with suppress(asyncio.CancelledError):
            await notifier
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
