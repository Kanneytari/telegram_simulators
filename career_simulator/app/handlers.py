from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .admin import AdminError, AdminService
from .game import GameError, GameService
from .keyboards import (
    back_menu,
    career_menu,
    focus_menu,
    inbox_menu,
    investments_menu,
    main_menu,
    project_menu,
    reset_confirm_menu,
)
from .session import SessionService
from .ui import (
    career_screen,
    focus_screen,
    history_screen,
    home_screen,
    inbox_screen,
    investments_screen,
    project_screen,
    start_intro,
    with_notice,
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
    session: SessionService,
    admin: AdminService,
):
    player = game.get_player(telegram_id)
    inbox = session.inbox_progress(telegram_id)
    return main_menu(
        unread=inbox["unread"],
        is_admin=admin.is_admin(telegram_id),
        fast_mode=admin.is_fast_mode(telegram_id),
        actions_left=player["actions_left"],
        active_focus=bool(session.active_focus(telegram_id)),
    )


def _home_text(
    telegram_id: int,
    game: GameService,
    session: SessionService,
    admin: AdminService,
    notice: str | None = None,
) -> str:
    screen = home_screen(
        game,
        session,
        telegram_id,
        fast_mode=admin.is_fast_mode(telegram_id),
    )
    return with_notice(screen, notice)


async def _dashboard(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
    admin: AdminService,
    notice: str | None = None,
) -> None:
    telegram_id = callback.from_user.id
    await _edit(
        callback,
        _home_text(telegram_id, game, session, admin, notice),
        _main_markup(telegram_id, game, session, admin),
    )


@router.message(CommandStart())
async def start(
    message: Message,
    game: GameService,
    session: SessionService,
    admin: AdminService,
) -> None:
    telegram_id = message.from_user.id
    game.ensure_player(telegram_id, message.from_user.username)
    text = (
        f"{home_screen(game, session, telegram_id, fast_mode=admin.is_fast_mode(telegram_id))}"
        f"\n\n<blockquote>{start_intro()}</blockquote>"
    )
    await message.answer(
        text,
        reply_markup=_main_markup(telegram_id, game, session, admin),
    )


@router.message(Command("menu"))
async def menu(
    message: Message,
    game: GameService,
    session: SessionService,
    admin: AdminService,
) -> None:
    telegram_id = message.from_user.id
    game.ensure_player(telegram_id, message.from_user.username)
    await message.answer(
        _home_text(telegram_id, game, session, admin),
        reply_markup=_main_markup(telegram_id, game, session, admin),
    )


@router.message(Command("reset"))
async def reset_command(message: Message, admin: AdminService) -> None:
    if not admin.is_admin(message.from_user.id):
        await message.answer("Команда доступна только администратору.")
        return
    await message.answer(
        "<b>Сброс прогресса</b>\n\nУдалить персонажа и всю его игровую историю? "
        "Настройка быстрого режима сохранится.",
        reply_markup=reset_confirm_menu(),
    )


@router.message(Command("fast"))
async def fast_command(
    message: Message,
    game: GameService,
    session: SessionService,
    admin: AdminService,
) -> None:
    telegram_id = message.from_user.id
    if not admin.is_admin(telegram_id):
        await message.answer("Команда доступна только администратору.")
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

    notice = f"Быстрый режим {'включён' if enabled else 'выключен'}."
    await message.answer(
        _home_text(telegram_id, game, session, admin, notice),
        reply_markup=_main_markup(telegram_id, game, session, admin),
    )


@router.callback_query(F.data == "menu:main")
async def open_main(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
    admin: AdminService,
) -> None:
    await callback.answer()
    await _dashboard(callback, game, session, admin)


@router.callback_query(F.data == "menu:project")
async def open_project(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
) -> None:
    await callback.answer()
    player = game.get_player(callback.from_user.id)
    active = session.active_focus(callback.from_user.id)
    await _edit(
        callback,
        project_screen(game, session, callback.from_user.id),
        project_menu(
            actions_left=player["actions_left"],
            active_focus=bool(active),
            focus_left=session.focus_runs_left(callback.from_user.id),
        ),
    )


@router.callback_query(F.data == "project:quick")
async def quick_work(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
) -> None:
    await callback.answer()
    if session.active_focus(callback.from_user.id):
        result = "Сначала закончи начатую фокус-сессию."
    else:
        try:
            result = game.perform_action(callback.from_user.id, "work")
        except GameError as exc:
            result = str(exc)
    player = game.get_player(callback.from_user.id)
    await _edit(
        callback,
        with_notice(project_screen(game, session, callback.from_user.id), result),
        project_menu(
            actions_left=player["actions_left"],
            active_focus=bool(session.active_focus(callback.from_user.id)),
            focus_left=session.focus_runs_left(callback.from_user.id),
        ),
    )


@router.callback_query(F.data == "focus:start")
async def start_focus(callback: CallbackQuery, session: SessionService) -> None:
    await callback.answer()
    notice = None
    try:
        session.start_focus(callback.from_user.id)
    except GameError as exc:
        notice = str(exc)
    view = session.focus_view(callback.from_user.id)
    if not view:
        await _edit(
            callback,
            with_notice("<b>Карьерист · Фокус</b>", notice),
            back_menu(),
        )
        return
    await _edit(
        callback,
        with_notice(focus_screen(session, callback.from_user.id), notice),
        focus_menu(view["step"]),
    )


@router.callback_query(F.data == "focus:open")
async def open_focus(callback: CallbackQuery, session: SessionService) -> None:
    await callback.answer()
    view = session.focus_view(callback.from_user.id)
    if not view:
        await _edit(
            callback,
            "<b>Карьерист · Фокус</b>\n\nАктивной сессии нет.",
            back_menu(),
        )
        return
    await _edit(
        callback,
        focus_screen(session, callback.from_user.id),
        focus_menu(view["step"]),
    )


@router.callback_query(F.data.startswith("focus:choice:"))
async def choose_focus(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
) -> None:
    await callback.answer()
    choice_index = int(callback.data.rsplit(":", 1)[1])
    try:
        result = session.resolve_focus(callback.from_user.id, choice_index)
    except GameError as exc:
        result = {"finished": True, "notice": str(exc)}

    if not result["finished"]:
        view = session.focus_view(callback.from_user.id)
        await _edit(
            callback,
            with_notice(focus_screen(session, callback.from_user.id), result["notice"]),
            focus_menu(view["step"]),
        )
        return

    player = game.get_player(callback.from_user.id)
    await _edit(
        callback,
        with_notice(project_screen(game, session, callback.from_user.id), result["notice"]),
        project_menu(
            actions_left=player["actions_left"],
            active_focus=False,
            focus_left=session.focus_runs_left(callback.from_user.id),
        ),
    )


@router.callback_query(F.data == "menu:inbox")
async def open_inbox(callback: CallbackQuery, session: SessionService) -> None:
    await callback.answer()
    item = session.next_inbox_item(callback.from_user.id)
    await _edit(
        callback,
        inbox_screen(session, callback.from_user.id),
        inbox_menu(item),
    )


@router.callback_query(F.data.startswith("inbox:"))
async def choose_inbox(callback: CallbackQuery, session: SessionService) -> None:
    await callback.answer()
    _, slot, choice = callback.data.split(":", 2)
    try:
        result = session.resolve_inbox(callback.from_user.id, int(slot), int(choice))
    except GameError as exc:
        result = str(exc)
    item = session.next_inbox_item(callback.from_user.id)
    await _edit(
        callback,
        with_notice(inbox_screen(session, callback.from_user.id), result),
        inbox_menu(item),
    )


@router.callback_query(F.data.startswith("action:"))
async def action(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
    admin: AdminService,
) -> None:
    await callback.answer()
    if session.active_focus(callback.from_user.id):
        result = "Сначала закончи начатую фокус-сессию."
    else:
        action_name = callback.data.split(":", 1)[1]
        try:
            result = game.perform_action(callback.from_user.id, action_name)
        except GameError as exc:
            result = str(exc)
            if (
                admin.is_fast_mode(callback.from_user.id)
                and game.get_player(callback.from_user.id)["actions_left"] == 0
            ):
                result += " Перейти дальше можно кнопкой «Следующий день»."
    await _dashboard(callback, game, session, admin, result)


@router.callback_query(F.data == "menu:invest")
async def open_investments(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    await _edit(
        callback,
        investments_screen(game, callback.from_user.id),
        investments_menu(),
    )


@router.callback_query(F.data.startswith("buy:"))
async def buy(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
    admin: AdminService,
) -> None:
    await callback.answer()
    item_id = callback.data.split(":", 1)[1]
    try:
        result = game.buy_investment(callback.from_user.id, item_id)
    except GameError as exc:
        result = str(exc)
    await _dashboard(callback, game, session, admin, result)


@router.callback_query(F.data == "menu:career")
async def open_career(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    player = game.get_player(callback.from_user.id)
    await _edit(
        callback,
        career_screen(game, callback.from_user.id),
        career_menu(player),
    )


@router.callback_query(F.data.startswith("promotion:"))
async def promotion(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
    admin: AdminService,
) -> None:
    await callback.answer()
    choice = callback.data.split(":", 1)[1]
    track = choice if choice in {"expert", "manager"} else None
    try:
        result = game.claim_promotion(callback.from_user.id, track)
    except GameError as exc:
        result = str(exc)
    await _dashboard(callback, game, session, admin, result)


@router.callback_query(F.data == "menu:history")
async def open_history(callback: CallbackQuery, game: GameService) -> None:
    await callback.answer()
    await _edit(callback, history_screen(game, callback.from_user.id), back_menu())


@router.callback_query(F.data == "admin:fast")
async def toggle_fast(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
    admin: AdminService,
) -> None:
    await callback.answer()
    try:
        enabled = admin.toggle_fast_mode(callback.from_user.id)
        result = f"Быстрый режим {'включён' if enabled else 'выключен'}."
    except AdminError as exc:
        result = str(exc)
    await _dashboard(callback, game, session, admin, result)


@router.callback_query(F.data == "admin:next_day")
async def next_day(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
    admin: AdminService,
) -> None:
    await callback.answer()
    try:
        result = admin.advance_day(callback.from_user.id)
    except AdminError as exc:
        result = str(exc)
    await _dashboard(callback, game, session, admin, result)


@router.callback_query(F.data == "admin:reset:cancel")
async def cancel_reset(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
    admin: AdminService,
) -> None:
    await callback.answer("Сброс отменён.")
    await _dashboard(callback, game, session, admin)


@router.callback_query(F.data == "admin:reset:confirm")
async def confirm_reset(
    callback: CallbackQuery,
    game: GameService,
    session: SessionService,
    admin: AdminService,
) -> None:
    await callback.answer()
    telegram_id = callback.from_user.id
    try:
        admin.reset_player(telegram_id)
    except AdminError as exc:
        await _edit(callback, str(exc))
        return

    game.ensure_player(telegram_id, callback.from_user.username)
    await _dashboard(
        callback,
        game,
        session,
        admin,
        "Прогресс сброшен. Начинаем заново.",
    )
