from __future__ import annotations

from html import escape

from .content import (
    ARMORS,
    ATTRIBUTES,
    BASE_NAME,
    ENEMIES,
    GAME_TITLE,
    ITEMS,
    SECTORS,
    WEAPONS,
    XP_PER_LEVEL,
)
from .game import GameService


def notice(text: str, message: str | None = None) -> str:
    if not message:
        return text
    return f"<blockquote>▸ {escape(message)}</blockquote>\n\n{text}"


def threat_label(value: int) -> str:
    if value < 30:
        return "🟢 низкая"
    if value < 65:
        return "🟡 растёт"
    return "🔴 высокая"


def requirements_text(item: dict) -> str:
    requirements = item.get("requirements", {})
    if not requirements:
        return "без требований"
    return " · ".join(
        f"{ATTRIBUTES[key]['icon']} {ATTRIBUTES[key]['name']} {need}"
        for key, need in requirements.items()
    )


def main_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    weapon = WEAPONS[player["weapon_id"]]
    armor = ARMORS[player["armor_id"]]
    points = game.attribute_points(player)
    stash = game.inventory(telegram_id, secured=1)
    stash_units = sum(row["qty"] for row in stash)
    point_text = f" · ⬆️ очков: {points}" if points else ""
    return (
        f"☢️ <b>{GAME_TITLE}</b>\n"
        f"{BASE_NAME} · уровень {game.level(player)}{point_text}\n"
        "━━━━━━━━━━━━\n"
        f"❤️ {player['hp']}/{game.max_hp(player)} · 🔫 {player['ammo']} · 🩹 {player['medkits']}\n"
        f"💰 {player['credits']} жет. · 📦 склад: {stash_units} ед.\n\n"
        f"🔫 {escape(weapon['name'])}\n"
        f"🦺 {escape(armor['name'])}\n\n"
        f"💪 {player['strength']} · 🏃 {player['agility']} · 👁 {player['perception']} · 🧠 {player['intelligence']}\n"
        f"✨ Опыт {player['xp']}\n\n"
        f"🧭 Успешных вылазок: {player['successful_runs']} · ☠️ смертей: {player['deaths']}"
    )


def sector_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    lines = [
        "🧭 <b>ВЫБОР СЕКТОРА</b>",
        "━━━━━━━━━━━━",
        "Чем опаснее сектор, тем дороже средняя добыча.",
        "",
    ]
    for sector_id, sector in SECTORS.items():
        unlocked = game.sector_unlocked(player, sector_id)
        mark = "🟢" if unlocked else "🔒"
        lines.append(
            f"{mark} <b>{sector['icon']} {escape(sector['name'])}</b> · опасность {sector['danger']}/3"
        )
        lines.append(escape(sector["description"]))
        if not unlocked:
            lines.append(
                f"Нужно: {sector['runs']} успешных вылазок · уровень {sector['level']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def expedition_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    sector = SECTORS[player["sector_id"]]
    weight = game.field_weight(telegram_id)
    capacity = game.carry_capacity(player)
    field = game.inventory(telegram_id, secured=0)
    value = sum(row["qty"] * ITEMS[row["item_id"]]["value"] for row in field)
    return (
        f"{sector['icon']} <b>{escape(sector['name']).upper()}</b>\n"
        "━━━━━━━━━━━━\n"
        f"❤️ {player['hp']}/{game.max_hp(player)} · 🔫 {player['ammo']} · 🩹 {player['medkits']}\n"
        f"🎒 {weight}/{capacity} · добыча примерно на {value} жет.\n\n"
        f"☣️ Угроза: <b>{threat_label(player['threat'])}</b> ({player['threat']}/100)\n"
        f"👣 Пройдено участков: {player['steps']}\n\n"
        "<i>Каждый новый поиск повышает угрозу. Вернёшься сейчас — вся добыча станет безопасной.</i>"
    )


def event_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    sector = SECTORS[player["sector_id"]]
    if player["pending_event"] == "anomaly":
        chance = min(
            90,
            36
            + player["perception"] * 6
            + player["intelligence"] * 5
            - sector["danger"] * 4,
        )
        return (
            "💠 <b>НЕСТАБИЛЬНЫЙ КОНТУР</b>\n"
            "━━━━━━━━━━━━\n"
            "Датчик показывает редкую плотность поля. Можно попытаться снять образец или не лезть.\n\n"
            f"Шанс аккуратного извлечения: <b>{chance}%</b>\n"
            "Успех: редкий осколок и много опыта.\n"
            "Провал: серьёзный урон."
        )
    chance = min(
        94,
        48
        + player["perception"] * 6
        + player["intelligence"] * 3
        - sector["danger"] * 4,
    )
    return (
        "🧰 <b>ТЕХНИЧЕСКИЙ ЯЩИК</b>\n"
        "━━━━━━━━━━━━\n"
        "Герметичный контейнер пережил хозяев. Замок можно вскрыть, но рядом видна старая растяжка.\n\n"
        f"Шанс вскрыть чисто: <b>{chance}%</b>\n"
        "Успех: ресурсы и патроны.\n"
        "Провал: урон."
    )


def combat_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    enemy = ENEMIES[player["enemy_id"]]
    weapon = WEAPONS[player["weapon_id"]]
    aim = " · 🎯 прицел готов" if player["aimed"] else ""
    resistance = game.combat_damage_reduction(player)
    return (
        f"⚔️ <b>БОЙ · {escape(enemy['name']).upper()}</b>\n"
        "━━━━━━━━━━━━\n"
        f"❤️ Ты: {player['hp']}/{game.max_hp(player)}\n"
        f"☠️ Противник: {player['enemy_hp']} HP\n\n"
        f"🔫 {escape(weapon['name'])} · патроны {player['ammo']}{aim}\n"
        f"🛡 Сопротивление урону: {resistance}\n\n"
        "<i>Ловкость повышает сопротивление урону и шанс отступить. Прицеливание тратит ход, но даёт +20% точности следующему выстрелу.</i>"
    )


def inventory_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    secured = game.inventory(telegram_id, secured=1)
    field = game.inventory(telegram_id, secured=0)
    lines = ["🎒 <b>ДОБЫЧА</b>", "━━━━━━━━━━━━"]
    if player["state"] == "base":
        lines.append(f"📦 Склад · стоимость {game.stash_value(telegram_id)} жет.")
        rows = secured
    else:
        lines.append(f"🎒 Рюкзак · {game.field_weight(telegram_id)}/{game.carry_capacity(player)}")
        rows = field
    lines.append("")
    if not rows:
        lines.append("Пусто.")
    else:
        for row in rows:
            item = ITEMS[row["item_id"]]
            lines.append(
                f"{item['icon']} {escape(item['name'])} ×{row['qty']} · {item['value']} жет./ед."
            )
    lines.extend(
        ["", "<i>Ресурсы в рюкзаке теряются при смерти. Склад в Приюте безопасен.</i>"]
    )
    return "\n".join(lines)


def character_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    level = game.level(player)
    points = game.attribute_points(player)
    progress = player["xp"] % XP_PER_LEVEL
    return "\n".join(
        [
            "🧬 <b>ПЕРСОНАЖ</b>",
            "━━━━━━━━━━━━",
            f"Уровень: <b>{level}</b> · ❤️ {game.max_hp(player)} HP",
            f"Опыт до следующего уровня: {progress}/{XP_PER_LEVEL}",
            f"Свободных очков: <b>{points}</b>",
            "",
            f"💪: <b>{player['strength']}</b> · 🏃: <b>{player['agility']}</b> · 👁: <b>{player['perception']}</b> · 🧠: <b>{player['intelligence']}</b>",
            "",
            "<i>Каждый новый уровень даёт 1 очко характеристики и +20 к максимальному здоровью.</i>",
        ]
    )


def shop_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    return (
        "🏪 <b>ТОРГОВЕЦ</b>\n"
        "━━━━━━━━━━━━\n"
        f"💰 На руках: {player['credits']} жет.\n"
        f"📦 Добыча на складе: {game.stash_value(telegram_id)} жет.\n\n"
        "Выбери категорию товаров. Продать всю добычу можно прямо отсюда."
    )


def shop_weapons_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    lines = [
        "🔫 <b>ТОРГОВЕЦ · ОРУЖИЕ</b>",
        "━━━━━━━━━━━━",
        f"💰 На руках: {player['credits']} жет.",
        f"Текущее оружие: {escape(WEAPONS[player['weapon_id']]['name'])}",
        "",
        "<b>БОЕПРИПАСЫ</b>",
        "🔫 Патроны ×6 · 24 жет.",
        "",
        "<b>ОРУЖИЕ</b>",
    ]
    current_order = WEAPONS[player["weapon_id"]]["order"]
    upgrades = 0
    for item_id, item in WEAPONS.items():
        if not item["price"] or item["order"] <= current_order:
            continue
        upgrades += 1
        lock = "🔒" if game.missing_requirements(player, item) else "•"
        lines.append(
            f"{lock} {escape(item['name'])} · {item['price']} жет. · урон {item['damage']} · "
            f"точность {item['accuracy']}%\n   Нужно: {requirements_text(item)}"
        )
    if not upgrades:
        lines.append("Лучшее доступное оружие уже куплено.")
    return "\n".join(lines)


def shop_equipment_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    lines = [
        "🦺 <b>ТОРГОВЕЦ · ЭКИПИРОВКА</b>",
        "━━━━━━━━━━━━",
        f"💰 На руках: {player['credits']} жет.",
        f"Текущая броня: {escape(ARMORS[player['armor_id']]['name'])}",
        "",
    ]
    current_order = ARMORS[player["armor_id"]]["order"]
    upgrades = 0
    for item_id, item in ARMORS.items():
        if not item["price"] or item["order"] <= current_order:
            continue
        upgrades += 1
        lock = "🔒" if game.missing_requirements(player, item) else "•"
        lines.append(
            f"{lock} {escape(item['name'])} · {item['price']} жет. · защита {item['reduction']}\n"
            f"   Нужно: {requirements_text(item)}"
        )
    if not upgrades:
        lines.append("Лучшая доступная экипировка уже куплена.")
    return "\n".join(lines)


def shop_medicine_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    return (
        "🩹 <b>ТОРГОВЕЦ · МЕДИЦИНА</b>\n"
        "━━━━━━━━━━━━\n"
        f"💰 На руках: {player['credits']} жет.\n"
        f"🩹 Аптечек с собой: {player['medkits']}\n\n"
        "🩹 <b>Аптечка</b> · 32 жет.\n"
        "Восстанавливает здоровье. Эффективность повышается Интеллектом."
    )


def rules_screen() -> str:
    return (
        "ℹ️ <b>КАК ИГРАТЬ</b>\n"
        "━━━━━━━━━━━━\n"
        "1. Выбери сектор и отправляйся в вылазку.\n"
        "2. Ищи добычу. Каждый шаг повышает угрозу и шанс неприятной встречи.\n"
        "3. Решай, когда остановиться. До возвращения ресурсы считаются незакреплёнными.\n"
        "4. Опыт повышает уровень. Каждый уровень даёт 1 очко характеристики и +20 HP.\n"
        "5. Сила, Ловкость, Восприятие и Интеллект меняют реальные игровые проверки.\n"
        "6. Ловкость также снижает входящий урон; экипировка может требовать характеристики.\n"
        "7. Более сложные сектора открываются через успешные вылазки и уровень.\n\n"
        "<b>Главное решение игры:</b> вернуться с тем, что уже нашёл, или рискнуть ради следующей находки."
    )
