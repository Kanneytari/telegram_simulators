from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


def packaging_keyboard(rule: dict[str, int]) -> InlineKeyboardMarkup:
    rows = []
    for pack_size, key in ((1, "pct_1"), (2, "pct_2"), (5, "pct_5")):
        rows.append([
            InlineKeyboardButton(text="−10", callback_data=f"team:packadj:{pack_size}:-10"),
            InlineKeyboardButton(text=f"×{pack_size} · {int(rule[key])}%", callback_data="workflow:noop"),
            InlineKeyboardButton(text="+10", callback_data=f"team:packadj:{pack_size}:10"),
        ])
    rows.append([InlineKeyboardButton(text="← Команда", callback_data="menu:team")])
    rows.append([InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def packaging_text(rule: dict[str, int]) -> str:
    return (
        "<b>⚙️ Распределение по фасовкам</b>\n\n"
        "Одна настройка применяется ко <b>всем товарам</b> и ко <b>всем розничным сотрудникам</b>.\n"
        "Изменения влияют на следующие подготовленные позиции; уже опубликованные позиции не пересобираются.\n\n"
        f"×1: <b>{int(rule['pct_1'])}%</b>\n"
        f"×2: <b>{int(rule['pct_2'])}%</b>\n"
        f"×5: <b>{int(rule['pct_5'])}%</b>\n\n"
        "Сумма всегда равна 100%. Шаг изменения — 10 п.п."
    )


def build_global_packaging_router(game) -> Router:
    router = Router(name="global-packaging")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    async def show(target: Message, player_id: int) -> None:
        rule = game.global_packaging_rule(player_id)
        await present(target, packaging_text(rule), packaging_keyboard(rule))

    @router.callback_query(F.data == "team:packrules")
    async def packrules(callback: CallbackQuery) -> None:
        await callback.answer()
        await show(callback.message, callback.from_user.id)

    @router.callback_query(F.data.startswith("team:packadj:"))
    async def pack_adjust(callback: CallbackQuery) -> None:
        await callback.answer()
        try:
            _, _, pack_size, delta = (callback.data or "").split(":")
            game.adjust_global_packaging_rule(
                callback.from_user.id,
                int(pack_size),
                int(delta),
            )
        except (ValueError, IndexError):
            return
        await show(callback.message, callback.from_user.id)

    return router
