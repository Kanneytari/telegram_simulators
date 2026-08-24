from __future__ import annotations

import re
from html import escape

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message


_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")


def money(value: int | float) -> str:
    return f"{int(round(value or 0)):,}".replace(",", " ") + " ₽"


def number(value: int | float) -> str:
    return f"{int(round(value or 0)):,}".replace(",", " ")


def pct(value: int | float, digits: int = 0) -> str:
    return f"{float(value):.{digits}f}%".replace(".", ",")


def rating(value: float, count: int = 1) -> str:
    if count <= 0 or value <= 0:
        return "нет оценок"
    return f"{value:.1f}/5".replace(".", ",")


def signed_pct_change(current: float, previous: float, neutral: float = 0.05) -> str:
    if previous == 0:
        return "" if current == 0 else " ↑"
    change = (current - previous) / abs(previous)
    if abs(change) < neutral:
        return " →"
    arrow = "↑" if change > 0 else "↓"
    return f" {arrow}{abs(change) * 100:.0f}%"


def clean(value: object) -> str:
    return escape(str(value or ""))


def normalize_text(text: str) -> str:
    return _THOUSANDS_COMMA.sub(" ", text)


async def present(
    target: Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    edit: bool = True,
) -> None:
    text = normalize_text(text)
    if not edit:
        await target.answer(text, reply_markup=markup)
        return
    try:
        await target.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


def nav(
    parent_callback: str | None = None,
    parent_text: str = "← Назад",
    *,
    menu: bool = True,
) -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    if parent_callback:
        row.append(InlineKeyboardButton(text=parent_text, callback_data=parent_callback))
    if menu:
        row.append(InlineKeyboardButton(text="Меню", callback_data="menu:home"))
    return InlineKeyboardMarkup(inline_keyboard=[row] if row else [])


def nav_row(
    parent_callback: str | None = None,
    parent_text: str = "← Назад",
    *,
    menu: bool = True,
) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if parent_callback:
        row.append(InlineKeyboardButton(text=parent_text, callback_data=parent_callback))
    if menu:
        row.append(InlineKeyboardButton(text="Меню", callback_data="menu:home"))
    return row


def notice(text: str | None, body: str) -> str:
    return f"{text}\n\n{body}" if text else body
