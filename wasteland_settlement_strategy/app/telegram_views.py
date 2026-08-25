from __future__ import annotations

from datetime import timedelta

from .content import ATTRIBUTES, BUILDINGS, RESOURCES, SECTORS
from .events import (
    BuildingUpgradeStarted,
    BuildingUpgraded,
    DayAdvanced,
    ExpeditionCompleted,
    ExpeditionStarted,
    ResidentLeveled,
    ResidentTrainingCompleted,
    ResidentTrainingStarted,
    SectorMastered,
)
from .model import Resident
from .scenario import sector_is_unlocked, xp_to_next_level
from .telegram_state import PlayerSession


STATUS_NAMES = {
    "idle": "свободен",
    "expedition": "в вылазке",
    "injured": "ранен",
    "training": "тренируется",
}

ERROR_MESSAGES = {
    "unknown_sector": "Неизвестный сектор.",
    "invalid_squad_size": "В отряде должно быть от 1 до 3 жителей.",
    "duplicate_resident": "Один житель не может занимать два места в отряде.",
    "sector_locked": "Этот сектор пока закрыт.",
    "resident_not_found": "Житель не найден.",
    "resident_busy": "Житель сейчас занят.",
    "resident_unfit": "Житель слишком ранен для вылазки.",
    "resident_exhausted": "Житель слишком устал для вылазки.",
    "unknown_building": "Неизвестная постройка.",
    "building_busy": "Эта постройка уже улучшается.",
    "building_max_level": "Постройка уже максимального уровня.",
    "no_skill_points": "У жителя нет свободных очков развития.",
    "unknown_attribute": "Неизвестная характеристика.",
}


def format_duration(delta: timedelta) -> str:
    seconds = max(0, int(delta.total_seconds()))
    minutes = (seconds + 59) // 60
    if minutes < 60:
        return f"{minutes} мин"
    hours, minutes = divmod(minutes, 60)
    if minutes:
        return f"{hours} ч {minutes} мин"
    return f"{hours} ч"


def resource_text(resource_id: str, amount: int) -> str:
    meta = RESOURCES[resource_id]
    return f"{meta['icon']} {meta['name']}: {amount}"


def home_text(session: PlayerSession) -> str:
    state = session.engine.state
    idle = sum(r.status == "idle" for r in state.residents.values())
    away = sum(r.status == "expedition" for r in state.residents.values())
    injured = sum(r.status == "injured" for r in state.residents.values())
    active_builds = sum(b.upgrading for b in state.buildings.values())
    active_training = sum(r.status == "training" for r in state.residents.values())

    return "\n".join(
        [
            f"☢️ {state.name} · день {state.day}",
            f"🙂 Мораль: {state.morale}/100",
            "",
            f"👥 Свободны: {idle} · в вылазке: {away} · ранены: {injured}",
            f"⏳ Строек: {active_builds} · обучаются: {active_training}",
            "",
            f"🥫 {state.resources['food']}   💧 {state.resources['water']}   📦 {state.resources['ammo']}",
            f"🔩 {state.resources['scrap']}   ⚙️ {state.resources['parts']}   🩹 {state.resources['medicine']}",
            "",
            "Выберите раздел.",
        ]
    )


def settlement_text(session: PlayerSession) -> str:
    state = session.engine.state
    lines = [
        f"🏠 {state.name}",
        f"День {state.day} · мораль {state.morale}/100",
        "",
        "Запасы:",
    ]
    for resource_id in ("food", "water", "ammo", "medicine", "scrap", "wire", "chem", "parts", "shard"):
        lines.append(resource_text(resource_id, state.resources.get(resource_id, 0)))

    lines.append("")
    lines.append("Текущие процессы:")
    if not session.engine.pending_triggers:
        lines.append("• ничего не происходит")
    else:
        now = session.engine.clock.now()
        for trigger in session.engine.pending_triggers:
            action_name = type(trigger.action).__name__
            if action_name == "ResolveExpedition":
                expedition = state.expeditions.get(trigger.action.expedition_id)
                label = "вылазка"
                if expedition:
                    label = f"вылазка: {SECTORS[expedition.sector_id]['name']}"
            elif action_name == "CompleteBuildingUpgrade":
                label = f"стройка: {BUILDINGS[trigger.action.building_id]['name']}"
            elif action_name == "CompleteTraining":
                resident = state.residents[trigger.action.resident_id]
                label = f"обучение: {resident.name}"
            else:
                label = action_name
            lines.append(f"• {label} · ещё {format_duration(trigger.at - now)}")
    return "\n".join(lines)


def residents_text(session: PlayerSession) -> str:
    state = session.engine.state
    lines = ["👥 Жители", ""]
    for resident in state.residents.values():
        lines.append(
            f"{resident.name} · ур. {resident.level} · HP {resident.hp}/100 · "
            f"усталость {resident.fatigue}/100 · {STATUS_NAMES.get(resident.status, resident.status)}"
        )
    lines.extend(["", "Нажмите на жителя, чтобы открыть карточку."])
    return "\n".join(lines)


def resident_text(session: PlayerSession, resident_id: str) -> str:
    resident = session.engine.state.residents[resident_id]
    return "\n".join(
        [
            f"👤 {resident.name} · уровень {resident.level}",
            f"Состояние: {STATUS_NAMES.get(resident.status, resident.status)}",
            f"❤️ HP: {resident.hp}/100",
            f"😮‍💨 Усталость: {resident.fatigue}/100",
            f"⭐ XP: {resident.xp}/{xp_to_next_level(resident.level)}",
            f"➕ Очки развития: {resident.skill_points}",
            "",
            f"💪 Сила: {resident.strength}",
            f"🏃 Ловкость: {resident.agility}",
            f"👁 Восприятие: {resident.perception}",
            f"🧠 Интеллект: {resident.intelligence}",
        ]
    )


def expeditions_text(session: PlayerSession) -> str:
    state = session.engine.state
    lines = ["🧭 Вылазки", ""]
    active = [exp for exp in state.expeditions.values() if exp.status == "active"]
    if active:
        lines.append("Сейчас в пустоши:")
        for expedition in active:
            names = ", ".join(state.residents[rid].name for rid in expedition.resident_ids)
            remaining = format_duration(expedition.resolves_at - session.engine.clock.now())
            lines.append(f"• {SECTORS[expedition.sector_id]['name']} · {names} · ещё {remaining}")
        lines.append("")

    lines.append("Доступные направления:")
    for sector_id, sector in SECTORS.items():
        if sector_is_unlocked(state, sector_id):
            lines.append(
                f"{sector['icon']} {sector['name']} · опасность {sector['danger']} · "
                f"освоение {state.sector_progress[sector_id]}/100"
            )
        else:
            required = SECTORS[sector["requires_mastery"]]["name"]
            lines.append(f"🔒 {sector['name']} · сначала освоить {required}")
    return "\n".join(lines)


def expedition_setup_text(session: PlayerSession, sector_id: str) -> str:
    state = session.engine.state
    sector = SECTORS[sector_id]
    selected = [state.residents[rid].name for rid in session.selected_residents if rid in state.residents]
    supplies = " · ".join(
        f"{RESOURCES[resource]['icon']} {amount}/чел."
        for resource, amount in sector["supplies_per_resident"].items()
    )
    lines = [
        f"{sector['icon']} {sector['name']}",
        f"Опасность: {sector['danger']}",
        f"Длительность: {sector['duration_minutes']} мин",
        f"Освоение: {state.sector_progress[sector_id]}/100",
        f"Припасы: {supplies}",
        "",
        "Отряд: " + (", ".join(selected) if selected else "не выбран"),
        "",
        "Выберите от 1 до 3 свободных жителей.",
    ]
    return "\n".join(lines)


def buildings_text(session: PlayerSession) -> str:
    state = session.engine.state
    lines = ["🏗 Развитие поселения", ""]
    for building_id, building in state.buildings.items():
        meta = BUILDINGS[building_id]
        suffix = " · строится" if building.upgrading else ""
        lines.append(f"{meta['icon']} {meta['name']} · ур. {building.level}/{meta['max_level']}{suffix}")
        lines.append(f"  {meta['effect']}")
    return "\n".join(lines)


def building_text(session: PlayerSession, building_id: str) -> str:
    state = session.engine.state
    building = state.buildings[building_id]
    meta = BUILDINGS[building_id]
    target = building.level + 1
    lines = [
        f"{meta['icon']} {meta['name']}",
        f"Уровень: {building.level}/{meta['max_level']}",
        f"Эффект: {meta['effect']}",
    ]
    if building.upgrading:
        lines.extend(["", "⏳ Улучшение уже идёт."])
    elif building.level >= meta["max_level"]:
        lines.extend(["", "Максимальный уровень достигнут."])
    else:
        factor = 1 + 0.6 * (target - 1)
        cost = {
            resource: max(1, int(round(amount * factor)))
            for resource, amount in meta["base_cost"].items()
        }
        duration = meta["base_duration_minutes"] * target
        lines.extend(
            [
                "",
                f"Следующий уровень: {target}",
                "Стоимость: " + " · ".join(resource_text(r, a) for r, a in cost.items()),
                f"Время: {duration} мин",
            ]
        )
    return "\n".join(lines)


def event_text(session: PlayerSession, event: object) -> str:
    state = session.engine.state
    if isinstance(event, ExpeditionStarted):
        names = ", ".join(state.residents[rid].name for rid in event.resident_ids)
        return f"🧭 Отряд ({names}) отправлен: {SECTORS[event.sector_id]['name']}"
    if isinstance(event, ExpeditionCompleted):
        result = "успех" if event.success else "неудача"
        loot = ", ".join(
            f"{RESOURCES[r]['icon']} {amount}" for r, amount in event.loot.items()
        ) or "без добычи"
        injured = ", ".join(state.residents[rid].name for rid in event.injured_resident_ids)
        suffix = f" · ранены: {injured}" if injured else ""
        return (
            f"{'✅' if event.success else '⚠️'} Вылазка: {SECTORS[event.sector_id]['name']} · {result} · "
            f"добыча: {loot} · освоение +{event.progress_gained}{suffix}"
        )
    if isinstance(event, SectorMastered):
        return f"🗺 Освоен сектор: {SECTORS[event.sector_id]['name']}"
    if isinstance(event, ResidentLeveled):
        return f"⭐ {state.residents[event.resident_id].name} получил уровень {event.new_level}"
    if isinstance(event, ResidentTrainingStarted):
        return f"🎯 {state.residents[event.resident_id].name} начал обучение: {ATTRIBUTES[event.attribute]['name']}"
    if isinstance(event, ResidentTrainingCompleted):
        return (
            f"✅ {state.residents[event.resident_id].name}: {ATTRIBUTES[event.attribute]['name']} "
            f"повышена до {event.new_value}"
        )
    if isinstance(event, BuildingUpgradeStarted):
        return f"🏗 Начато улучшение: {BUILDINGS[event.building_id]['name']} → ур. {event.target_level}"
    if isinstance(event, BuildingUpgraded):
        return f"✅ {BUILDINGS[event.building_id]['name']} улучшен до ур. {event.new_level}"
    if isinstance(event, DayAdvanced):
        return (
            f"🌙 Наступил день {event.day} · еда {event.food_delta:+d} · "
            f"вода {event.water_delta:+d} · мораль {event.morale_delta:+d}"
        )
    return type(event).__name__


def events_text(session: PlayerSession, limit: int = 12) -> str:
    events = session.engine.event_log[-limit:]
    if not events:
        return "📋 События\n\nПока ничего не произошло."
    lines = ["📋 Последние события", ""]
    lines.extend(event_text(session, event) for event in reversed(events))
    return "\n".join(lines)


def rejection_text(code: str | None) -> str:
    if not code:
        return "Действие не выполнено."
    if code.startswith("not_enough_"):
        resource_id = code.removeprefix("not_enough_")
        meta = RESOURCES.get(resource_id)
        if meta:
            return f"Не хватает ресурса: {meta['name']}."
    return ERROR_MESSAGES.get(code, f"Действие недоступно: {code}.")
