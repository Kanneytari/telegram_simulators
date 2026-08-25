from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from .config import load_settings
from .events import (
    BuildingUpgraded,
    ExpeditionCompleted,
    ResidentLeveled,
    ResidentTrainingCompleted,
    SectorMastered,
)
from .handlers import router
from .telegram_state import sessions
from .telegram_views import event_text


NOTIFICATION_EVENT_TYPES = (
    ExpeditionCompleted,
    SectorMastered,
    ResidentLeveled,
    ResidentTrainingCompleted,
    BuildingUpgraded,
)


async def timer_worker(bot: Bot) -> None:
    while True:
        await asyncio.sleep(5)
        for user_id, session in sessions.all_sessions():
            if session.chat_id is None:
                continue
            before = session.notified_event_count
            sessions.sync(user_id)
            new_events = session.engine.event_log[before:]
            session.notified_event_count = len(session.engine.event_log)
            noteworthy = [event for event in new_events if isinstance(event, NOTIFICATION_EVENT_TYPES)]
            if not noteworthy:
                continue
            text = "⏱ Завершились процессы\n\n" + "\n".join(
                event_text(session, event) for event in noteworthy[-8:]
            )
            try:
                await bot.send_message(session.chat_id, text)
            except Exception:
                logging.exception("Could not send process notification to user %s", user_id)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    bot = Bot(token=settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    worker = asyncio.create_task(timer_worker(bot))
    try:
        await dispatcher.start_polling(bot)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
