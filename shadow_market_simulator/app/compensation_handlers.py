from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


ROLE_TITLES = {
    "courier": "👤 Розничные сотрудники",
    "warehouse": "🚚 Оптовые сотрудники",
}


def _pct(bps: int) -> str:
    return f"{int(bps) / 100:.1f}%"


def build_compensation_router(game) -> Router:
    router = Router(name="team-compensation")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def root_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=ROLE_TITLES["courier"], callback_data="team:terms:courier")],
            [InlineKeyboardButton(text=ROLE_TITLES["warehouse"], callback_data="team:terms:warehouse")],
            [InlineKeyboardButton(text="← Команда", callback_data="menu:team")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ])

    def root_text(player_id: int) -> str:
        retail = game.compensation_policy(player_id, "courier")
        wholesale = game.compensation_policy(player_id, "warehouse")
        return (
            "<b>💰 Условия работы</b>\n\n"
            "Условия задаются сразу для <b>всех сотрудников одного типа</b>. "
            "Индивидуальных ставок нет.\n\n"
            "<b>Розница</b>\n"
            f"{retail['fixed_fee']:,} ₽ за успешный заказ + "
            f"{_pct(retail['base_rate_bps'])} с продажи\n"
            f"В депозит: {retail['deposit_contribution_pct']}%\n\n"
            "<b>Опт</b>\n"
            f"{_pct(wholesale['base_rate_bps'])} от стоимости успешной передачи\n"
            f"+{_pct(wholesale['risk_rate_bps'])} от непокрытой депозитом части\n"
            f"В депозит: {wholesale['deposit_contribution_pct']}%\n\n"
            "Изменение условий влияет на отношение всей соответствующей группы сотрудников."
        )

    def role_keyboard(role: str, policy: dict[str, int]) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        if role == "courier":
            rows.append([
                InlineKeyboardButton(text="−50", callback_data="team:termsadj:courier:fixed_fee:-50"),
                InlineKeyboardButton(text=f"Фикс {policy['fixed_fee']:,} ₽", callback_data="workflow:noop"),
                InlineKeyboardButton(text="+50", callback_data="team:termsadj:courier:fixed_fee:50"),
            ])
            rows.append([
                InlineKeyboardButton(text="−0.5%", callback_data="team:termsadj:courier:base_rate_bps:-50"),
                InlineKeyboardButton(text=f"Продажа {_pct(policy['base_rate_bps'])}", callback_data="workflow:noop"),
                InlineKeyboardButton(text="+0.5%", callback_data="team:termsadj:courier:base_rate_bps:50"),
            ])
        else:
            rows.append([
                InlineKeyboardButton(text="−0.5%", callback_data="team:termsadj:warehouse:base_rate_bps:-50"),
                InlineKeyboardButton(text=f"Передача {_pct(policy['base_rate_bps'])}", callback_data="workflow:noop"),
                InlineKeyboardButton(text="+0.5%", callback_data="team:termsadj:warehouse:base_rate_bps:50"),
            ])
            rows.append([
                InlineKeyboardButton(text="−0.5%", callback_data="team:termsadj:warehouse:risk_rate_bps:-50"),
                InlineKeyboardButton(text=f"Риск +{_pct(policy['risk_rate_bps'])}", callback_data="workflow:noop"),
                InlineKeyboardButton(text="+0.5%", callback_data="team:termsadj:warehouse:risk_rate_bps:50"),
            ])
        rows.append([
            InlineKeyboardButton(text="−5%", callback_data=f"team:termsadj:{role}:deposit_contribution_pct:-5"),
            InlineKeyboardButton(
                text=f"В депозит {policy['deposit_contribution_pct']}%",
                callback_data="workflow:noop",
            ),
            InlineKeyboardButton(text="+5%", callback_data=f"team:termsadj:{role}:deposit_contribution_pct:5"),
        ])
        rows.append([InlineKeyboardButton(text="← Условия работы", callback_data="team:terms")])
        rows.append([InlineKeyboardButton(text="← Команда", callback_data="menu:team")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def role_text(role: str, policy: dict[str, int], reaction: str | None = None) -> str:
        if role == "courier":
            body = (
                f"<b>{ROLE_TITLES[role]}</b>\n\n"
                "<b>Формула</b>\n"
                f"{policy['fixed_fee']:,} ₽ за каждый успешно выполненный заказ\n"
                f"+ {_pct(policy['base_rate_bps'])} от суммы продажи\n\n"
                f"В депозит из заработка: <b>{policy['deposit_contribution_pct']}%</b>\n\n"
                "Мелкие позиции дают больше отдельных заказов и поэтому сохраняют смысл. "
                "Крупные позиции дают сотруднику больше денег за одну продажу за счёт процентной части."
            )
        else:
            body = (
                f"<b>{ROLE_TITLES[role]}</b>\n\n"
                "<b>Формула</b>\n"
                f"{_pct(policy['base_rate_bps'])} от себестоимости успешно переданного товара\n"
                f"+ {_pct(policy['risk_rate_bps'])} от части передачи, которая не была покрыта депозитом\n\n"
                f"В депозит из заработка: <b>{policy['deposit_contribution_pct']}%</b>\n\n"
                "За получение партии у поставщика оплата не начисляется. "
                "Оптовик зарабатывает только после фактической передачи товара рознице."
            )
        if reaction:
            body += f"\n\n<b>Изменение применено ко всей группе.</b>\n{reaction}"
        return body

    @router.callback_query(F.data == "team:terms")
    async def terms_root(callback: CallbackQuery) -> None:
        await callback.answer()
        await present(callback.message, root_text(callback.from_user.id), root_keyboard())

    @router.callback_query(F.data.regexp(r"^team:terms:(courier|warehouse)$"))
    async def terms_role(callback: CallbackQuery) -> None:
        await callback.answer()
        role = (callback.data or "").split(":")[2]
        policy = game.compensation_policy(callback.from_user.id, role)
        await present(callback.message, role_text(role, policy), role_keyboard(role, policy))

    @router.callback_query(F.data.startswith("team:termsadj:"))
    async def terms_adjust(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            _, _, role, field, delta = (callback.data or "").split(":")
            result = game.adjust_compensation_policy(
                callback.from_user.id, role, field, int(delta)
            )
        except (ValueError, IndexError):
            return
        policy = result["policy"]
        await present(
            callback.message,
            role_text(role, policy, result.get("reaction")),
            role_keyboard(role, policy),
        )

    return router
