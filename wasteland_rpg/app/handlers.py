from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from . import keyboards, ui
from .content import START_INTRO
from .game import GameError, GameService

router = Router()


async def _edit(callback: CallbackQuery, text: str, markup) -> None:
    if not callback.message:
        return
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


async def _error(callback: CallbackQuery, exc: GameError) -> None:
    await callback.answer(str(exc), show_alert=True)


@router.message(CommandStart())
async def start(message: Message, game: GameService) -> None:
    game.ensure_player(message.from_user.id, message.from_user.username)
    await message.answer(
        f"<blockquote>{START_INTRO}</blockquote>",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        ui.main_screen(game, message.from_user.id),
        reply_markup=keyboards.home(),
    )


@router.message(Command("menu"))
async def menu(message: Message, game: GameService) -> None:
    game.ensure_player(message.from_user.id, message.from_user.username)
    player = game.get_player(message.from_user.id)
    if player["state"] == "combat":
        await message.answer(
            ui.combat_screen(game, message.from_user.id),
            reply_markup=keyboards.combat(),
        )
    elif player["state"] == "expedition":
        markup = keyboards.event() if player["pending_event"] else keyboards.expedition()
        screen = (
            ui.event_screen(game, message.from_user.id)
            if player["pending_event"]
            else ui.expedition_screen(game, message.from_user.id)
        )
        await message.answer(screen, reply_markup=markup)
    else:
        await message.answer(
            ui.main_screen(game, message.from_user.id),
            reply_markup=keyboards.home(),
        )


@router.callback_query(F.data == "menu:home")
async def open_home(callback: CallbackQuery, game: GameService) -> None:
    await _edit(callback, ui.main_screen(game, callback.from_user.id), keyboards.home())


@router.callback_query(F.data == "menu:sectors")
async def open_sectors(callback: CallbackQuery, game: GameService) -> None:
    await _edit(
        callback,
        ui.sector_screen(game, callback.from_user.id),
        keyboards.sectors(game, callback.from_user.id),
    )


@router.callback_query(F.data == "menu:inventory")
async def open_inventory(callback: CallbackQuery, game: GameService) -> None:
    await _edit(
        callback,
        ui.inventory_screen(game, callback.from_user.id),
        keyboards.back_home(),
    )


@router.callback_query(F.data == "menu:character")
async def open_character(callback: CallbackQuery, game: GameService) -> None:
    await _edit(
        callback,
        ui.character_screen(game, callback.from_user.id),
        keyboards.character(game, callback.from_user.id),
    )


@router.callback_query(F.data == "menu:shop")
async def open_shop(callback: CallbackQuery, game: GameService) -> None:
    await _edit(
        callback,
        ui.shop_screen(game, callback.from_user.id),
        keyboards.shop(game, callback.from_user.id),
    )


@router.callback_query(F.data == "menu:rules")
async def open_rules(callback: CallbackQuery) -> None:
    await _edit(callback, ui.rules_screen(), keyboards.back_home())


@router.callback_query(F.data.startswith("sector:"))
async def start_sector(callback: CallbackQuery, game: GameService) -> None:
    try:
        text = game.start_expedition(callback.from_user.id, callback.data.split(":", 1)[1])
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(
        callback,
        ui.notice(ui.expedition_screen(game, callback.from_user.id), text),
        keyboards.expedition(),
    )


@router.callback_query(F.data == "expedition:explore")
async def explore(callback: CallbackQuery, game: GameService) -> None:
    try:
        result = game.explore(callback.from_user.id)
    except GameError as exc:
        await _error(callback, exc)
        return
    player = game.get_player(callback.from_user.id)
    if player["state"] == "combat":
        await _edit(
            callback,
            ui.notice(ui.combat_screen(game, callback.from_user.id), result["text"]),
            keyboards.combat(),
        )
    elif player["pending_event"]:
        await _edit(
            callback,
            ui.notice(ui.event_screen(game, callback.from_user.id), result["text"]),
            keyboards.event(),
        )
    else:
        await _edit(
            callback,
            ui.notice(ui.expedition_screen(game, callback.from_user.id), result["text"]),
            keyboards.expedition(),
        )


@router.callback_query(F.data == "expedition:inventory")
async def expedition_inventory(callback: CallbackQuery, game: GameService) -> None:
    await _edit(
        callback,
        ui.inventory_screen(game, callback.from_user.id),
        keyboards.expedition_inventory(),
    )


@router.callback_query(F.data == "expedition:back")
async def expedition_back(callback: CallbackQuery, game: GameService) -> None:
    player = game.get_player(callback.from_user.id)
    if player["pending_event"]:
        await _edit(
            callback,
            ui.event_screen(game, callback.from_user.id),
            keyboards.event(),
        )
    else:
        await _edit(
            callback,
            ui.expedition_screen(game, callback.from_user.id),
            keyboards.expedition(),
        )


@router.callback_query(F.data == "expedition:return")
async def return_home(callback: CallbackQuery, game: GameService) -> None:
    try:
        result = game.return_base(callback.from_user.id)
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(
        callback,
        ui.notice(ui.main_screen(game, callback.from_user.id), result["text"]),
        keyboards.home(),
    )


@router.callback_query(F.data.startswith("event:"))
async def resolve_event(callback: CallbackQuery, game: GameService) -> None:
    action = callback.data.split(":", 1)[1]
    try:
        result = game.resolve_event(
            callback.from_user.id,
            "bypass" if action == "bypass" else "try",
        )
    except GameError as exc:
        await _error(callback, exc)
        return
    player = game.get_player(callback.from_user.id)
    if player["state"] == "base":
        await _edit(
            callback,
            ui.notice(ui.main_screen(game, callback.from_user.id), result["text"]),
            keyboards.home(),
        )
    else:
        await _edit(
            callback,
            ui.notice(ui.expedition_screen(game, callback.from_user.id), result["text"]),
            keyboards.expedition(),
        )


@router.callback_query(F.data.startswith("combat:"))
async def combat_action(callback: CallbackQuery, game: GameService) -> None:
    try:
        result = game.combat_action(
            callback.from_user.id,
            callback.data.split(":", 1)[1],
        )
    except GameError as exc:
        await _error(callback, exc)
        return
    player = game.get_player(callback.from_user.id)
    if player["state"] == "base":
        await _edit(
            callback,
            ui.notice(ui.main_screen(game, callback.from_user.id), result["text"]),
            keyboards.home(),
        )
    elif player["state"] == "expedition":
        await _edit(
            callback,
            ui.notice(ui.expedition_screen(game, callback.from_user.id), result["text"]),
            keyboards.expedition(),
        )
    else:
        await _edit(
            callback,
            ui.notice(ui.combat_screen(game, callback.from_user.id), result["text"]),
            keyboards.combat(),
        )


@router.callback_query(F.data.startswith("attribute:"))
async def upgrade_attribute(callback: CallbackQuery, game: GameService) -> None:
    try:
        message = game.upgrade_attribute(
            callback.from_user.id,
            callback.data.split(":", 1)[1],
        )
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(
        callback,
        ui.notice(ui.character_screen(game, callback.from_user.id), message),
        keyboards.character(game, callback.from_user.id),
    )


@router.callback_query(F.data.startswith("shop:"))
async def shop_action(callback: CallbackQuery, game: GameService) -> None:
    product = callback.data.split(":", 1)[1]
    try:
        message = (
            game.sell_all(callback.from_user.id)
            if product == "sell"
            else game.buy(callback.from_user.id, product)
        )
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(
        callback,
        ui.notice(ui.shop_screen(game, callback.from_user.id), message),
        keyboards.shop(game, callback.from_user.id),
    )
