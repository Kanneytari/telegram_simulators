from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from . import keyboards, ui
from .game import GameError

logger = logging.getLogger(__name__)


def _state_view(game, telegram_id: int):
    player = game.get_player(telegram_id)
    if player["state"] == "combat":
        return ui.combat_screen(game, telegram_id), keyboards.combat(game, telegram_id)
    if player["state"] == "travel":
        return ui.travel_screen(game, telegram_id), keyboards.travel(game, telegram_id)
    if player["state"] == "expedition":
        if game.pending_scene(telegram_id):
            return ui.choice_screen(game, telegram_id), keyboards.choice(game, telegram_id)
        if player["pending_event"]:
            return ui.event_screen(game, telegram_id), keyboards.event()
        return ui.expedition_screen(game, telegram_id), keyboards.expedition()
    return ui.main_screen(game, telegram_id), keyboards.home()


async def combat_update_loop(bot: Bot, game) -> None:
    """Advance all active combats and refresh their bound Telegram message once a second."""
    while True:
        started = time.monotonic()
        try:
            now = time.time()
            targets = game.combat_message_targets()
            results = game.tick_all_combats(now)

            for target in targets:
                telegram_id = int(target["telegram_id"])
                try:
                    text, markup = _state_view(game, telegram_id)
                except GameError:
                    continue

                result = results.get(telegram_id) or {}
                if result.get("finished") and result.get("text"):
                    text = ui.notice(text, str(result["text"]))

                try:
                    await bot.edit_message_text(
                        chat_id=int(target["chat_id"]),
                        message_id=int(target["message_id"]),
                        text=text,
                        reply_markup=markup,
                    )
                except TelegramBadRequest as exc:
                    if "message is not modified" not in str(exc).lower():
                        logger.warning("Combat message update failed for %s: %s", telegram_id, exc)
                except TelegramForbiddenError:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Realtime combat scheduler tick failed")

        elapsed = time.monotonic() - started
        await asyncio.sleep(max(0.1, 1.0 - elapsed))
