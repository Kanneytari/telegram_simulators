from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .admin import AdminError, AdminService
from .content import INVESTMENTS
from .game import GameError, GameService
from .keyboards import (
    back_menu,
    career_menu,
    event_menu,
    investments_menu,
    main_menu,
    reset_confirm_menu,
)

router = Router()


async def _edit(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    if not callback.message:
        return
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=reply_markup)


def _main_markup(
    telegram_id: int,
    game: GameService,
    admin: AdminService,
):
    player = game.get_player(telegram_id)
    return main_menu(
        is_admin=admin.is_admin(telegram_id),
        fast_mode=admin.is_fast_mode(telegram_id),
        actions_left=player["actions_left"],
    )


async def _dashboard(
    callback: CallbackQuery,
    game: GameService,
    admin: AdminService,
    notice: str | None = None,
) -> None:
    telegram_id = callback.from_user.id
    text = game.dashboard(telegram_id)
    if admin.is_fast_mode(telegram_id):
        text += "\n\n🧪 Быстрый режим: <b>включён</b>"
    if notice:
        text = f"{notice}\n\n{text}"
    await _edit(
        callback,
        text,
        _main_markup(telegram_id, game, admin),
    )


@router.message(CommandStart())
async def start(
    message: Message,
    game: GameService,
    admin: AdminService,
) -> None:
    telegram_id = message.from_user.id
    game.ensure_player(telegram_id, message.from_user.username)
    intro = (
        "<b>КАРЬЕРИСТ</b>\n\n"
        "Здесь недостаточно просто хорошо работать. Нужно ещё учиться, быть заметным, "
        "строить связи и не сгореть по дороге.\n\n"
        "Каждый активный день у тебя 5 действий. Новые появляются после 04:00 МСК."
    )
    await message.answer(intro)
    await message.answer(
        game.dashboard(telegram_id),
        reply_markup=_main_markup(telegram_id, game, admin),
    )


@router.message(Command("menu"))
async def menu(
    message: Message,
    game: GameService,
    admin: AdminService,
) -> None:
    telegram_id = message.from_user.id
    game.ensure_player(telegram_id, message.from_user.username)
    text = game.dashboard(telegram_id)
    if admin.is_fast_mode(telegram_id):
        text += "\n\n🧪 Быстрый режим: <b>включён</b>"
    await message.answer(
        text,
        reply_markup=_main_markup(telegram_id, game, admin),
    )


@router.message(Command("reset"))
async def reset_command(
    message: Message,
    admin: AdminService,
) -> None:
    if not admin.is_admin(message.from_user.id):
        await message.answer("⚠️ Команда доступна только администратору.")
        return

    await message.answer(
        "⚠️ Сбросить весь текущий прогресс персонажа?\n"
        "Быстрый режим при этом сохранит своё состояние.",
        reply_markup=reset_confirm_menu(),
    )


@router.message(Command("fast"))
async def fast_command(
    message: Message,
    game: GameService,
    admin: AdminService,
) -> None:
    telegram_id = message.from_user.id
    if not admin.is_admin(telegram_id):
        await message.answer("⚠️ Команда доступна только администратору.")
        return

    game.ensure_player(telegram_id, message.from_user.username)
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip().lower() if len(parts) == 2 else ""

    if arg in {"on", "1", "вкл", "включить"}:
        enabled = admin.set_fast_mode(telegram_id, True)
    elif arg in {"off", "0", "выкл", "выключить"}:
        enabled = admin.set_fast_mode(telegram_id, False)
    elif arg:
        await message.answer("Используй /fast, /fast on или /fast off.")
        return
    else:
        enabled = admin.toggle_fast_mode(telegram_id)

    status = "включён" if enabled else "выключен"
    await message.answer(
        f"🧪 Быстрый режим {status}.",
        reply_markup=_main_markup(telegram_id, game, admin),
    )


@router.callback_query(F.data == "menu:main")
async def open_main(
    callback: CallbackQuery,
    game: GameService,
    admin: AdminService,
) -> None:
    await callback.answer()
    await _dashboard(callback, game, admin)


@router.callback_query(F.data.startswith("action:"))
async def action(
    callback: CallbackQuery,
    game: GameService,
    admin: AdminService,
) -> None:
    await callback.answer()
    action_name = callback.data.split(":", 1)[1]
    try:
        result = game.perform_action(callback.from_user.id, action_name)
    except GameError as exc:
        result = f"⚠️ {exc}"
        if (
            admin.is_fast_mode(callback.from_user.id)
            and game.get_player(callback.from_user.id)["actions_left"] == 0
        ):
            result += "\nНажми «⏭ Следующий день»."
    await _dashboard(callback, game, admin, result)


@router.callback_query(F.data == "menu:event")
async def open_event(
    callback: CallbackQuery,
    game: GameService,
) -> None:
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
async def choose_event(
    callback: CallbackQuery,
    game: GameService,
    admin: AdminService,
) -> None:
    await callback.answer()
    _, event_id, index = callback.data.split(":", 2)
    try:
        result = game.resolve_event(callback.from_user.id, event_id, int(index))
    except GameError as exc:
        result = f"⚠️ {exc}"
    await _dashboard(callback, game, admin, result)


@router.callback_query(F.data == "menu:invest")
async def open_investments(
    callback: CallbackQuery,
    game: GameService,
) -> None:
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
        lines.append(
            f"• <b>{item['title']}</b> — {item['price']:,} ₽".replace(",", " ")
        )
    await _edit(callback, "\n".join(lines), investments_menu())


@router.callback_query(F.data.startswith("buy:"))
async def buy(
    callback: CallbackQuery,
    game: GameService,
    admin: AdminService,
) -> None:
    await callback.answer()
    item_id = callback.data.split(":", 1)[1]
    try:
        result = game.buy_investment(callback.from_user.id, item_id)
    except GameError as exc:
        result = f"⚠️ {exc}"
    await _dashboard(callback, game, admin, result)


@router.callback_query(F.data == "menu:career")
async def open_career(
    callback: CallbackQuery,
    game: GameService,
) -> None:
    await callback.answer()
    p = game.get_player(callback.from_user.id)
    await _edit(
        callback,
        game.career_status(callback.from_user.id),
        career_menu(p),
    )


@router.callback_query(F.data.startswith("promotion:"))
async def promotion(
    callback: CallbackQuery,
    game: GameService,
    admin: AdminService,
) -> None:
    await callback.answer()
    choice = callback.data.split(":", 1)[1]
    track = choice if choice in {"expert", "manager"} else None
    try:
        result = game.claim_promotion(callback.from_user.id, track)
    except GameError as exc:
        result = f"⚠️ {exc}"
    await _dashboard(callback, game, admin, result)


@router.callback_query(F.data == "menu:history")
async def open_history(
    callback: CallbackQuery,
    game: GameService,
) -> None:
    await callback.answer()
    await _edit(
        callback,
        game.recent_history(callback.from_user.id),
        back_menu(),
    )


@router.callback_query(F.data == "admin:fast")
async def toggle_fast(
    callback: CallbackQuery,
    game: GameService,
    admin: AdminService,
) -> None:
    await callback.answer()
    try:
        enabled = admin.toggle_fast_mode(callback.from_user.id)
        result = (
            "🧪 Быстрый режим включён."
            if enabled
            else "🧪 Быстрый режим выключен."
        )
    except AdminError as exc:
        result = f"⚠️ {exc}"
    await _dashboard(callback, game, admin, result)


@router.callback_query(F.data == "admin:next_day")
async def next_day(
    callback: CallbackQuery,
    game: GameService,
    admin: AdminService,
) -> None:
    await callback.answer()
    try:
        result = admin.advance_day(callback.from_user.id)
    except AdminError as exc:
        result = f"⚠️ {exc}"
    await _dashboard(callback, game, admin, result)


@router.callback_query(F.data == "admin:reset:cancel")
async def cancel_reset(
    callback: CallbackQuery,
    game: GameService,
    admin: AdminService,
) -> None:
    await callback.answer("Сброс отменён.")
    await _dashboard(callback, game, admin)


@router.callback_query(F.data == "admin:reset:confirm")
async def confirm_reset(
    callback: CallbackQuery,
    game: GameService,
    admin: AdminService,
) -> None:
    await callback.answer()
    telegram_id = callback.from_user.id
    try:
        admin.reset_player(telegram_id)
    except AdminError as exc:
        await _edit(callback, f"⚠️ {exc}")
        return

    game.ensure_player(telegram_id, callback.from_user.username)
    await _dashboard(
        callback,
        game,
        admin,
        "🗑 Прогресс полностью сброшен. Начинаем заново.",
    )
