from __future__ import annotations

import re
from html import escape
from pathlib import Path

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message


_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")
_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
_HOME_IMAGE = _ASSET_DIR / "nightshift_menu.jpg"
_PRODUCT_IMAGE = _ASSET_DIR / "nightshift_product.jpg"


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


def claim_tip(db, player_id: int, code: str) -> bool:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO player_tips(player_id, code) VALUES (?, ?)",
            (player_id, code),
        )
    return cur.rowcount > 0


def _callback_data(markup: InlineKeyboardMarkup | None) -> set[str]:
    if not markup:
        return set()
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    }


def _screen_image(text: str, markup: InlineKeyboardMarkup | None) -> Path | None:
    callbacks = _callback_data(markup)
    if {"menu:inbox", "menu:product", "menu:storefront", "menu:team"}.issubset(callbacks):
        return _HOME_IMAGE if _HOME_IMAGE.is_file() else None
    if "<b>📦 Товар</b>" in text and "menu:product" in callbacks:
        return _PRODUCT_IMAGE if _PRODUCT_IMAGE.is_file() else None
    return None


async def _answer_photo(
    target: Message,
    image: Path,
    text: str,
    markup: InlineKeyboardMarkup | None,
) -> None:
    await target.answer_photo(
        photo=FSInputFile(image),
        caption=text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def present(
    target: Message,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    *,
    edit: bool = True,
) -> None:
    text = normalize_text(text)
    image = _screen_image(text, markup)

    if image is not None:
        if not edit:
            await _answer_photo(target, image, text, markup)
            return
        if target.photo:
            try:
                await target.edit_media(
                    InputMediaPhoto(
                        media=FSInputFile(image),
                        caption=text,
                        parse_mode=ParseMode.HTML,
                    ),
                    reply_markup=markup,
                )
            except TelegramBadRequest as exc:
                if "message is not modified" not in str(exc).lower():
                    raise
            return
        try:
            await target.delete()
        except TelegramBadRequest:
            pass
        await _answer_photo(target, image, text, markup)
        return

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
