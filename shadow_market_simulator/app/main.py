from __future__ import annotations

import asyncio
from contextlib import suppress

from .bootstrap import build_application
from .bot import notification_loop


async def main() -> None:
    app = build_application()

    await app.bot.delete_webhook(drop_pending_updates=True)
    notifier = asyncio.create_task(
        notification_loop(
            app.bot,
            app.db,
            app.simulation,
            app.game,
            app.recruitment,
            app.analytics,
            app.settings.simulation_interval_seconds,
        )
    )
    try:
        await app.dispatcher.start_polling(app.bot)
    finally:
        notifier.cancel()
        with suppress(asyncio.CancelledError):
            await notifier
        await app.bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
