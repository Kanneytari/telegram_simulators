from __future__ import annotations

import re
from html import escape

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message


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
        return "" if current == 0 else " · рост"
    change = (current - previous) / abs(previous)
    if abs(change) < neutral:
        return ""
    sign = "+" if change > 0 else "-"
    return f" {sign}{abs(change) * 100:.0f}%"


def clean(value: object) -> str:
    return escape(str(value or ""))


def _normalize_tutorial_button_mentions(text: str) -> str:
    text = (
        text.replace("—", "-")
        .replace("«", "[")
        .replace("»", "]")
        .replace(" → ", ", затем ")
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
    safe = clean(_format_tutorial_blocks(normalized))
    safe = safe.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    return f"<blockquote>{safe}</blockquote>"


def normalize_text(text: str) -> str:
    text = (
        text.replace("—", "-")
        .replace("«", '"')
        .replace("»", '"')
        .replace(" → ", ", затем ")
        .replace("→ ", "")
    )
    return _THOUSANDS_COMMA.sub(" ", text)


def claim_tip(db, player_id: int, code: str) -> bool:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO player_tips(player_id, code) VALUES (?, ?)",
            (player_id, code),
        )
    return cur.rowcount > 0


async def present(
    target: Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    edit: bool = True,
) -> None:
    text = normalize_text(text)

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


def notice(text: str | None, body: str) -> str:
    return f"{text}\n\n{body}" if text else body
