from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from .content import INVESTMENTS
from .project_play import TACTICS

HOME = "📊 Статус"
PROJECT = "📌 Проект"
OPPORTUNITIES = "🎯 Возможности"
INBOX = "✉️ Входящие"
CAREER = "📈 Карьера"
MORE = "🧰 Ещё"
BACK = "⬅️ Главное"
PORTFOLIO = "🏅 Портфолио"
HISTORY = "📜 История"
INVESTMENTS_BUTTON = "💸 Вложения"
LEARN = "📚 Учиться"
NETWORK = "🤝 Нетворк"
SHOW = "📣 Показать результат"
REST = "☕ Отдохнуть"
ADMIN = "🧪 Админ"
NEXT_DAY = "⏭ Следующий день"
FAST = "⚡ Быстрый режим"
RESET = "🗑 Сбросить прогресс"
CONFIRM_RESET = "✅ Да, сбросить"
CANCEL = "↩️ Отмена"


def _markup(rows: list[list[str]], placeholder: str | None = None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text) for text in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=placeholder,
    )


def main_menu(*, is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [HOME, PROJECT],
        [OPPORTUNITIES, INBOX],
        [CAREER, MORE],
    ]
    if is_admin:
        rows.append([ADMIN])
    return _markup(rows, "Выбери раздел")


def more_menu() -> ReplyKeyboardMarkup:
    return _markup(
        [
            [LEARN, NETWORK],
            [SHOW, REST],
            [INVESTMENTS_BUTTON, PORTFOLIO],
            [HISTORY, BACK],
        ],
        "Дополнительные действия",
    )


def project_menu(*, actions_left: int) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if actions_left > 0:
        rows.extend(
            [
                [TACTICS["fast"]["title"], TACTICS["careful"]["title"]],
                [TACTICS["team"]["title"]],
            ]
        )
    rows.append([BACK])
    return _markup(rows, "Выбери тактику работы")


def opportunity_board_menu(items: list[dict], *, can_start: bool) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if can_start:
        for item in items:
            if item["status"] == "open":
                rows.append([f"{item['slot']} · {item['title']}"])
    rows.append([BACK])
    return _markup(rows, "Выбери возможность")


def opportunity_choice_menu(view: dict) -> ReplyKeyboardMarkup:
    rows = [
        [f"{choice['index'] + 1} · {choice['title']} · {choice['chance']}%"]
        for choice in view["choices"]
    ]
    return _markup(rows, "Выбери подход")


def inbox_menu(item: dict | None) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if item:
        rows.extend(
            [[f"{index + 1} · {choice[0]}"] for index, choice in enumerate(item["choices"])]
        )
    rows.append([BACK])
    return _markup(rows, "Разобрать сообщение")


def investments_menu() -> ReplyKeyboardMarkup:
    rows = [[item["title"]] for item in INVESTMENTS.values()]
    rows.append([BACK])
    return _markup(rows, "Выбери вложение")


def career_menu(player: dict) -> ReplyKeyboardMarkup:
    rows: list[list[str]] = []
    if player["promotion_ready"]:
        if player["rank"] == 2 and player["track"] == "general":
            rows.extend([["🧠 Экспертный трек"], ["👥 Управленческий трек"]])
        else:
            rows.append(["🚀 Принять повышение"])
    rows.append([BACK])
    return _markup(rows, "Карьера")


def admin_menu(*, fast_mode: bool, can_advance: bool) -> ReplyKeyboardMarkup:
    status = "ВКЛ" if fast_mode else "ВЫКЛ"
    rows = [[f"{FAST}: {status}"]]
    if fast_mode and can_advance:
        rows.append([NEXT_DAY])
    rows.extend([[RESET], [BACK]])
    return _markup(rows, "Админские инструменты")


def reset_confirm_menu() -> ReplyKeyboardMarkup:
    return _markup([[CONFIRM_RESET, CANCEL]], "Подтверди сброс")
