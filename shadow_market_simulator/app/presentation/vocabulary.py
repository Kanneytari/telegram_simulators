from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


@dataclass(frozen=True, slots=True)
class UiItem:
    label: str
    callback_data: str


HOME = UiItem("🏠 Меню", "menu:home")
PRODUCT = UiItem("📦 Товар", "menu:product")
SUPPLIERS = UiItem("🤝 Поставщики", "proc:suppliers")
WAREHOUSE = UiItem("📦 Склад", "team:batches")
STOREFRONT = UiItem("🏷 Витрина", "menu:storefront")
TEAM = UiItem("👥 Команда", "menu:team")
ANALYTICS = UiItem("📊 Аналитика", "menu:analytics")
INBOX = UiItem("📨 Входящие", "menu:inbox")
ADMIN = UiItem("🛠 Админ", "admin:panel")
RECRUIT = UiItem("🔎 Нанять", "team:recruit")
PAYMENT = UiItem("⚙️ Оплата", "team:terms")
PACKAGING = UiItem("⚙️ Фасовки", "sales:packaging")
REFRESH = UiItem("🔄 Обновить", "menu:home")


def label(item: UiItem, suffix: object | None = None) -> str:
    return item.label if suffix is None else f"{item.label} · {suffix}"


def button(
    item: UiItem,
    *,
    callback_data: str | None = None,
    suffix: object | None = None,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=label(item, suffix),
        callback_data=callback_data or item.callback_data,
    )


def nav_row(
    parent: UiItem | str | None = None,
    parent_text: str | None = None,
    *,
    callback_data: str | None = None,
    menu: bool = True,
) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if isinstance(parent, UiItem):
        row.append(button(parent, callback_data=callback_data))
    elif parent:
        if not parent_text:
            raise ValueError("parent_text is required for a raw callback")
        row.append(InlineKeyboardButton(text=parent_text, callback_data=callback_data or parent))
    if menu:
        row.append(button(HOME))
    return row


def nav(
    parent: UiItem | str | None = None,
    parent_text: str | None = None,
    *,
    callback_data: str | None = None,
    menu: bool = True,
) -> InlineKeyboardMarkup:
    row = nav_row(
        parent,
        parent_text,
        callback_data=callback_data,
        menu=menu,
    )
    return InlineKeyboardMarkup(inline_keyboard=[row] if row else [])
