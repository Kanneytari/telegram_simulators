from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import load_settings
from .db import Database
from .game import GameService
from .handlers import build_router
from .keyboards import notification_actions
from .recruitment import RecruitmentService
from .recruitment_handlers import build_recruitment_router
from .simulation import SimulationEngine, iso, utcnow


async def notification_loop(
    bot: Bot,
    db: Database,
    simulation: SimulationEngine,
    recruitment: RecruitmentService,
    interval: int,
) -> None:
    while True:
        try:
            simulation.advance_all()
            recruitment.advance_all()
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
    simulation = SimulationEngine(db, speed=settings.simulation_speed)
    simulation.seed_catalog()
    game = GameService(db, simulation)
    recruitment = RecruitmentService(db, speed=settings.simulation_speed)

    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    # Новый роутер регистрируется первым и перехватывает старые callback-и найма.
    # Это позволяет сохранить совместимость со старыми сообщениями бота.
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
