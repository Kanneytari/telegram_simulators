from __future__ import annotations

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .content import LOCATIONS, ROUTES
from .ui import level_up_notice


def travel_screen(game, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    travel = game.travel_state(telegram_id)
    if not travel:
        return game.location(telegram_id)["name"]

    route = ROUTES[travel["route_id"]]
    origin = LOCATIONS[travel["origin_id"]]
    target = LOCATIONS[travel["target_id"]]
    stages = int(route["stages"])
    step = int(travel["step"])
    remaining = max(0, stages - step)

    lines = [
        f"🛣 <b>{escape(route['name']).upper()}</b>",
        f"{origin['icon']} {escape(origin['name'])} → {target['icon']} {escape(target['name'])}",
        "━━━━━━━━━━━━",
    ]
    notice = level_up_notice(game, player)
    if notice:
        lines.append(notice)

    if remaining:
        lines.append(f"👣 До {escape(target['name'])}: {remaining} участков")
    else:
        lines.append(f"📍 Ты у входа в {escape(target['name'])}.")

    lines += [
        f"⚠️ Опасность: {route['danger']}/3",
        f"🚚 Груз: {game.cargo_weight(telegram_id)}/{game.carry_capacity(player)} веса",
        f"💰 В пункте назначения: ~{game.cargo_value_at(telegram_id, travel['target_id'])} жет.",
        "",
        (
            "<i>Дорога пройдена. Можно войти в поселение или развернуться.</i>"
            if remaining == 0
            else "<i>Каждый участок дороги опасен. Можно развернуться и пройти путь обратно.</i>"
        ),
    ]
    return "\n".join(lines)


def travel_keyboard(game, telegram_id: int) -> InlineKeyboardMarkup:
    travel = game.travel_state(telegram_id)
    if not travel:
        return InlineKeyboardMarkup(inline_keyboard=[])

    route = ROUTES[travel["route_id"]]
    origin = LOCATIONS[travel["origin_id"]]
    target = LOCATIONS[travel["target_id"]]
    step = int(travel["step"])

    if step >= int(route["stages"]):
        advance_text = f"🏁 Войти в {target['name']}"
    else:
        advance_text = f"👣 Дальше к {target['name']}"

    turn_text = (
        f"↩️ Вернуться в {origin['name']}"
        if step <= 0
        else f"↩️ Повернуть к {origin['name']}"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=advance_text, callback_data="road:advance")],
            [InlineKeyboardButton(text=turn_text, callback_data="road:turn")],
            [InlineKeyboardButton(text="🚚 Груз", callback_data="road:cargo")],
        ]
    )
