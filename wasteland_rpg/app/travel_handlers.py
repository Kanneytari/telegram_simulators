from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from . import keyboards, ui
from .game import GameError
from .service import GameService
from .travel_control import turn_travel

router = Router()


@router.callback_query(F.data == "road:turn")
async def turn_route(callback: CallbackQuery, game: GameService) -> None:
    try:
        result = turn_travel(game, callback.from_user.id)
    except GameError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    if not callback.message:
        await callback.answer()
        return

    player = game.get_player(callback.from_user.id)
    if result.get("arrived") or player["state"] == "base":
        screen = ui.main_screen(game, callback.from_user.id)
        markup = keyboards.home()
    else:
        screen = ui.travel_screen(game, callback.from_user.id)
        markup = keyboards.travel(game, callback.from_user.id)

    await callback.message.edit_text(
        ui.notice(screen, result.get("text")),
        reply_markup=markup,
    )
    await callback.answer()
