from __future__ import annotations

from html import escape

from .content import INVESTMENTS, PROMOTION_REQUIREMENTS
from .game import ACTIONS_PER_DAY, MAX_RANK, GameService
from .session import SessionService


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₽"


def bar(value: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "·" * width
    filled = max(0, min(width, round(width * value / total)))
    return "▰" * filled + "▱" * (width - filled)


def with_notice(screen: str, notice: str | None = None) -> str:
    if not notice:
        return screen
    cleaned = notice
    for marker in ("✅ ", "🔥 ", "📌 ", "🚀 ", "🏆 ", "🗂 ", "⚠️ "):
        cleaned = cleaned.replace(marker, "")
    return f"<blockquote>{escape(cleaned)}</blockquote>\n\n{screen}"


def home_screen(
    game: GameService,
    session: SessionService,
    telegram_id: int,
    *,
    fast_mode: bool = False,
) -> str:
    player = game.get_player(telegram_id)
    project = game.get_active_project(telegram_id)
    inbox = session.inbox_progress(telegram_id)
    focus_left = session.focus_runs_left(telegram_id)
    active_focus = session.active_focus(telegram_id)
    rank = game.rank_name(player["rank"], player["track"])

    if project:
        days_left = project["deadline_day"] - player["career_day"]
        if days_left > 1:
            deadline = f"до дедлайна {days_left} дня"
        elif days_left == 1:
            deadline = "до дедлайна 1 день"
        elif days_left == 0:
            deadline = "дедлайн сегодня"
        else:
            deadline = "дедлайн просрочен"
        project_block = (
            f"<b>Проект</b>\n"
            f"{escape(project['title'])}\n"
            f"{bar(project['progress'], project['target'])} "
            f"{project['progress']}/{project['target']} · {deadline}"
        )
    else:
        project_block = "<b>Проект</b>\nАктивного проекта нет."

    stress = player["stress"]
    stress_label = "спокойно" if stress < 45 else "напряжённо" if stress < 75 else "опасно"
    fast = "\nТестовый режим: включён" if fast_mode else ""
    focus_state = "в процессе" if active_focus else f"{focus_left}/2"

    return (
        f"<b>Карьерист</b>\n"
        f"{escape(rank)} · день {player['career_day']}\n\n"
        f"{project_block}\n\n"
        f"<b>Сегодня</b>\n"
        f"Действия: {player['actions_left']}/{ACTIONS_PER_DAY} · "
        f"входящие: {inbox['unread']} · фокус: {focus_state}\n"
        f"Стресс: {stress}/100 ({stress_label})\n\n"
        f"<b>Рост</b>\n"
        f"Навык {player['skill']} · репутация {player['reputation']}\n"
        f"Заметность {player['visibility']} · связи {player['network']}\n"
        f"Деньги: {money(player['money'])}{fast}"
    )


def project_screen(game: GameService, session: SessionService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    project = game.get_active_project(telegram_id)
    active_focus = session.active_focus(telegram_id)
    focus_left = session.focus_runs_left(telegram_id)

    if not project:
        return "<b>Карьерист · Проект</b>\n\nАктивного проекта сейчас нет."

    days_left = project["deadline_day"] - player["career_day"]
    deadline = "сегодня" if days_left == 0 else f"через {days_left} дн." if days_left > 0 else "просрочен"
    focus_line = (
        "Фокус-сессия уже начата - её можно продолжить."
        if active_focus
        else f"Фокус-сессий осталось: {focus_left}/2."
    )
    action_line = (
        f"Ключевых действий осталось: {player['actions_left']}/{ACTIONS_PER_DAY}."
        if player["actions_left"]
        else "Ключевые действия на сегодня закончились."
    )

    return (
        f"<b>Карьерист · Проект</b>\n\n"
        f"<b>{escape(project['title'])}</b>\n"
        f"{bar(project['progress'], project['target'])} {project['progress']}/{project['target']}\n"
        f"Дедлайн: {deadline}\n"
        f"Награда: {money(project['reward_money'])} · +{project['reward_rep']} репутации\n\n"
        f"<b>Как работать</b>\n"
        f"Фокус - три решения подряд и немного выше эффективность.\n"
        f"Быстрая работа - мгновенный результат без дополнительных решений.\n\n"
        f"{focus_line}\n{action_line}"
    )


def focus_screen(session: SessionService, telegram_id: int) -> str:
    view = session.focus_view(telegram_id)
    if not view:
        return "<b>Карьерист · Фокус</b>\n\nАктивной фокус-сессии нет."
    step = view["step"]
    return (
        f"<b>Карьерист · Фокус</b>\n"
        f"Шаг {view['step_number']} из {view['step_total']} · {escape(step['title'])}\n\n"
        f"{escape(step['text'])}\n\n"
        f"Выбери подход."
    )


def inbox_screen(session: SessionService, telegram_id: int) -> str:
    progress = session.inbox_progress(telegram_id)
    item = session.next_inbox_item(telegram_id)
    if not item:
        return (
            f"<b>Карьерист · Входящие</b>\n\n"
            f"Всё разобрано: {progress['resolved']}/{progress['total']}.\n"
            f"Новых решений здесь сегодня не осталось."
        )
    current = item["resolved"] + 1
    return (
        f"<b>Карьерист · Входящие</b>\n"
        f"{current} из {item['total']} · осталось {item['unread']}\n\n"
        f"<b>{escape(item['title'])}</b>\n"
        f"{escape(item['text'])}"
    )


def investments_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    lines = [
        "<b>Карьерист · Вложения</b>",
        "",
        f"На руках: {money(player['money'])}",
        "Одно вложение за активный день.",
        "",
    ]
    for item in INVESTMENTS.values():
        lines.append(f"<b>{escape(item['title'])}</b> · {money(item['price'])}")
    return "\n".join(lines)


def career_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    current = game.rank_name(player["rank"], player["track"])
    track = ""
    if player["track"] != "general":
        track_name = "Экспертный" if player["track"] == "expert" else "Управленческий"
        track = f" · {track_name} трек"

    lines = [
        "<b>Карьерист · Карьера</b>",
        "",
        f"{escape(current)}{track}",
        f"Ставка за день: {money(game.salary(player['rank']))}",
        f"Проекты: {player['projects_done']} закрыто · {player['projects_failed']} провалено",
        "",
    ]

    if player["rank"] >= MAX_RANK:
        lines.append("Текущая карьерная лестница пройдена.")
        return "\n".join(lines)

    labels = {
        "skill": "Навык",
        "reputation": "Репутация",
        "visibility": "Заметность",
        "network": "Связи",
        "projects_done": "Проекты",
    }
    lines.append("<b>Следующее повышение</b>")
    for key, need in PROMOTION_REQUIREMENTS[player["rank"]].items():
        value = player[key]
        mark = "✓" if value >= need else "·"
        lines.append(f"{mark} {labels[key]}: {value}/{need}")
    if player["promotion_ready"]:
        lines.extend(["", "Повышение одобрено. Осталось его принять."])
    else:
        lines.extend(["", "Ревью проходит каждые 5 активных дней."])
    return "\n".join(lines)


def history_screen(game: GameService, telegram_id: int) -> str:
    raw = game.recent_history(telegram_id)
    if "\n\n" in raw:
        raw = raw.split("\n\n", 1)[1]
    return f"<b>Карьерист · История</b>\n\n{raw}"


def start_intro() -> str:
    return (
        "Ты начинаешь стажёром. Хорошо работать недостаточно: придётся расти, "
        "строить связи, показывать результат и не выгореть.\n"
        "5 ключевых действий задают стратегию дня; входящие и фокус-сессии "
        "дают пространство для более длинной игровой сессии."
    )
