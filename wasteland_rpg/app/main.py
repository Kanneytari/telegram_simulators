from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from . import keyboards, ui
from .combat_view import combat_keyboard, combat_screen
from .config import load_config
from .db import Database
from .handlers import router
from .main_view import main_screen
from .progression_view import character_screen
from .sector_view import sector_screen
from .service import GameService
from .travel_handlers import router as travel_router
from .travel_view import travel_keyboard, travel_screen

# Handlers call these module functions dynamically. Keep the existing modules as the
# single routing surface while specialized presentations stay isolated.
ui.main_screen = main_screen
ui.combat_screen = combat_screen
ui.character_screen = character_screen
ui.sector_screen = sector_screen
ui.travel_screen = travel_screen
keyboards.combat = combat_keyboard
keyboards.travel = travel_keyboard


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    db = Database(config.db_path)
    db.init()
    game = GameService(db)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    dp.include_router(travel_router)
    dp["game"] = game
    dp["config"] = config

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
