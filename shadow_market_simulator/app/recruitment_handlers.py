from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .db import Database
from .game import GameService, ROLE_NAMES
from .keyboards import candidate_actions, candidate_list, result_actions
from .recruitment import CHANNELS, DURATION_OPTIONS, VOLUME_OPTIONS, RecruitmentService


ROLE_LABELS = {"courier": "Розница", "warehouse": "Опт"}


def build_recruitment_router(
    db: Database,
    game: GameService,
    simulation,
    recruitment: RecruitmentService,
    admin_ids: frozenset[int],
) -> Router:
    router = Router(name="recruitment")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def channels_keyboard() -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton(text=f"{channel.icon} {channel.title}", callback_data=f"recruit:channel:{code}")]
            for code, channel in CHANNELS.items()
        ]
        rows.append([
            InlineKeyboardButton(text="← Команда", callback_data="menu:team"),
            InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def draft_keyboard(draft, quote) -> InlineKeyboardMarkup:
        volume = int(draft["traffic_multiplier"])
        duration = int(draft["duration_hours"])
        role = draft["role"]
        pay_step = 250 if role == "warehouse" else 100
        deposit_step = 50_000 if role == "warehouse" else 10_000
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=("✓ " if role == "courier" else "") + "Розница", callback_data="recruit:set:role:courier"),
                InlineKeyboardButton(text=("✓ " if role == "warehouse" else "") + "Опт", callback_data="recruit:set:role:warehouse"),
            ],
            [InlineKeyboardButton(text="Охват", callback_data="recruit:noop")]
            + [InlineKeyboardButton(
                text=("✓ " if value == volume else "") + f"x{value}",
                callback_data=f"recruit:set:traffic_multiplier:{value}",
            ) for value in VOLUME_OPTIONS],
            [InlineKeyboardButton(text="Срок", callback_data="recruit:noop")]
            + [InlineKeyboardButton(
                text=("✓ " if value == duration else "") + f"{value} ч",
                callback_data=f"recruit:set:duration_hours:{value}",
            ) for value in DURATION_OPTIONS],
            [
                InlineKeyboardButton(text=f"−{pay_step}", callback_data=f"recruit:adj:pay_per_job:-{pay_step}"),
                InlineKeyboardButton(text=f"Ставка {draft['pay_per_job']:,}", callback_data="recruit:noop"),
                InlineKeyboardButton(text=f"+{pay_step}", callback_data=f"recruit:adj:pay_per_job:{pay_step}"),
            ],
            [
                InlineKeyboardButton(text=f"−{deposit_step//1000}k", callback_data=f"recruit:adj:min_deposit:-{deposit_step}"),
                InlineKeyboardButton(text=f"Депозит {int(draft['min_deposit'])//1000}k", callback_data="recruit:noop"),
                InlineKeyboardButton(text=f"+{deposit_step//1000}k", callback_data=f"recruit:adj:min_deposit:{deposit_step}"),
            ],
            [
                InlineKeyboardButton(text="−5%", callback_data="recruit:adj:deposit_contribution_pct:-5"),
                InlineKeyboardButton(text=f"В депозит {draft['deposit_contribution_pct']}%", callback_data="recruit:noop"),
                InlineKeyboardButton(text="+5%", callback_data="recruit:adj:deposit_contribution_pct:5"),
            ],
            [
                InlineKeyboardButton(
                    text=("✅" if draft["car_required"] else "▫️") + " Нужен автомобиль",
                    callback_data="recruit:toggle:car_required",
                ),
                InlineKeyboardButton(
                    text=("✅" if draft["experience_required"] else "▫️") + " Нужен опыт",
                    callback_data="recruit:toggle:experience_required",
                ),
            ],
            [InlineKeyboardButton(text=f"✅ Запустить · {int(quote['cost']):,} ₽", callback_data="recruit:run")],
            [
                InlineKeyboardButton(text="← Каналы", callback_data="recruit:menu"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ])

    def draft_screen(player_id: int) -> tuple[str, InlineKeyboardMarkup]:
        draft = recruitment.ensure_draft(player_id)
        channel = recruitment.get_channel(draft["channel"])
        quote = recruitment.quote(player_id, draft)
        role_title = "Оптовый сотрудник" if draft["role"] == "warehouse" else "Розничный сотрудник"
        car = "обязательно" if draft["car_required"] else "не требуется"
        experience = "обязателен" if draft["experience_required"] else "не обязателен"
        text = (
            f"<b>{channel.icon} {channel.title}</b>\n\n"
            f"{channel.description}\n\n"
            f"<b>Вакансия</b>\n"
            f"Роль: <b>{role_title}</b>\n"
            f"Ставка: <b>{draft['pay_per_job']:,} ₽</b> / операцию\n"
            f"Минимальный депозит: {draft['min_deposit']:,} ₽\n"
            f"В депозит из заработка: {draft['deposit_contribution_pct']}%\n"
            f"Автомобиль: {car}\n"
            f"Опыт: {experience}\n\n"
            f"<b>Размещение</b>\n"
            f"Охват: x{draft['traffic_multiplier']}\n"
            f"Срок: {draft['duration_hours']} игровых ч\n"
            f"Стоимость: <b>{int(quote['cost']):,} ₽</b>\n"
            f"Скидка за объём/срок: {float(quote['discount_pct']):.0f}%\n\n"
            f"📨 Ожидаемые отклики: <b>{quote['expected_min']}-{quote['expected_max']}</b>"
        )
        return text, draft_keyboard(draft, quote)

    @router.callback_query(F.data == "recruit:noop")
    async def noop(callback: CallbackQuery) -> None:
        await callback.answer()

    @router.callback_query(F.data == "recruit:menu")
    async def recruit_menu(callback: CallbackQuery) -> None:
        await callback.answer()
        status = recruitment.campaign_status_text(callback.from_user.id)
        await present(
            callback.message,
            "<b>🔎 Набор сотрудников</b>\n\nВыбери канал. Затем укажи роль и условия работы.\n\n" + status,
            channels_keyboard(),
        )

    @router.callback_query(F.data.startswith("recruit:channel:"))
    async def recruit_channel(callback: CallbackQuery) -> None:
        await callback.answer()
        code = callback.data.split(":")[2]
        if code not in CHANNELS:
            return
        recruitment.ensure_draft(callback.from_user.id, code)
        text, keyboard = draft_screen(callback.from_user.id)
        await present(callback.message, text, keyboard)

    @router.callback_query(F.data.startswith("recruit:set:"))
    async def recruit_set(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, field, value = callback.data.split(":")
        recruitment.update_draft(callback.from_user.id, field, value if field == "role" else int(value))
        text, keyboard = draft_screen(callback.from_user.id)
        await present(callback.message, text, keyboard)

    @router.callback_query(F.data.startswith("recruit:adj:"))
    async def recruit_adjust(callback: CallbackQuery) -> None:
        await callback.answer()
        _, _, field, delta = callback.data.split(":")
        recruitment.adjust_draft(callback.from_user.id, field, int(delta))
        text, keyboard = draft_screen(callback.from_user.id)
        await present(callback.message, text, keyboard)

    @router.callback_query(F.data.startswith("recruit:toggle:"))
    async def recruit_toggle(callback: CallbackQuery) -> None:
        await callback.answer()
        field = callback.data.split(":")[2]
        draft = recruitment.ensure_draft(callback.from_user.id)
        recruitment.update_draft(callback.from_user.id, field, 0 if draft[field] else 1)
        text, keyboard = draft_screen(callback.from_user.id)
        await present(callback.message, text, keyboard)

    @router.callback_query(F.data == "recruit:run")
    async def recruit_run(callback: CallbackQuery) -> None:
        await callback.answer()
        result = recruitment.start_campaign(callback.from_user.id)
        await present(callback.message, f"<b>🔎 Набор</b>\n\n{result}", result_actions("recruit:menu", "← Набор"))

    @router.callback_query(F.data.startswith("recruit:confirm:"))
    @router.callback_query(F.data.startswith("recruit:run:"))
    async def legacy_channel(callback: CallbackQuery) -> None:
        await callback.answer()
        code = callback.data.split(":")[2]
        if code in CHANNELS:
            recruitment.ensure_draft(callback.from_user.id, code)
        text, keyboard = draft_screen(callback.from_user.id)
        await present(callback.message, text, keyboard)

    @router.callback_query(F.data == "candidates:list")
    async def candidates(callback: CallbackQuery) -> None:
        await callback.answer()
        rows = recruitment.candidates(callback.from_user.id)
        text = (
            f"<b>👤 Кандидаты</b>\n\nСвежих анкет: <b>{len(rows)}</b>\n\n"
            "Условия вакансии уже учтены в отклике. Скрытые качества проявятся только в работе."
            if rows else
            "<b>👤 Кандидаты</b>\n\nСвежих откликов нет. Запусти набор или дождись активного размещения."
        )
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
        if not row or row["campaign_id"] is None:
            await present(callback.message, "Кандидат больше недоступен.", result_actions("candidates:list", "← Кандидаты"))
            return
        offered = int(row["offered_pay"] or row["desired_pay"])
        text = (
            f"<b>👤 {row['alias']}</b>\n\n"
            f"<b>Анкета</b>\n"
            f"Роль: {ROLE_NAMES.get(row['role'], row['role'])}\n"
            f"Ожидания кандидата: ~{row['desired_pay']:,} ₽ / операцию\n"
            f"Автомобиль: {'есть' if row['has_car'] else 'нет'}\n"
            f"Готовый депозит: {row['deposit']:,} ₽\n\n"
            f"<b>Предложенные условия</b>\n"
            f"Ставка: <b>{offered:,} ₽</b> / операцию\n"
            f"В депозит: {row['deposit_contribution_pct']}% заработка\n"
            f"Минимальный депозит: {row['min_deposit']:,} ₽\n\n"
            f"{row['summary']}"
        )
        await present(callback.message, text, candidate_actions(candidate_id))

    @router.callback_query(F.data.startswith("candidate:hire:"))
    async def candidate_hire(callback: CallbackQuery) -> None:
        await callback.answer()
        result = game.hire_candidate(callback.from_user.id, int(callback.data.split(":")[2]))
        await present(callback.message, f"<b>👥 Команда</b>\n\n{result}", result_actions("menu:team", "← Команда"))

    @router.callback_query(F.data.startswith("candidate:reject:"))
    async def candidate_reject(callback: CallbackQuery) -> None:
        await callback.answer()
        game.reject_candidate(callback.from_user.id, int(callback.data.split(":")[2]))
        await present(callback.message, "<b>Кандидату отказано.</b>", result_actions("candidates:list", "← Кандидаты"))

    return router
