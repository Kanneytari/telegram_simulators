from __future__ import annotations

import math

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


def build_deposit_share_router(game) -> Router:
    router = Router(name="deposit-share-negotiation")

    async def present(target: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            await target.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def employee_keyboard(employee_id: int, role: str) -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton(text="⭐ Отзывы о работе", callback_data=f"employee:reviews:{employee_id}")],
            [InlineKeyboardButton(text="💰 Доля в депозит", callback_data=f"employee:depositshare:{employee_id}:current")],
        ]
        if role == "warehouse":
            rows.append([InlineKeyboardButton(text="📦 Партии и распределение", callback_data=f"workflow:batches:{employee_id}")])
        else:
            rows.append([InlineKeyboardButton(text="⚙️ Фасовки", callback_data=f"workflow:packemployee:{employee_id}")])
        rows.extend([
            [InlineKeyboardButton(text="🔁 Сменить роль", callback_data=f"workflow:role:{employee_id}")],
            [InlineKeyboardButton(text="Уволить сотрудника", callback_data=f"employee:fire:{employee_id}")],
            [
                InlineKeyboardButton(text="← Команда", callback_data="menu:team"),
                InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home"),
            ],
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @router.callback_query(F.data.regexp(r"^employee:\d+$"))
    async def employee_profile(callback: CallbackQuery) -> None:
        await callback.answer()
        employee_id = int((callback.data or "").split(":")[1])
        text = game.employee_details(callback.from_user.id, employee_id)
        with game.db.connect() as conn:
            employee = conn.execute(
                "SELECT role FROM employees WHERE id=? AND player_id=? AND active=1",
                (employee_id, callback.from_user.id),
            ).fetchone()
        if not text or not employee:
            await present(
                callback.message,
                "Сотрудник не найден.",
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="← Команда", callback_data="menu:team")],
                    [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
                ]),
            )
            return
        await present(callback.message, text, employee_keyboard(employee_id, employee["role"]))

    @staticmethod
    def cooldown_text(hours: float) -> str:
        minutes = max(1, int(math.ceil(hours * 60)))
        if minutes < 60:
            return f"~{minutes} игровых мин."
        whole, rest = divmod(minutes, 60)
        if rest == 0:
            return f"~{whole} игровых ч"
        return f"~{whole} ч {rest} игровых мин."

    def negotiation_keyboard(context: dict) -> InlineKeyboardMarkup:
        employee_id = int(context["id"])
        target = int(context["target_pct"])
        rows = [
            [
                InlineKeyboardButton(
                    text="−5 п.п.",
                    callback_data=f"employee:depositshare:{employee_id}:{max(0, target - 5)}",
                ),
                InlineKeyboardButton(
                    text="+5 п.п.",
                    callback_data=f"employee:depositshare:{employee_id}:{min(50, target + 5)}",
                ),
            ],
            [
                InlineKeyboardButton(text="0%", callback_data=f"employee:depositshare:{employee_id}:0"),
                InlineKeyboardButton(text="10%", callback_data=f"employee:depositshare:{employee_id}:10"),
                InlineKeyboardButton(text="25%", callback_data=f"employee:depositshare:{employee_id}:25"),
                InlineKeyboardButton(text="50%", callback_data=f"employee:depositshare:{employee_id}:50"),
            ],
        ]
        if context["can_propose"]:
            rows.append([
                InlineKeyboardButton(
                    text=f"🤝 Предложить {target}%",
                    callback_data=f"employee:depositsubmit:{employee_id}:{target}",
                )
            ])
        rows.extend([
            [InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")],
            [InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")],
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def negotiation_text(context: dict) -> str:
        current = int(context["current_pct"])
        target = int(context["target_pct"])
        text = (
            f"<b>💰 Условия выплат · {context['alias']}</b>\n\n"
            "<b>Сейчас</b>\n"
            f"Ставка: {context['pay_per_job']:,} ₽ / операцию\n"
            f"В депозит: <b>{current}%</b> · ~{context['current_deposit']:,} ₽\n"
            f"Деньгами: ~{context['current_cash']:,} ₽\n\n"
            "<b>Предложение</b>\n"
            f"В депозит: <b>{target}%</b> · ~{context['target_deposit']:,} ₽\n"
            f"Деньгами: ~{context['target_cash']:,} ₽\n\n"
        )
        if target == current:
            text += "Выбери другую долю выплат, чтобы сделать предложение."
        elif context["cooldown_game_hours"] > 0.001:
            text += (
                "Вы уже недавно обсуждали условия с этим сотрудником.\n"
                f"Следующее предложение можно сделать примерно через {cooldown_text(context['cooldown_game_hours'])}."
            )
        else:
            direction = "Увеличение удержаний обычно воспринимается хуже." if target > current else "Снижение удержаний обычно воспринимается положительно."
            text += (
                "Сотрудник может согласиться или отказаться. Решение зависит от его отношения к работе и текущего состояния.\n\n"
                f"{direction} Резкие изменения условий повышают риск отказа."
            )
        return text

    @router.callback_query(F.data.startswith("employee:depositshare:"))
    async def deposit_share(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        try:
            employee_id = int(parts[2])
        except (IndexError, ValueError):
            return
        target_raw = parts[3] if len(parts) > 3 else "current"
        base = game.deposit_share_context(callback.from_user.id, employee_id)
        if not base:
            await present(callback.message, "Сотрудник больше недоступен.")
            return
        target = int(base["current_pct"]) if target_raw == "current" else int(target_raw)
        context = game.deposit_share_context(callback.from_user.id, employee_id, target)
        if not context:
            await present(callback.message, "Сотрудник больше недоступен.")
            return
        await present(callback.message, negotiation_text(context), negotiation_keyboard(context))

    @router.callback_query(F.data.startswith("employee:depositsubmit:"))
    async def deposit_submit(callback: CallbackQuery) -> None:
        await callback.answer()
        parts = (callback.data or "").split(":")
        try:
            employee_id = int(parts[2])
            target = int(parts[3])
        except (IndexError, ValueError):
            return
        result = game.propose_deposit_share(callback.from_user.id, employee_id, target)
        rows = [[InlineKeyboardButton(text="← Профиль", callback_data=f"employee:{employee_id}")]]
        if result.get("status") in {"same", "cooldown"}:
            rows.insert(0, [
                InlineKeyboardButton(
                    text="← Условия выплат",
                    callback_data=f"employee:depositshare:{employee_id}:{target}",
                )
            ])
        rows.append([InlineKeyboardButton(text="⌂ Меню", callback_data="menu:home")])
        await present(
            callback.message,
            f"<b>💰 Переговоры об условиях</b>\n\n{result['text']}",
            InlineKeyboardMarkup(inline_keyboard=rows),
        )

    return router
