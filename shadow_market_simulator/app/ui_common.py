from __future__ import annotations

import re
from html import escape

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message


_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")
_TUTORIAL_BUTTON_MENTION = re.compile(
    r"(?i)(\bкнопк\w*\s+)(?:«([^»]+)»|\[([^\]]+)\]|([^\n.!?]+))"
)
_TUTORIAL_ACTION_MENTION = re.compile(
    r"(?i)(\bнажм(?:и|ите|ать)\s+)(⏩ Пропустить ожидание)"
)


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
        return "" if current == 0 else " +100%"
    change = (current - previous) / abs(previous)
    if abs(change) < neutral:
        return ""
    sign = "+" if change > 0 else "-"
    return f" {sign}{abs(change) * 100:.0f}%"


def clean(value: object) -> str:
    return escape(str(value or ""))


def _normalize_tutorial_button_mentions(text: str) -> str:
    text = (
        text.replace("🚚 Склад", "📦 Склад")
        .replace("—", "-")
        .replace("«", "[")
        .replace("»", "]")
        .replace(" → ", ", затем ")
        .replace("← ", "")
    )
    text = _TUTORIAL_ACTION_MENTION.sub(r"\1[\2]", text)

    def replace(match: re.Match[str]) -> str:
        label = next(
            group.strip()
            for group in match.groups()[1:]
            if group is not None
        )
        return f"{match.group(1)}[{label}]"

    return _TUTORIAL_BUTTON_MENTION.sub(replace, text)


def _format_tutorial_blocks(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.strip())


def tutorial_hint(text: str) -> str:
    normalized = _normalize_tutorial_button_mentions(text)
    return f"<blockquote>{clean(_format_tutorial_blocks(normalized))}</blockquote>"


def normalize_text(text: str) -> str:
    text = (
        text.replace("—", "-")
        .replace("«", '"')
        .replace("»", '"')
        .replace(" → ", ", затем ")
        .replace("→ ", "")
        .replace("← ", "")
    )
    return _THOUSANDS_COMMA.sub(" ", text)


def claim_tip(db, player_id: int, code: str) -> bool:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO player_tips(player_id, code) VALUES (?, ?)",
            (player_id, code),
        )
    return cur.rowcount > 0


def _normalize_button_text(text: str) -> str:
    return (
        text.replace("—", "-")
        .replace("«", '"')
        .replace("»", '"')
        .replace("← ", "")
        .replace(" →", "")
    )


def _normalize_menu_buttons(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    if not markup:
        return None
    changed = False
    rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        normalized_row: list[InlineKeyboardButton] = []
        for button in row:
            original_text = button.text or ""
            replacement = _normalize_button_text(original_text)
            if button.callback_data == "menu:home" and replacement == "Меню":
                replacement = "🏠 Меню"
            elif button.callback_data == "team:recruit" and replacement == "Нанять":
                replacement = "🔎 Нанять"
            elif button.callback_data == "team:terms" and replacement == "Оплата":
                replacement = "⚙️ Оплата"
            if replacement != original_text:
                button = button.model_copy(update={"text": replacement})
                changed = True
            normalized_row.append(button)
        rows.append(normalized_row)
    return InlineKeyboardMarkup(inline_keyboard=rows) if changed else markup


async def present(
    target: Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    edit: bool = True,
) -> None:
    text = normalize_text(text)
    markup = _normalize_menu_buttons(markup)

    if target.photo and edit:
        try:
            await target.delete()
        except TelegramBadRequest:
            pass
        await target.answer(text, reply_markup=markup)
        return

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
    parent_text: str = "Назад",
    *,
    menu: bool = True,
) -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    if parent_callback:
        row.append(InlineKeyboardButton(text=parent_text, callback_data=parent_callback))
    if menu:
        row.append(InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home"))
    return InlineKeyboardMarkup(inline_keyboard=[row] if row else [])


def nav_row(
    parent_callback: str | None = None,
    parent_text: str = "Назад",
    *,
    menu: bool = True,
) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if parent_callback:
        row.append(InlineKeyboardButton(text=parent_text, callback_data=parent_callback))
    if menu:
        row.append(InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home"))
    return row


def notice(text: str | None, body: str) -> str:
    return f"{text}\n\n{body}" if text else body
