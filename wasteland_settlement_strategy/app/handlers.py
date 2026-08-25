from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .actions import AdvanceDay, StartExpedition, TrainResident, UpgradeBuilding
from .content import SECTORS
from .keyboards import (
    building_keyboard,
    buildings_keyboard,
    events_keyboard,
    main_menu,
    resident_keyboard,
    residents_keyboard,
    sectors_keyboard,
    settlement_keyboard,
    squad_keyboard,
)
from .telegram_state import sessions
from .telegram_views import (
    building_text,
    buildings_text,
    events_text,
    expedition_setup_text,
    expeditions_text,
    home_text,
    rejection_text,
    resident_text,
    residents_text,
    settlement_text,
)


router = Router()


async def edit(callback: CallbackQuery, text: str, reply_markup) -> None:
    if callback.message is not None:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup)
        except Exception as exc:
            if "message is not modified" not in str(exc).lower():
                raise
    await callback.answer()


def user_id_from_callback(callback: CallbackQuery) -> int:
    return callback.from_user.id


@router.message(CommandStart())
async def start(message: Message) -> None:
    session, _ = sessions.sync(message.from_user.id)
    session.chat_id = message.chat.id
    await message.answer(home_text(session), reply_markup=main_menu())


@router.message(Command("reset"))
async def reset(message: Message) -> None:
    session = sessions.reset(message.from_user.id)
    session.chat_id = message.chat.id
    await message.answer("Прогресс сброшен. Приют-7 создан заново.", reply_markup=main_menu())


@router.callback_query(F.data == "menu:home")
async def menu_home(callback: CallbackQuery) -> None:
    session, _ = sessions.sync(user_id_from_callback(callback))
    await edit(callback, home_text(session), main_menu())


@router.callback_query(F.data == "menu:settlement")
async def menu_settlement(callback: CallbackQuery) -> None:
    session, _ = sessions.sync(user_id_from_callback(callback))
    await edit(callback, settlement_text(session), settlement_keyboard())


@router.callback_query(F.data == "menu:residents")
async def menu_residents(callback: CallbackQuery) -> None:
    session, _ = sessions.sync(user_id_from_callback(callback))
    await edit(callback, residents_text(session), residents_keyboard(session))


@router.callback_query(F.data == "menu:expeditions")
async def menu_expeditions(callback: CallbackQuery) -> None:
    session, _ = sessions.sync(user_id_from_callback(callback))
    session.selected_residents.clear()
    await edit(callback, expeditions_text(session), sectors_keyboard(session))


@router.callback_query(F.data == "menu:buildings")
async def menu_buildings(callback: CallbackQuery) -> None:
    session, _ = sessions.sync(user_id_from_callback(callback))
    await edit(callback, buildings_text(session), buildings_keyboard(session))


@router.callback_query(F.data == "menu:events")
async def menu_events(callback: CallbackQuery) -> None:
    session, _ = sessions.sync(user_id_from_callback(callback))
    await edit(callback, events_text(session), events_keyboard())


@router.callback_query(F.data == "noop:locked")
async def locked(callback: CallbackQuery) -> None:
    await callback.answer("Сектор пока закрыт.", show_alert=True)


@router.callback_query(F.data.startswith("resident:"))
async def resident_card(callback: CallbackQuery) -> None:
    resident_id = callback.data.split(":", 1)[1]
    session, _ = sessions.sync(user_id_from_callback(callback))
    if resident_id not in session.engine.state.residents:
        await callback.answer("Житель не найден.", show_alert=True)
        return
    await edit(callback, resident_text(session, resident_id), resident_keyboard(session, resident_id))


@router.callback_query(F.data.startswith("train:"))
async def train(callback: CallbackQuery) -> None:
    _, resident_id, attribute = callback.data.split(":", 2)
    session, _ = sessions.sync(user_id_from_callback(callback))
    result = session.engine.execute(
        TrainResident(resident_id=resident_id, attribute=attribute),
        idempotency_key=f"telegram:{callback.id}",
    )
    if result.status != "success":
        await callback.answer(rejection_text(result.code), show_alert=True)
        return
    if callback.message is not None:
        await callback.message.edit_text(
            resident_text(session, resident_id),
            reply_markup=resident_keyboard(session, resident_id),
        )
    await callback.answer("Обучение начато.")


@router.callback_query(F.data.startswith("sector:"))
async def sector(callback: CallbackQuery) -> None:
    sector_id = callback.data.split(":", 1)[1]
    session, _ = sessions.sync(user_id_from_callback(callback))
    if sector_id not in SECTORS:
        await callback.answer("Сектор не найден.", show_alert=True)
        return
    session.selected_sector = sector_id
    session.selected_residents.clear()
    await edit(
        callback,
        expedition_setup_text(session, sector_id),
        squad_keyboard(session, sector_id),
    )


@router.callback_query(F.data.startswith("toggle:"))
async def toggle_resident(callback: CallbackQuery) -> None:
    _, sector_id, resident_id = callback.data.split(":", 2)
    session, _ = sessions.sync(user_id_from_callback(callback))
    resident = session.engine.state.residents.get(resident_id)
    if resident is None:
        await callback.answer("Житель не найден.", show_alert=True)
        return
    if resident_id in session.selected_residents:
        session.selected_residents.remove(resident_id)
    else:
        if resident.status != "idle":
            await callback.answer("Этот житель сейчас занят.", show_alert=True)
            return
        if len(session.selected_residents) >= 3:
            await callback.answer("В отряде максимум 3 человека.", show_alert=True)
            return
        session.selected_residents.add(resident_id)
    if callback.message is not None:
        await callback.message.edit_text(
            expedition_setup_text(session, sector_id),
            reply_markup=squad_keyboard(session, sector_id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("send:"))
async def send_expedition(callback: CallbackQuery) -> None:
    sector_id = callback.data.split(":", 1)[1]
    session, _ = sessions.sync(user_id_from_callback(callback))
    ordered_ids = tuple(
        resident.id
        for resident in session.engine.state.residents.values()
        if resident.id in session.selected_residents
    )
    result = session.engine.execute(
        StartExpedition(sector_id=sector_id, resident_ids=ordered_ids),
        idempotency_key=f"telegram:{callback.id}",
    )
    if result.status != "success":
        await callback.answer(rejection_text(result.code), show_alert=True)
        return
    session.selected_residents.clear()
    if callback.message is not None:
        await callback.message.edit_text(
            expeditions_text(session),
            reply_markup=sectors_keyboard(session),
        )
    await callback.answer("Отряд отправлен.")


@router.callback_query(F.data.startswith("building:"))
async def building(callback: CallbackQuery) -> None:
    building_id = callback.data.split(":", 1)[1]
    session, _ = sessions.sync(user_id_from_callback(callback))
    if building_id not in session.engine.state.buildings:
        await callback.answer("Постройка не найдена.", show_alert=True)
        return
    await edit(
        callback,
        building_text(session, building_id),
        building_keyboard(session, building_id),
    )


@router.callback_query(F.data.startswith("upgrade:"))
async def upgrade(callback: CallbackQuery) -> None:
    building_id = callback.data.split(":", 1)[1]
    session, _ = sessions.sync(user_id_from_callback(callback))
    result = session.engine.execute(
        UpgradeBuilding(building_id=building_id),
        idempotency_key=f"telegram:{callback.id}",
    )
    if result.status != "success":
        await callback.answer(rejection_text(result.code), show_alert=True)
        return
    if callback.message is not None:
        await callback.message.edit_text(
            building_text(session, building_id),
            reply_markup=building_keyboard(session, building_id),
        )
    await callback.answer("Строительство начато.")


@router.callback_query(F.data == "day:advance")
async def advance_day(callback: CallbackQuery) -> None:
    session, _ = sessions.sync(user_id_from_callback(callback))
    result = session.engine.execute(AdvanceDay(), idempotency_key=f"telegram:{callback.id}")
    if result.status != "success":
        await callback.answer(rejection_text(result.code), show_alert=True)
        return
    if callback.message is not None:
        await callback.message.edit_text(
            settlement_text(session),
            reply_markup=settlement_keyboard(),
        )
    await callback.answer("Наступил следующий день.")
