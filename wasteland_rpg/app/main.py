from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import load_config
from .db import Database
from .handlers import router
from .progression import ProgressionGameService


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    db = Database(config.db_path)
    db.init()
    game = ProgressionGameService(db)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    dp["game"] = game

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
