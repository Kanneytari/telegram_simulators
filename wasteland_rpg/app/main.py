from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from . import keyboards, ui
from .combat_runtime import combat_update_loop
from .combat_view import combat_keyboard, combat_screen
from .config import load_config
from .db import Database
from .handlers import router
from .main_view import main_screen
from .progression_view import character_screen
from .queued_combat_service import GameService
from .rules_view import rules_screen
from .sector_view import sector_screen

# Handlers call these module functions dynamically. Keep the existing modules as the
# single routing surface while specialized presentations stay isolated.
ui.main_screen = main_screen
ui.combat_screen = combat_screen
ui.character_screen = character_screen
ui.rules_screen = rules_screen
ui.sector_screen = sector_screen
keyboards.combat = combat_keyboard


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
    dp["game"] = game

    await bot.delete_webhook(drop_pending_updates=True)
    combat_task = asyncio.create_task(combat_update_loop(bot, game))
    try:
        await dp.start_polling(bot)
    finally:
        combat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await combat_task


if __name__ == "__main__":
    asyncio.run(main())
