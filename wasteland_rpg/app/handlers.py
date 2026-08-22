from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from . import keyboards, ui
from .content import START_INTRO
from .game import GameError
from .service import GameService

router = Router()


async def _edit(callback: CallbackQuery, text: str, markup) -> None:
    if not callback.message:
        return
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


async def _error(callback: CallbackQuery, exc: GameError) -> None:
    await callback.answer(str(exc), show_alert=True)


def _bind_callback_combat(callback: CallbackQuery, game: GameService) -> None:
    if not callback.message:
        return
    player = game.get_player(callback.from_user.id)
    if player["state"] == "combat":
        game.bind_combat_message(
            callback.from_user.id,
            callback.message.chat.id,
            callback.message.message_id,
        )


def _shop_view(category: str, game: GameService, telegram_id: int):
    if category == "weapons":
        return ui.shop_weapons_screen(game, telegram_id), keyboards.shop_weapons(game, telegram_id)
    if category == "equipment":
        return ui.shop_equipment_screen(game, telegram_id), keyboards.shop_equipment(game, telegram_id)
    if category == "medicine":
        return ui.shop_medicine_screen(game, telegram_id), keyboards.shop_medicine(game, telegram_id)
    raise GameError("Неизвестная категория товаров.")


def _state_view(game: GameService, telegram_id: int):
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


@router.message(CommandStart())
async def start(message: Message, game: GameService) -> None:
    game.ensure_player(message.from_user.id, message.from_user.username)
    await message.answer(f"<blockquote>{START_INTRO}</blockquote>", reply_markup=ReplyKeyboardRemove())
    text, markup = _state_view(game, message.from_user.id)
    sent = await message.answer(text, reply_markup=markup)
    if game.get_player(message.from_user.id)["state"] == "combat":
        game.bind_combat_message(message.from_user.id, sent.chat.id, sent.message_id)


@router.message(Command("menu"))
async def menu(message: Message, game: GameService) -> None:
    game.ensure_player(message.from_user.id, message.from_user.username)
    text, markup = _state_view(game, message.from_user.id)
    sent = await message.answer(text, reply_markup=markup)
    if game.get_player(message.from_user.id)["state"] == "combat":
        game.bind_combat_message(message.from_user.id, sent.chat.id, sent.message_id)


@router.message(Command("reset"))
async def reset_progress(message: Message, game: GameService) -> None:
    game.ensure_player(message.from_user.id, message.from_user.username)
    await message.answer(
        "⚠️ <b>ПОЛНЫЙ СБРОС ПРОГРЕССА</b>\n"
        "━━━━━━━━━━━━\n"
        "Будут удалены уровень, характеристики, деньги, предметы, склад, груз, "
        "экипировка, открытые поселения и текущая вылазка/дорога.\n\n"
        "Персонаж будет создан заново с начальными параметрами. "
        "Это действие нельзя отменить.",
        reply_markup=keyboards.reset_confirm(),
    )


@router.callback_query(F.data == "reset:cancel")
async def cancel_reset(callback: CallbackQuery, game: GameService) -> None:
    screen, markup = _state_view(game, callback.from_user.id)
    await _edit(callback, ui.notice(screen, "Сброс отменён."), markup)


@router.callback_query(F.data == "reset:confirm")
async def confirm_reset(callback: CallbackQuery, game: GameService) -> None:
    game.db.reset_player(callback.from_user.id)
    game.ensure_player(callback.from_user.id, callback.from_user.username)
    text = (
        "<blockquote>🗑 Прогресс полностью сброшен.</blockquote>\n\n"
        f"<blockquote>{START_INTRO}</blockquote>\n\n"
        f"{ui.main_screen(game, callback.from_user.id)}"
    )
    await _edit(callback, text, keyboards.home())


@router.callback_query(F.data == "menu:home")
async def open_home(callback: CallbackQuery, game: GameService) -> None:
    await _edit(callback, ui.main_screen(game, callback.from_user.id), keyboards.home())


@router.callback_query(F.data == "menu:map")
async def open_map(callback: CallbackQuery, game: GameService) -> None:
    await _edit(callback, ui.map_screen(game, callback.from_user.id), keyboards.map_routes(game, callback.from_user.id))


@router.callback_query(F.data.startswith("route:"))
async def start_route(callback: CallbackQuery, game: GameService) -> None:
    try:
        message = game.start_travel(callback.from_user.id, callback.data.split(":", 1)[1])
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(callback, ui.notice(ui.travel_screen(game, callback.from_user.id), message), keyboards.travel(game, callback.from_user.id))


@router.callback_query(F.data == "road:advance")
async def advance_route(callback: CallbackQuery, game: GameService) -> None:
    try:
        result = game.advance_travel(callback.from_user.id)
    except GameError as exc:
        await _error(callback, exc)
        return
    player = game.get_player(callback.from_user.id)
    if player["state"] == "combat":
        _bind_callback_combat(callback, game)
        screen, markup = ui.combat_screen(game, callback.from_user.id), keyboards.combat(game, callback.from_user.id)
    elif result.get("arrived"):
        screen, markup = ui.main_screen(game, callback.from_user.id), keyboards.home()
    else:
        screen, markup = ui.travel_screen(game, callback.from_user.id), keyboards.travel(game, callback.from_user.id)
    await _edit(callback, ui.notice(screen, result["text"]), markup)


@router.callback_query(F.data == "road:cargo")
async def road_cargo(callback: CallbackQuery, game: GameService) -> None:
    await _edit(callback, ui.inventory_screen(game, callback.from_user.id), keyboards.travel_inventory())


@router.callback_query(F.data == "road:back")
async def road_back(callback: CallbackQuery, game: GameService) -> None:
    await _edit(callback, ui.travel_screen(game, callback.from_user.id), keyboards.travel(game, callback.from_user.id))


@router.callback_query(F.data == "menu:market")
async def open_market(callback: CallbackQuery, game: GameService) -> None:
    await _edit(callback, ui.market_screen(game, callback.from_user.id), keyboards.market(game, callback.from_user.id))


@router.callback_query(F.data.startswith("market:"))
async def market_action(callback: CallbackQuery, game: GameService) -> None:
    parts = callback.data.split(":")
    try:
        if parts[1] == "buy":
            message = game.buy_trade_good(callback.from_user.id, parts[2])
        elif parts[1] == "sell_cargo":
            message = game.sell_cargo(callback.from_user.id)
        elif parts[1] == "load":
            message = game.load_stash_to_cargo(callback.from_user.id)
        elif parts[1] == "unload":
            message = game.unload_cargo(callback.from_user.id)
        else:
            raise GameError("Неизвестное действие рынка.")
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(callback, ui.notice(ui.market_screen(game, callback.from_user.id), message), keyboards.market(game, callback.from_user.id))


@router.callback_query(F.data == "menu:sectors")
async def open_sectors(callback: CallbackQuery, game: GameService) -> None:
    await _edit(callback, ui.sector_screen(game, callback.from_user.id), keyboards.sectors(game, callback.from_user.id))


@router.callback_query(F.data.startswith("sector:"))
async def start_sector(callback: CallbackQuery, game: GameService) -> None:
    try:
        text = game.start_expedition(callback.from_user.id, callback.data.split(":", 1)[1])
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(callback, ui.notice(ui.expedition_screen(game, callback.from_user.id), text), keyboards.expedition())


@router.callback_query(F.data == "expedition:explore")
async def explore(callback: CallbackQuery, game: GameService) -> None:
    try:
        result = game.explore(callback.from_user.id)
    except GameError as exc:
        await _error(callback, exc)
        return
    player = game.get_player(callback.from_user.id)
    if player["state"] == "combat":
        _bind_callback_combat(callback, game)
        screen, markup = ui.combat_screen(game, callback.from_user.id), keyboards.combat(game, callback.from_user.id)
    elif result.get("kind") == "choice":
        screen, markup = ui.choice_screen(game, callback.from_user.id), keyboards.choice(game, callback.from_user.id)
    elif player["pending_event"]:
        screen, markup = ui.event_screen(game, callback.from_user.id), keyboards.event()
    else:
        screen, markup = ui.expedition_screen(game, callback.from_user.id), keyboards.expedition()

    parts = [f"<blockquote>▸ {escape(result['text'])}</blockquote>"]
    if result.get("progress_notice"):
        parts.append(f"<blockquote>{escape(result['progress_notice'])}</blockquote>")
    parts.append(screen)
    await _edit(callback, "\n\n".join(parts), markup)


@router.callback_query(F.data.startswith("choice:"))
async def resolve_choice(callback: CallbackQuery, game: GameService) -> None:
    try:
        result = game.resolve_choice(callback.from_user.id, callback.data.split(":", 1)[1])
    except GameError as exc:
        await _error(callback, exc)
        return
    _bind_callback_combat(callback, game)
    screen, markup = _state_view(game, callback.from_user.id)
    await _edit(callback, ui.notice(screen, result["text"]), markup)


@router.callback_query(F.data.startswith("event:"))
async def resolve_event(callback: CallbackQuery, game: GameService) -> None:
    try:
        result = game.resolve_event(callback.from_user.id, "bypass" if callback.data.endswith("bypass") else "try")
    except GameError as exc:
        await _error(callback, exc)
        return
    screen, markup = _state_view(game, callback.from_user.id)
    await _edit(callback, ui.notice(screen, result["text"]), markup)


@router.callback_query(F.data.startswith("combat:"))
async def combat_action(callback: CallbackQuery, game: GameService) -> None:
    try:
        result = game.combat_action(callback.from_user.id, callback.data.split(":", 1)[1])
    except GameError as exc:
        await _error(callback, exc)
        return
    player = game.get_player(callback.from_user.id)
    screen, markup = _state_view(game, callback.from_user.id)
    if player["state"] == "combat":
        await _edit(callback, screen, markup)
    else:
        await _edit(callback, ui.notice(screen, result.get("text")), markup)


@router.callback_query(F.data == "menu:inventory")
async def open_inventory(callback: CallbackQuery, game: GameService) -> None:
    await _edit(callback, ui.inventory_screen(game, callback.from_user.id), keyboards.back_home())


@router.callback_query(F.data == "expedition:inventory")
async def expedition_inventory(callback: CallbackQuery, game: GameService) -> None:
    await _edit(callback, ui.inventory_screen(game, callback.from_user.id), keyboards.expedition_inventory())


@router.callback_query(F.data == "expedition:back")
async def expedition_back(callback: CallbackQuery, game: GameService) -> None:
    screen, markup = _state_view(game, callback.from_user.id)
    await _edit(callback, screen, markup)


@router.callback_query(F.data == "expedition:return")
async def return_home(callback: CallbackQuery, game: GameService) -> None:
    try:
        result = game.return_base(callback.from_user.id)
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(callback, ui.notice(ui.main_screen(game, callback.from_user.id), result["text"]), keyboards.home())


@router.callback_query(F.data == "menu:character")
async def open_character(callback: CallbackQuery, game: GameService) -> None:
    await _edit(callback, ui.character_screen(game, callback.from_user.id), keyboards.character(game, callback.from_user.id))


@router.callback_query(F.data.startswith("attribute:"))
async def upgrade_attribute(callback: CallbackQuery, game: GameService) -> None:
    try:
        message = game.upgrade_attribute(callback.from_user.id, callback.data.split(":", 1)[1])
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(callback, ui.notice(ui.character_screen(game, callback.from_user.id), message), keyboards.character(game, callback.from_user.id))


@router.callback_query(F.data == "menu:shop")
async def open_shop(callback: CallbackQuery, game: GameService) -> None:
    await _edit(callback, ui.shop_screen(game, callback.from_user.id), keyboards.shop())


@router.callback_query(F.data.startswith("shopcat:"))
async def open_shop_category(callback: CallbackQuery, game: GameService) -> None:
    try:
        screen, markup = _shop_view(callback.data.split(":", 1)[1], game, callback.from_user.id)
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(callback, screen, markup)


@router.callback_query(F.data == "shop:sell")
async def sell_stash(callback: CallbackQuery, game: GameService) -> None:
    try:
        message = game.sell_all(callback.from_user.id)
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(callback, ui.notice(ui.shop_screen(game, callback.from_user.id), message), keyboards.shop())


@router.callback_query(F.data.startswith("shopbuy:"))
async def buy_from_shop(callback: CallbackQuery, game: GameService) -> None:
    _, category, product = callback.data.split(":", 2)
    try:
        message = game.buy(callback.from_user.id, product)
        screen, markup = _shop_view(category, game, callback.from_user.id)
    except GameError as exc:
        await _error(callback, exc)
        return
    await _edit(callback, ui.notice(screen, message), markup)


@router.callback_query(F.data == "menu:rules")
async def open_rules(callback: CallbackQuery) -> None:
    await _edit(callback, ui.rules_screen(), keyboards.back_home())
