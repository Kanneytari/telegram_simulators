from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from .db import Database
from .game import GameService, ROLE_NAMES
from .keyboards import (
    candidate_actions,
    candidate_list,
    main_menu,
    recruitment_confirm,
    recruitment_menu,
    result_actions,
)
from .recruitment import RecruitmentService
from .simulation import SimulationEngine, iso, utcnow


def build_recruitment_router(
    db: Database,
    game: GameService,
    simulation: SimulationEngine,
    recruitment: RecruitmentService,
    admin_ids: frozenset[int],
) -> Router:
    router = Router(name="recruitment")

    async def present(
        target: Message,
        text: str,
        markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    @router.callback_query(F.data == "candidates:list")
    async def candidates(callback: CallbackQuery) -> None:
        await callback.answer()
        rows = recruitment.candidates(callback.from_user.id)
        if rows:
            text = (
                f"<b>👤 Кандидаты</b>\n\nАнкет: <b>{len(rows)}</b>\n"
                "Источник отклика виден в анкете. Скрытые качества проявятся только в работе."
            )
        else:
            text = "<b>👤 Кандидаты</b>\n\nСвежих откликов нет. Запусти набор или дождись активной кампании."
        await present(callback.message, text, candidate_list(rows))

    @router.callback_query(
        F.data.startswith("candidate:")
        & ~F.data.startswith("candidate:hire:")
        & ~F.data.startswith("candidate:reject:")
    )
    async def candidate(callback: CallbackQuery) -> None:
        await callback.answer()
        candidate_id = int(callback.data.split(":")[1])
        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM candidates WHERE id=? AND player_id=? AND status='open'",
                (candidate_id, callback.from_user.id),
            ).fetchone()
        if not row or not str(row["summary"]).startswith("Источник:"):
            await present(
                callback.message,
                "Кандидат больше недоступен.",
                result_actions("candidates:list", "← Кандидаты"),
            )
            return
        text = (
            f"<b>👤 {row['alias']}</b>\n\n"
            f"Роль: {ROLE_NAMES.get(row['role'], row['role'])}\n"
            f"Ставка: <b>{row['desired_pay']:,} ₽</b> / заказ\n"
            f"Обеспечение: {row['deposit']:,} ₽\n"
            f"Автомобиль: {'есть' if row['has_car'] else 'нет'}\n\n"
            f"{row['summary']}"
        )
        await present(callback.message, text, candidate_actions(candidate_id))

    @router.callback_query(F.data.startswith("candidate:hire:"))
    async def candidate_hire(callback: CallbackQuery) -> None:
        await callback.answer()
        candidate_id = int(callback.data.split(":")[2])
        result = game.hire_candidate(callback.from_user.id, candidate_id)
        await present(
            callback.message,
            f"<b>👥 Команда</b>\n\n{result}",
            result_actions("menu:team", "← Команда"),
        )

    @router.callback_query(F.data.startswith("candidate:reject:"))
    async def candidate_reject(callback: CallbackQuery) -> None:
        await callback.answer()
        candidate_id = int(callback.data.split(":")[2])
        game.reject_candidate(callback.from_user.id, candidate_id)
        await present(
            callback.message,
            "<b>Кандидату отказано.</b>",
            result_actions("candidates:list", "← Кандидаты"),
        )

    @router.callback_query(F.data == "recruit:menu")
    async def recruit_menu(callback: CallbackQuery) -> None:
        await callback.answer()
        status = recruitment.campaign_status_text(callback.from_user.id)
        text = (
            "<b>🔎 Набор сотрудников</b>\n\n"
            "Выбери канал привлечения. Они отличаются ценой, скоростью, числом откликов и средним качеством потока.\n\n"
            f"{status}"
        )
        await present(callback.message, text, recruitment_menu())

    @router.callback_query(F.data.startswith("recruit:confirm:"))
    async def recruit_confirm(callback: CallbackQuery) -> None:
        await callback.answer()
        code = callback.data.split(":")[2]
        channel = recruitment.get_channel(code)
        if not channel:
            await present(
                callback.message,
                "Канал недоступен.",
                result_actions("recruit:menu", "← Набор"),
            )
            return
        text = (
            f"<b>{channel.icon} {channel.title}</b>\n\n"
            f"Стоимость: <b>{channel.cost:,} ₽</b>\n"
            f"Отклики: обычно {channel.min_candidates}-{channel.max_candidates}\n"
            f"Срок: {channel.min_hours:g}-{channel.max_hours:g} игровых часов\n\n"
            f"{channel.description}\n\n"
            "Запустить кампанию?"
        )
        await present(callback.message, text, recruitment_confirm(code, channel.cost))

    @router.callback_query(F.data.startswith("recruit:run:"))
    async def recruit_run(callback: CallbackQuery) -> None:
        await callback.answer()
        code = callback.data.split(":")[2]
        result = recruitment.start_campaign(callback.from_user.id, code)
        await present(
            callback.message,
            f"<b>🔎 Набор</b>\n\n{result}",
            result_actions("recruit:menu", "← Набор"),
        )

    @router.message(Command("tick"))
    async def debug_tick(message: Message) -> None:
        if message.from_user.id not in admin_ids:
            return
        simulation.ensure_player(message.from_user.id, message.from_user.username)
        with db.connect() as conn:
            conn.execute(
                "UPDATE shops SET last_simulated_at=? WHERE player_id=?",
                (
                    iso(utcnow() - timedelta(hours=6 / max(simulation.speed, 0.1))),
                    message.from_user.id,
                ),
            )
        result = simulation.advance(message.from_user.id)
        candidates_created = recruitment.fast_forward(message.from_user.id, 6)
        with db.connect() as conn:
            inbox = conn.execute(
                """SELECT COUNT(*) AS opened,
                          SUM(CASE WHEN priority IN ('important','urgent') THEN 1 ELSE 0 END) AS urgent
                   FROM inbox WHERE player_id=? AND status='open'""",
                (message.from_user.id,),
            ).fetchone()
        await message.answer(
            "<b>⏩ Тестовый тик</b>\n\n"
            f"Заказов: {result.orders_created}\n"
            f"Диспутов: {result.disputes_created}\n"
            f"Сообщений: {result.messages_created}\n"
            f"Новых кандидатов: {candidates_created}",
            reply_markup=main_menu(int(inbox["opened"] or 0), int(inbox["urgent"] or 0)),
        )

    return router
