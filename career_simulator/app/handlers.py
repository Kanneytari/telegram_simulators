from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from .admin import AdminError, AdminService
from .content import INVESTMENTS
from .game import GameError, GameService
from .keyboards import (
    ADMIN,
    BACK,
    CANCEL,
    CAREER,
    CONFIRM_RESET,
    FAST,
    HISTORY,
    HOME,
    INBOX,
    INVESTMENTS_BUTTON,
    LEARN,
    MORE,
    NETWORK,
    NEXT_DAY,
    OPPORTUNITIES,
    PORTFOLIO,
    PROJECT,
    RESET,
    REST,
    SHOW,
    admin_menu,
    career_menu,
    inbox_menu,
    investments_menu,
    main_menu,
    more_menu,
    opportunity_board_menu,
    opportunity_choice_menu,
    project_menu,
    reset_confirm_menu,
)
from .opportunities import OpportunityService
from .project_play import ProjectPlayService, TACTICS
from .session import SessionService
from .ui import (
    career_screen,
    history_screen,
    home_screen,
    inbox_screen,
    investments_screen,
    opportunity_board_screen,
    opportunity_screen,
    portfolio_screen,
    project_screen,
    start_intro,
    with_notice,
)

router = Router()


def _home_markup(admin: AdminService, telegram_id: int):
    return main_menu(is_admin=admin.is_admin(telegram_id))


def _home_text(
    game: GameService,
    session: SessionService,
    opportunities: OpportunityService,
    project_play: ProjectPlayService,
    admin: AdminService,
    telegram_id: int,
    notice: str | None = None,
) -> str:
    screen = home_screen(
        game,
        session,
        opportunities,
        project_play,
        telegram_id,
        fast_mode=admin.is_fast_mode(telegram_id),
    )
    return with_notice(screen, notice)


async def _send_home(
    message: Message,
    game: GameService,
    session: SessionService,
    opportunities: OpportunityService,
    project_play: ProjectPlayService,
    admin: AdminService,
    notice: str | None = None,
) -> None:
    telegram_id = message.from_user.id
    await message.answer(
        _home_text(
            game,
            session,
            opportunities,
            project_play,
            admin,
            telegram_id,
            notice,
        ),
        reply_markup=_home_markup(admin, telegram_id),
    )


@router.message(CommandStart())
async def start(
    message: Message,
    game: GameService,
    session: SessionService,
    opportunities: OpportunityService,
    project_play: ProjectPlayService,
    admin: AdminService,
) -> None:
    telegram_id = message.from_user.id
    game.ensure_player(telegram_id, message.from_user.username)
    await message.answer(
        f"<blockquote>{start_intro()}</blockquote>\n\n"
        + _home_text(game, session, opportunities, project_play, admin, telegram_id),
        reply_markup=_home_markup(admin, telegram_id),
    )


@router.message(Command("menu"))
@router.message(F.text.in_({HOME, BACK}))
async def open_home(
    message: Message,
    game: GameService,
    session: SessionService,
    opportunities: OpportunityService,
    project_play: ProjectPlayService,
    admin: AdminService,
) -> None:
    game.ensure_player(message.from_user.id, message.from_user.username)
    await _send_home(message, game, session, opportunities, project_play, admin)


@router.message(F.text == PROJECT)
async def open_project(
    message: Message,
    game: GameService,
    project_play: ProjectPlayService,
) -> None:
    player = game.get_player(message.from_user.id)
    await message.answer(
        project_screen(game, project_play, message.from_user.id),
        reply_markup=project_menu(actions_left=player["actions_left"]),
    )


@router.message(F.text.in_({TACTICS["fast"]["title"], TACTICS["careful"]["title"], TACTICS["team"]["title"]}))
async def project_tactic(
    message: Message,
    game: GameService,
    project_play: ProjectPlayService,
) -> None:
    tactic_by_title = {item["title"]: tactic_id for tactic_id, item in TACTICS.items()}
    try:
        result = project_play.work(message.from_user.id, tactic_by_title[message.text])
    except GameError as exc:
        result = str(exc)
    player = game.get_player(message.from_user.id)
    await message.answer(
        with_notice(project_screen(game, project_play, message.from_user.id), result),
        reply_markup=project_menu(actions_left=player["actions_left"]),
    )


@router.message(F.text == OPPORTUNITIES)
async def open_opportunities(
    message: Message,
    game: GameService,
    opportunities: OpportunityService,
) -> None:
    view = opportunities.current(message.from_user.id)
    if view:
        await message.answer(
            opportunity_screen(opportunities, message.from_user.id),
            reply_markup=opportunity_choice_menu(view),
        )
        return

    items = opportunities.board(message.from_user.id)
    player = game.get_player(message.from_user.id)
    can_start = opportunities.runs_left(message.from_user.id) > 0 and player["actions_left"] > 0
    await message.answer(
        opportunity_board_screen(game, opportunities, message.from_user.id),
        reply_markup=opportunity_board_menu(items, can_start=can_start),
    )


@router.message(F.text.startswith("🎯 "))
async def start_opportunity(
    message: Message,
    opportunities: OpportunityService,
) -> None:
    try:
        slot = int(message.text.split(" ", 2)[1])
        opportunities.start(message.from_user.id, slot)
        view = opportunities.current(message.from_user.id)
        await message.answer(
            opportunity_screen(opportunities, message.from_user.id),
            reply_markup=opportunity_choice_menu(view),
        )
    except (ValueError, GameError) as exc:
        await message.answer(str(exc))


@router.message(F.text.startswith("🎲 "))
async def resolve_opportunity(
    message: Message,
    game: GameService,
    opportunities: OpportunityService,
) -> None:
    try:
        choice_index = int(message.text.split(" ", 2)[1]) - 1
        result = opportunities.resolve(message.from_user.id, choice_index)
    except (ValueError, GameError) as exc:
        await message.answer(str(exc))
        return

    outcome = (
        f"{'✓' if result['success'] else '✕'} {result['text']} "
        f"(шанс был {result['chance']}%)"
    )
    if not result["finished"]:
        view = opportunities.current(message.from_user.id)
        await message.answer(
            with_notice(opportunity_screen(opportunities, message.from_user.id), outcome),
            reply_markup=opportunity_choice_menu(view),
        )
        return

    outcome += f"\nИтог: {result['tier']} · {result['successes']}/3."
    items = opportunities.board(message.from_user.id)
    player = game.get_player(message.from_user.id)
    can_start = opportunities.runs_left(message.from_user.id) > 0 and player["actions_left"] > 0
    await message.answer(
        with_notice(opportunity_board_screen(game, opportunities, message.from_user.id), outcome),
        reply_markup=opportunity_board_menu(items, can_start=can_start),
    )


@router.message(F.text == INBOX)
async def open_inbox(message: Message, session: SessionService) -> None:
    item = session.next_inbox_item(message.from_user.id)
    await message.answer(
        inbox_screen(session, message.from_user.id),
        reply_markup=inbox_menu(item),
    )


@router.message(F.text.startswith("✉️ "))
async def resolve_inbox(message: Message, session: SessionService) -> None:
    item = session.next_inbox_item(message.from_user.id)
    if not item:
        await message.answer("Входящие на сегодня уже разобраны.", reply_markup=inbox_menu(None))
        return
    try:
        choice_index = int(message.text.split(" ", 2)[1]) - 1
        result = session.resolve_inbox(message.from_user.id, item["slot"], choice_index)
    except (ValueError, GameError) as exc:
        result = str(exc)
    next_item = session.next_inbox_item(message.from_user.id)
    await message.answer(
        with_notice(inbox_screen(session, message.from_user.id), result),
        reply_markup=inbox_menu(next_item),
    )


@router.message(F.text == MORE)
async def open_more(message: Message) -> None:
    await message.answer(
        "🧰 <b>ЕЩЁ</b>\n━━━━━━━━━━━━\nРазвитие, отдых, деньги и история персонажа.",
        reply_markup=more_menu(),
    )


@router.message(F.text.in_({LEARN, NETWORK, SHOW, REST}))
async def secondary_action(
    message: Message,
    game: GameService,
    session: SessionService,
    opportunities: OpportunityService,
    project_play: ProjectPlayService,
    admin: AdminService,
) -> None:
    mapping = {LEARN: "learn", NETWORK: "network", SHOW: "show", REST: "rest"}
    try:
        result = game.perform_action(message.from_user.id, mapping[message.text])
    except GameError as exc:
        result = str(exc)
    await message.answer(
        _home_text(
            game,
            session,
            opportunities,
            project_play,
            admin,
            message.from_user.id,
            result,
        ),
        reply_markup=more_menu(),
    )


@router.message(F.text == INVESTMENTS_BUTTON)
async def open_investments(message: Message, game: GameService) -> None:
    await message.answer(
        investments_screen(game, message.from_user.id),
        reply_markup=investments_menu(),
    )


@router.message(F.text.startswith("💳 "))
async def buy_investment(
    message: Message,
    game: GameService,
    session: SessionService,
    opportunities: OpportunityService,
    project_play: ProjectPlayService,
    admin: AdminService,
) -> None:
    title = message.text.removeprefix("💳 ")
    item_id = next((key for key, item in INVESTMENTS.items() if item["title"] == title), None)
    if not item_id:
        await message.answer("Неизвестное вложение.")
        return
    try:
        result = game.buy_investment(message.from_user.id, item_id)
    except GameError as exc:
        result = str(exc)
    await message.answer(
        _home_text(
            game,
            session,
            opportunities,
            project_play,
            admin,
            message.from_user.id,
            result,
        ),
        reply_markup=more_menu(),
    )


@router.message(F.text == PORTFOLIO)
async def open_portfolio(message: Message, opportunities: OpportunityService) -> None:
    await message.answer(portfolio_screen(opportunities, message.from_user.id), reply_markup=more_menu())


@router.message(F.text == HISTORY)
async def open_history(message: Message, game: GameService) -> None:
    await message.answer(history_screen(game, message.from_user.id), reply_markup=more_menu())


@router.message(F.text == CAREER)
async def open_career(message: Message, game: GameService) -> None:
    player = game.get_player(message.from_user.id)
    await message.answer(
        career_screen(game, message.from_user.id),
        reply_markup=career_menu(player),
    )


@router.message(F.text.in_({"🚀 Принять повышение", "🧠 Экспертный трек", "👥 Управленческий трек"}))
async def claim_promotion(
    message: Message,
    game: GameService,
    session: SessionService,
    opportunities: OpportunityService,
    project_play: ProjectPlayService,
    admin: AdminService,
) -> None:
    track = None
    if message.text == "🧠 Экспертный трек":
        track = "expert"
    elif message.text == "👥 Управленческий трек":
        track = "manager"
    try:
        result = game.claim_promotion(message.from_user.id, track)
    except GameError as exc:
        result = str(exc)
    await _send_home(message, game, session, opportunities, project_play, admin, result)


@router.message(F.text == ADMIN)
async def open_admin(message: Message, game: GameService, admin: AdminService) -> None:
    if not admin.is_admin(message.from_user.id):
        await message.answer("Раздел доступен только администратору.")
        return
    player = game.get_player(message.from_user.id)
    fast = admin.is_fast_mode(message.from_user.id)
    await message.answer(
        "🧪 <b>АДМИН</b>\n━━━━━━━━━━━━\n"
        f"Быстрый режим: <b>{'включён' if fast else 'выключен'}</b>\n"
        f"Действия: {player['actions_left']}/5",
        reply_markup=admin_menu(fast_mode=fast, can_advance=player["actions_left"] == 0),
    )


@router.message(F.text.startswith(FAST))
async def toggle_fast(message: Message, game: GameService, admin: AdminService) -> None:
    try:
        enabled = admin.toggle_fast_mode(message.from_user.id)
    except AdminError as exc:
        await message.answer(str(exc))
        return
    player = game.get_player(message.from_user.id)
    await message.answer(
        f"🧪 Быстрый режим {'включён' if enabled else 'выключен'}.",
        reply_markup=admin_menu(
            fast_mode=enabled,
            can_advance=player["actions_left"] == 0,
        ),
    )


@router.message(F.text == NEXT_DAY)
async def next_day(
    message: Message,
    game: GameService,
    session: SessionService,
    opportunities: OpportunityService,
    project_play: ProjectPlayService,
    admin: AdminService,
) -> None:
    try:
        result = admin.advance_day(message.from_user.id)
    except AdminError as exc:
        result = str(exc)
    await _send_home(message, game, session, opportunities, project_play, admin, result)


@router.message(Command("fast"))
async def fast_command(message: Message, game: GameService, admin: AdminService) -> None:
    if not admin.is_admin(message.from_user.id):
        await message.answer("Команда доступна только администратору.")
        return
    game.ensure_player(message.from_user.id, message.from_user.username)
    enabled = admin.toggle_fast_mode(message.from_user.id)
    player = game.get_player(message.from_user.id)
    await message.answer(
        f"🧪 Быстрый режим {'включён' if enabled else 'выключен'}.",
        reply_markup=admin_menu(
            fast_mode=enabled,
            can_advance=player["actions_left"] == 0,
        ),
    )


@router.message(Command("reset"))
@router.message(F.text == RESET)
async def reset_command(message: Message, admin: AdminService) -> None:
    if not admin.is_admin(message.from_user.id):
        await message.answer("Команда доступна только администратору.")
        return
    await message.answer(
        "🗑 <b>СБРОС ПРОГРЕССА</b>\n━━━━━━━━━━━━\n"
        "Удалить персонажа, проекты, портфолио и историю? Быстрый режим сохранится.",
        reply_markup=reset_confirm_menu(),
    )


@router.message(F.text == CONFIRM_RESET)
async def confirm_reset(
    message: Message,
    game: GameService,
    session: SessionService,
    opportunities: OpportunityService,
    project_play: ProjectPlayService,
    admin: AdminService,
) -> None:
    try:
        admin.reset_player(message.from_user.id)
    except AdminError as exc:
        await message.answer(str(exc))
        return
    game.ensure_player(message.from_user.id, message.from_user.username)
    await _send_home(
        message,
        game,
        session,
        opportunities,
        project_play,
        admin,
        "Прогресс полностью сброшен.",
    )


@router.message(F.text == CANCEL)
async def cancel_reset(
    message: Message,
    game: GameService,
    session: SessionService,
    opportunities: OpportunityService,
    project_play: ProjectPlayService,
    admin: AdminService,
) -> None:
    await _send_home(message, game, session, opportunities, project_play, admin, "Сброс отменён.")


@router.message()
async def unknown(message: Message, admin: AdminService) -> None:
    await message.answer(
        "Используй кнопки меню ниже — весь игровой интерфейс теперь находится там.",
        reply_markup=_home_markup(admin, message.from_user.id),
    )
