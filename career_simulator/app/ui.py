from __future__ import annotations

from html import escape

from .content import INVESTMENTS, PROMOTION_REQUIREMENTS
from .game import ACTIONS_PER_DAY, MAX_RANK, GameService
from .opportunities import OpportunityService
from .project_play import ProjectPlayService, TACTICS
from .session import SessionService


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₽"


def bar(value: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    filled = max(0, min(width, round(width * value / total)))
    return "▓" * filled + "░" * (width - filled)


def with_notice(screen: str, notice: str | None = None) -> str:
    if not notice:
        return screen
    return f"<blockquote>▸ {escape(notice)}</blockquote>\n\n{screen}"


def _deadline(project: dict, career_day: int) -> str:
    days_left = project["deadline_day"] - career_day
    if days_left > 1:
        return f"через {days_left} дня"
    if days_left == 1:
        return "завтра"
    if days_left == 0:
        return "сегодня"
    return "просрочен"


def _review_text(career_day: int) -> str:
    left = 5 - (career_day % 5)
    if left == 5:
        return "после этого дня"
    return f"через {left} дн."


def _quality_marker(value: int) -> str:
    if value >= 20:
        return "🟢"
    if value >= 8:
        return "🟡"
    return "🔴"


def _risk_marker(value: int) -> str:
    if value >= 45:
        return "🔴"
    if value >= 20:
        return "🟡"
    return "🟢"


def _effect_text(effects: dict[str, int]) -> str:
    labels = {
        "skill": "навык",
        "reputation": "репутация",
        "visibility": "заметность",
        "network": "связи",
        "stress": "стресс",
        "money": "деньги",
    }
    parts: list[str] = []
    for key in ("skill", "reputation", "visibility", "network", "stress", "money"):
        value = effects.get(key, 0)
        if not value:
            continue
        sign = "+" if value > 0 else ""
        suffix = " ₽" if key == "money" else ""
        parts.append(f"{labels[key]} {sign}{value}{suffix}")
    return " · ".join(parts) if parts else "без изменения показателей"


def home_screen(
    game: GameService,
    session: SessionService,
    opportunities: OpportunityService,
    project_play: ProjectPlayService,
    telegram_id: int,
    *,
    fast_mode: bool = False,
) -> str:
    player = game.get_player(telegram_id)
    project = project_play.state(telegram_id)
    inbox = session.inbox_progress(telegram_id)
    runs_left = opportunities.runs_left(telegram_id)
    active_opportunity = opportunities.active_run(telegram_id)
    rank = game.rank_name(player["rank"], player["track"])

    if project:
        progress = round(project["progress"] / project["target"] * 100)
        project_block = (
            f"📌 <b>ПРОЕКТ · {progress}%</b>\n"
            f"{escape(project['title'])}\n"
            f"⏳ {_deadline(project, player['career_day'])} · "
            f"риск: {project_play.risk_label(project['risk'])}"
        )
    else:
        project_block = "📌 <b>ПРОЕКТ</b> · нет активного"

    stress = player["stress"]
    stress_marker = "🟢" if stress < 45 else "🟡" if stress < 75 else "🔴"
    opportunity_text = "…" if active_opportunity else f"{runs_left}/2"
    fast = "\n🧪 Тестовый режим включён" if fast_mode else ""

    return (
        f"🏢 <b>КАРЬЕРИСТ</b>\n"
        f"{escape(rank)} · день {player['career_day']} · ревью {_review_text(player['career_day'])}\n"
        f"━━━━━━━━━━━━\n"
        f"{project_block}\n\n"
        f"⚡ {player['actions_left']}/{ACTIONS_PER_DAY} · "
        f"🎯 {opportunity_text} · ✉️ {inbox['unread']}\n"
        f"{stress_marker} Стресс: {stress}/100\n\n"
        f"🧠 Навык {player['skill']} · ⭐ Репутация {player['reputation']}\n"
        f"👁 Заметность {player['visibility']} · 🤝 Связи {player['network']}\n\n"
        f"💰 {money(player['money'])}{fast}"
    )


def project_screen(
    game: GameService,
    project_play: ProjectPlayService,
    telegram_id: int,
) -> str:
    player = game.get_player(telegram_id)
    project = project_play.state(telegram_id)
    if not project:
        return "📌 <b>ПРОЕКТ</b>\n━━━━━━━━━━━━\nАктивного проекта сейчас нет."

    return (
        f"📌 <b>ПРОЕКТ</b>\n"
        f"━━━━━━━━━━━━\n"
        f"<b>{escape(project['title'])}</b>\n"
        f"{bar(project['progress'], project['target'])} "
        f"{project['progress']}/{project['target']}\n\n"
        f"⏳ Дедлайн: {_deadline(project, player['career_day'])}\n"
        f"{_quality_marker(project['quality'])} Качество: <b>{project_play.quality_label(project['quality'])}</b> ({project['quality']})\n"
        f"{_risk_marker(project['risk'])} Риск: <b>{project_play.risk_label(project['risk'])}</b> ({project['risk']})\n"
        f"💰 Награда: {money(project['reward_money'])}\n\n"
        f"<b>ТАКТИКА</b>\n"
        f"{TACTICS['fast']['title']} · +24-30 прогресса · риск +18 · стресс +9\n"
        f"{TACTICS['careful']['title']} · +16-21 прогресса · качество +16 · риск -4\n"
        f"{TACTICS['team']['title']} · +18-24 прогресса · риск -8 · связи +1\n\n"
        f"⚡ Осталось действий: {player['actions_left']}/{ACTIONS_PER_DAY}\n"
        f"<i>Высокий риск может вызвать переделку. Высокое качество при низком риске повышает награду.</i>"
    )


def opportunity_board_screen(
    game: GameService,
    opportunities: OpportunityService,
    telegram_id: int,
) -> str:
    player = game.get_player(telegram_id)
    active = opportunities.current(telegram_id)
    if active:
        return opportunity_screen(opportunities, telegram_id)

    items = opportunities.board(telegram_id)
    lines = [
        "🎯 <b>ВОЗМОЖНОСТИ</b>",
        "━━━━━━━━━━━━",
        "Редкие карьерные ситуации. На одну попытку тратится 1 ключевое действие.",
        f"Сегодня можно взять ещё: <b>{opportunities.runs_left(telegram_id)}/2</b>",
        "",
    ]
    for item in items:
        state = "✓ использовано" if item["status"] != "open" else "доступно"
        lines.extend(
            [
                f"<b>{item['slot']}. {escape(item['title'])}</b>",
                escape(item["summary"]),
                f"Статус: {state} · база {money(item['reward_money'])}",
                "",
            ]
        )
    if player["actions_left"] <= 0:
        lines.append("⚠️ Для новой возможности сегодня не осталось ключевых действий.")
    return "\n".join(lines).rstrip()


def opportunity_screen(opportunities: OpportunityService, telegram_id: int) -> str:
    view = opportunities.current(telegram_id)
    if not view:
        return "🎯 <b>ВОЗМОЖНОСТЬ</b>\n━━━━━━━━━━━━\nАктивной возможности нет."

    lines = [
        f"🎯 <b>{escape(view['content']['title'])}</b>",
        "━━━━━━━━━━━━",
        f"Этап {view['stage_number']}/{view['stage_total']} · <b>{escape(view['stage']['title'])}</b>",
        "",
        escape(view["stage"]["text"]),
        "",
        "<b>ВАРИАНТЫ</b>",
    ]
    for choice in view["choices"]:
        lines.extend(
            [
                f"{choice['index'] + 1}. <b>{escape(choice['title'])}</b> · "
                f"{choice['chance']}% · {choice['stat_label']}",
                f"   ✓ {_effect_text(choice['success_effects'])}",
                f"   ✕ {_effect_text(choice['fail_effects'])}",
            ]
        )
    lines.extend(
        [
            "",
            "<i>Здесь нет универсально лучшей кнопки: шанс зависит от прокачки, а варианты дают разные карьерные эффекты.</i>",
        ]
    )
    return "\n".join(lines)


def portfolio_screen(opportunities: OpportunityService, telegram_id: int) -> str:
    items = opportunities.portfolio(telegram_id)
    lines = ["🏅 <b>ПОРТФОЛИО</b>", "━━━━━━━━━━━━"]
    if not items:
        lines.append("Пока здесь пусто. Карьерные возможности будут превращаться в конкретные истории и результаты.")
        return "\n".join(lines)
    for item in items:
        lines.append(
            f"День {item['career_day']} · <b>{escape(item['title'])}</b>\n"
            f"{item['tier']} · {item['successes']}/3 · {money(item['reward_money'])}"
        )
        lines.append("")
    return "\n".join(lines).rstrip()


def inbox_screen(session: SessionService, telegram_id: int) -> str:
    progress = session.inbox_progress(telegram_id)
    item = session.next_inbox_item(telegram_id)
    if not item:
        return (
            "✉️ <b>ВХОДЯЩИЕ</b>\n"
            "━━━━━━━━━━━━\n"
            f"Всё разобрано: {progress['resolved']}/{progress['total']}."
        )
    current = item["resolved"] + 1
    return (
        f"✉️ <b>ВХОДЯЩИЕ</b>\n"
        f"━━━━━━━━━━━━\n"
        f"Сообщение {current}/{item['total']}\n\n"
        f"<b>{escape(item['title'])}</b>\n"
        f"{escape(item['text'])}"
    )


def investments_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    lines = [
        "💸 <b>ВЛОЖЕНИЯ</b>",
        "━━━━━━━━━━━━",
        f"На руках: {money(player['money'])}",
        "Одно вложение за активный день.",
        "",
    ]
    for item in INVESTMENTS.values():
        lines.append(f"• <b>{escape(item['title'])}</b> — {money(item['price'])}")
    return "\n".join(lines)


def career_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    current = game.rank_name(player["rank"], player["track"])
    lines = [
        "📈 <b>КАРЬЕРА</b>",
        "━━━━━━━━━━━━",
        f"Должность: <b>{escape(current)}</b>",
        f"Ставка: {money(game.salary(player['rank']))}/день",
        f"Проекты: {player['projects_done']} ✓ · {player['projects_failed']} ✕",
        f"Следующее ревью: {_review_text(player['career_day'])}",
        "",
    ]

    if player["rank"] >= MAX_RANK:
        lines.append("🏆 Текущая карьерная лестница пройдена.")
        return "\n".join(lines)

    labels = {
        "skill": "🧠 Навык",
        "reputation": "⭐ Репутация",
        "visibility": "👁 Заметность",
        "network": "🤝 Связи",
        "projects_done": "📌 Проекты",
    }
    lines.append("<b>ТРЕБОВАНИЯ К ПОВЫШЕНИЮ</b>")
    for key, need in PROMOTION_REQUIREMENTS[player["rank"]].items():
        value = player[key]
        mark = "✓" if value >= need else "○"
        lines.append(f"{mark} {labels[key]}: {value}/{need}")
    if player["promotion_ready"]:
        lines.extend(["", "🚀 Повышение одобрено."])
    return "\n".join(lines)


def history_screen(game: GameService, telegram_id: int) -> str:
    raw = game.recent_history(telegram_id)
    if "\n\n" in raw:
        raw = raw.split("\n\n", 1)[1]
    return f"📜 <b>ИСТОРИЯ</b>\n━━━━━━━━━━━━\n{raw}"


def start_intro() -> str:
    return (
        "Ты начинаешь стажёром. Здесь мало просто нажимать «работать»: "
        "проекты требуют выбирать между скоростью, качеством и риском, а редкие "
        "карьерные возможности проверяют реальные сильные стороны персонажа."
    )
