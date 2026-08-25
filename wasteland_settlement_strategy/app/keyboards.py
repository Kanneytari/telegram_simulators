from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .content import ATTRIBUTES, BUILDINGS, SECTORS
from .scenario import sector_is_unlocked
from .telegram_state import PlayerSession


MAIN_ROWS = [
    [("🏠 Поселение", "menu:settlement"), ("👥 Жители", "menu:residents")],
    [("🧭 Вылазки", "menu:expeditions"), ("🏗 Развитие", "menu:buildings")],
    [("📋 События", "menu:events")],
]


def keyboard(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def main_menu() -> InlineKeyboardMarkup:
    return keyboard(MAIN_ROWS)


def settlement_keyboard() -> InlineKeyboardMarkup:
    return keyboard(
        [
            [("🌙 Следующий день", "day:advance")],
            [("🔄 Обновить", "menu:settlement"), ("🏠 Меню", "menu:home")],
        ]
    )


def residents_keyboard(session: PlayerSession) -> InlineKeyboardMarkup:
    rows = [
        [(f"👤 {resident.name}", f"resident:{resident.id}")]
        for resident in session.engine.state.residents.values()
    ]
    rows.append([("🏠 Меню", "menu:home")])
    return keyboard(rows)


def resident_keyboard(session: PlayerSession, resident_id: str) -> InlineKeyboardMarkup:
    resident = session.engine.state.residents[resident_id]
    rows: list[list[tuple[str, str]]] = []
    if resident.status == "idle" and resident.skill_points > 0:
        rows.append(
            [
                (f"{meta['icon']} {meta['name']}", f"train:{resident_id}:{attribute}")
                for attribute, meta in list(ATTRIBUTES.items())[:2]
            ]
        )
        rows.append(
            [
                (f"{meta['icon']} {meta['name']}", f"train:{resident_id}:{attribute}")
                for attribute, meta in list(ATTRIBUTES.items())[2:]
            ]
        )
    rows.append([("👥 К жителям", "menu:residents"), ("🏠 Меню", "menu:home")])
    return keyboard(rows)


def sectors_keyboard(session: PlayerSession) -> InlineKeyboardMarkup:
    state = session.engine.state
    rows: list[list[tuple[str, str]]] = []
    for sector_id, sector in SECTORS.items():
        unlocked = sector_is_unlocked(state, sector_id)
        icon = sector["icon"] if unlocked else "🔒"
        data = f"sector:{sector_id}" if unlocked else "noop:locked"
        rows.append([(f"{icon} {sector['name']}", data)])
    rows.append([("🔄 Обновить", "menu:expeditions"), ("🏠 Меню", "menu:home")])
    return keyboard(rows)


def squad_keyboard(session: PlayerSession, sector_id: str) -> InlineKeyboardMarkup:
    state = session.engine.state
    rows: list[list[tuple[str, str]]] = []
    for resident in state.residents.values():
        chosen = resident.id in session.selected_residents
        mark = "✅" if chosen else "➕"
        status = "" if resident.status == "idle" else " · занят"
        rows.append(
            [
                (
                    f"{mark} {resident.name}{status}",
                    f"toggle:{sector_id}:{resident.id}",
                )
            ]
        )
    if session.selected_residents:
        rows.append([("🚶 Отправить отряд", f"send:{sector_id}")])
    rows.append([("🧭 К секторам", "menu:expeditions"), ("🏠 Меню", "menu:home")])
    return keyboard(rows)


def buildings_keyboard(session: PlayerSession) -> InlineKeyboardMarkup:
    rows = []
    for building_id, building in session.engine.state.buildings.items():
        meta = BUILDINGS[building_id]
        status = " ⏳" if building.upgrading else ""
        rows.append([(f"{meta['icon']} {meta['name']} · ур. {building.level}{status}", f"building:{building_id}")])
    rows.append([("🔄 Обновить", "menu:buildings"), ("🏠 Меню", "menu:home")])
    return keyboard(rows)


def building_keyboard(session: PlayerSession, building_id: str) -> InlineKeyboardMarkup:
    building = session.engine.state.buildings[building_id]
    meta = BUILDINGS[building_id]
    rows: list[list[tuple[str, str]]] = []
    if not building.upgrading and building.level < meta["max_level"]:
        rows.append([("⬆️ Улучшить", f"upgrade:{building_id}")])
    rows.append([("🏗 К постройкам", "menu:buildings"), ("🏠 Меню", "menu:home")])
    return keyboard(rows)


def events_keyboard() -> InlineKeyboardMarkup:
    return keyboard([[('🔄 Обновить', 'menu:events'), ('🏠 Меню', 'menu:home')]])
