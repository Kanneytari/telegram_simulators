from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .admin import AdminService
from .config import load_config
from .db import Database
from .game import GameService
from .handlers import router
from .opportunities import OpportunityService
from .project_play import ProjectPlayService
from .session import SessionService


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()

    db = Database(config.db_path)
    db.init()
    game = GameService(db)
    session = SessionService(game)
    opportunities = OpportunityService(game)
    project_play = ProjectPlayService(game)
    admin = AdminService(db, game, config.admin_ids)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    dp["game"] = game
    dp["session"] = session
    dp["opportunities"] = opportunities
    dp["project_play"] = project_play
    dp["admin"] = admin

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
