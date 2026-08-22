from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .content import INVESTMENTS
from .game import GameError, GameService
from .keyboards import (
    back_menu,
    career_menu,
    event_menu,
    investments_menu,
    main_menu,
)

router = Router()


async def _edit(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    if not callback.message:
        return
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=reply_markup)


async def _dashboard(callback: CallbackQuery, game: GameService, notice: str | None = None) -> None:
    text = game.dashboard(callback.from_user.id)
    if notice:
        text = f"{notice}\n\n{text}"
    await _edit(callback, text, main_menu())


@router.message(CommandStart())
async def start(message: Message, game: GameService) -> None:
    game.ensure_player(message.from_user.id, message.from_user.username)
    intro = (
        "<b>КАРЬЕРИСТ</b>\n\n"
        "Здесь недостаточно просто хорошо работать. Нужно ещё учиться, быть заметным, "
        "строить связи и не сгореть по дороге.\n\n"
        "Каждый активный день у тебя 5 действий. Новые появляются после 04:00 МСК."
    )
    await message.answer(intro)
    await message.answer(game.dashboard(message.from_user.id), reply_markup=main_menu())


@router.message(Command("menu"))
async def menu(message: Message, game: GameService) -> None:
    game.ensure_player(message.from_user.id, message.from_user.username)
    await message.answer(game.dashboard(message.from_user.id), reply_markup=main_menu())


@router.callback_query(F.data == "menu:main")
async def open_main(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    await _dashboard(callback, game)


@router.callback_query(F.data.startswith("action:"))
async def action(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    action_name = callback.data.split(":", 1)[1]
    try:
        result = game.perform_action(callback.from_user.id, action_name)
    except GameError as exc:
        result = f"⚠️ {exc}"
    await _dashboard(callback, game, result)


@router.callback_query(F.data == "menu:event")
async def open_event(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    event = game.get_daily_event(callback.from_user.id)
    if event["choice_index"] is None:
        text = f"🎲 <b>Событие дня</b>\n\n{event['text']}"
    else:
        chosen_title, _, chosen_result = event["choices"][event["choice_index"]]
        text = (
            f"🎲 <b>Событие дня</b>\n\n{event['text']}\n\n"
            f"Твой выбор: <b>{chosen_title}</b>\n{chosen_result}"
        )
    await _edit(callback, text, event_menu(event))


@router.callback_query(F.data.startswith("event:"))
async def choose_event(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    _, event_id, index = callback.data.split(":", 2)
    try:
        result = game.resolve_event(callback.from_user.id, event_id, int(index))
    except GameError as exc:
        result = f"⚠️ {exc}"
    await _dashboard(callback, game, result)


@router.callback_query(F.data == "menu:invest")
async def open_investments(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    p = game.get_player(callback.from_user.id)
    lines = [
        "💸 <b>Вложения в себя</b>",
        "",
        f"На руках: {p['money']:,} ₽".replace(",", " "),
        "Можно сделать только одно вложение за активный день.",
        "",
    ]
    for item in INVESTMENTS.values():
        lines.append(f"• <b>{item['title']}</b> — {item['price']:,} ₽".replace(",", " "))
    await _edit(callback, "\n".join(lines), investments_menu())


@router.callback_query(F.data.startswith("buy:"))
async def buy(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    item_id = callback.data.split(":", 1)[1]
    try:
        result = game.buy_investment(callback.from_user.id, item_id)
    except GameError as exc:
        result = f"⚠️ {exc}"
    await _dashboard(callback, game, result)


@router.callback_query(F.data == "menu:career")
async def open_career(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    p = game.get_player(callback.from_user.id)
    await _edit(callback, game.career_status(callback.from_user.id), career_menu(p))


@router.callback_query(F.data.startswith("promotion:"))
async def promotion(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    choice = callback.data.split(":", 1)[1]
    track = choice if choice in {"expert", "manager"} else None
    try:
        result = game.claim_promotion(callback.from_user.id, track)
    except GameError as exc:
        result = f"⚠️ {exc}"
    await _dashboard(callback, game, result)


@router.callback_query(F.data == "menu:history")
async def open_history(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    await _edit(callback, game.recent_history(callback.from_user.id), back_menu())
