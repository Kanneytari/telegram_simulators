from __future__ import annotations

from html import escape

from .content import ARMORS, BASE_NAME, ENEMIES, GAME_TITLE, ITEMS, MAX_SKILL, SECTORS, WEAPONS, XP_PER_SKILL_POINT
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


def main_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    weapon = WEAPONS[player["weapon_id"]]
    armor = ARMORS[player["armor_id"]]
    points = game.skill_points(player)
    stash = game.inventory(telegram_id, secured=1)
    stash_units = sum(row["qty"] for row in stash)
    return (
        f"☢️ <b>{GAME_TITLE}</b>\n"
        f"{BASE_NAME}\n"
        f"━━━━━━━━━━━━\n"
        f"❤️ {player['hp']}/{game.max_hp(player)} · 🔫 {player['ammo']} · 🩹 {player['medkits']}\n"
        f"💰 {player['credits']} жет. · 📦 склад: {stash_units} ед.\n\n"
        f"🔫 {escape(weapon['name'])}\n"
        f"🦺 {escape(armor['name'])}\n\n"
        f"⚔️ Бой {player['combat']} · 🔎 Поиск {player['scavenging']} · 🛡 Выживание {player['survival']}\n"
        f"🧠 Опыт {player['xp']} · свободных очков: <b>{points}</b>\n\n"
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
        lines.append(f"{mark} <b>{sector['icon']} {escape(sector['name'])}</b> · опасность {sector['danger']}/3")
        lines.append(escape(sector["description"]))
        if not unlocked:
            lines.append(f"Нужно: {sector['runs']} успешных вылазок · Выживание {sector['survival']}")
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
        f"━━━━━━━━━━━━\n"
        f"❤️ {player['hp']}/{game.max_hp(player)} · 🔫 {player['ammo']} · 🩹 {player['medkits']}\n"
        f"🎒 {weight}/{capacity} · добыча примерно на {value} жет.\n\n"
        f"☣️ Угроза: <b>{threat_label(player['threat'])}</b> ({player['threat']}/100)\n"
        f"👣 Пройдено участков: {player['steps']}\n\n"
        f"<i>Каждый новый поиск повышает угрозу. Вернёшься сейчас — вся добыча станет безопасной.</i>"
    )


def event_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    sector = SECTORS[player["sector_id"]]
    if player["pending_event"] == "anomaly":
        chance = min(88, 43 + player["scavenging"] * 7 + player["survival"] * 4 - sector["danger"] * 4)
        return (
            "💠 <b>НЕСТАБИЛЬНЫЙ КОНТУР</b>\n"
            "━━━━━━━━━━━━\n"
            "Датчик показывает редкую плотность поля. Можно попытаться снять образец или не лезть.\n\n"
            f"Шанс аккуратного извлечения: <b>{chance}%</b>\n"
            "Успех: редкий осколок и много опыта.\n"
            "Провал: серьёзный урон."
        )
    chance = min(92, 54 + player["scavenging"] * 7 - sector["danger"] * 4)
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
    return (
        f"⚔️ <b>БОЙ · {escape(enemy['name']).upper()}</b>\n"
        f"━━━━━━━━━━━━\n"
        f"❤️ Ты: {player['hp']}/{game.max_hp(player)}\n"
        f"☠️ Противник: {player['enemy_hp']} HP\n\n"
        f"🔫 {escape(weapon['name'])} · патроны {player['ammo']}{aim}\n"
        f"🦺 Снижение урона: {ARMORS[player['armor_id']]['reduction']}\n\n"
        f"<i>Прицеливание тратит ход, но даёт +20% точности следующему выстрелу. Ближний бой экономит патроны.</i>"
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
            lines.append(f"{item['icon']} {escape(item['name'])} ×{row['qty']} · {item['value']} жет./ед.")
    lines.extend(["", "<i>Ресурсы в рюкзаке теряются при смерти. Склад в Приюте безопасен.</i>"])
    return "\n".join(lines)


def character_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    points = game.skill_points(player)
    progress = player["xp"] % XP_PER_SKILL_POINT
    return (
        "🧬 <b>ПЕРСОНАЖ</b>\n"
        "━━━━━━━━━━━━\n"
        f"Свободных очков: <b>{points}</b>\n"
        f"До следующего очка: {progress}/{XP_PER_SKILL_POINT} опыта\n\n"
        f"⚔️ <b>Бой {player['combat']}/{MAX_SKILL}</b>\n"
        "Точность огнестрела, урон и эффективность ближнего боя.\n\n"
        f"🔎 <b>Поиск {player['scavenging']}/{MAX_SKILL}</b>\n"
        "Лучше добыча и выше шанс безопасно вскрывать опасные находки.\n\n"
        f"🛡 <b>Выживание {player['survival']}/{MAX_SKILL}</b>\n"
        f"Больше HP и рюкзак. Сейчас: {game.max_hp(player)} HP · {game.carry_capacity(player)} веса."
    )


def shop_screen(game: GameService, telegram_id: int) -> str:
    player = game.get_player(telegram_id)
    lines = [
        "🏪 <b>ТОРГОВЕЦ</b>",
        "━━━━━━━━━━━━",
        f"💰 На руках: {player['credits']} жет.",
        f"📦 Добыча на складе: {game.stash_value(telegram_id)} жет.",
        "",
        "<b>РАСХОДНИКИ</b>",
        "🔫 Патроны ×6 · 24 жет.",
        "🩹 Аптечка · 32 жет.",
        "",
        "<b>СНАРЯЖЕНИЕ</b>",
    ]
    for weapon_id, item in WEAPONS.items():
        if item["price"]:
            mark = "✓" if player["weapon_id"] == weapon_id else "•"
            lines.append(f"{mark} {escape(item['name'])} · {item['price']} жет. · урон {item['damage']} · точность {item['accuracy']}%")
    for armor_id, item in ARMORS.items():
        if item["price"]:
            mark = "✓" if player["armor_id"] == armor_id else "•"
            lines.append(f"{mark} {escape(item['name'])} · {item['price']} жет. · защита {item['reduction']}")
    return "\n".join(lines)


def rules_screen() -> str:
    return (
        "ℹ️ <b>КАК ИГРАТЬ</b>\n"
        "━━━━━━━━━━━━\n"
        "1. Выбери сектор и отправляйся в вылазку.\n"
        "2. Ищи добычу. Каждый шаг повышает угрозу и шанс неприятной встречи.\n"
        "3. Решай, когда остановиться. До возвращения ресурсы считаются незакреплёнными.\n"
        "4. В Приюте продавай добычу, покупай снаряжение и прокачивай навыки.\n"
        "5. Более сложные сектора открываются через успешные вылазки и Выживание.\n\n"
        "<b>Главное решение игры:</b> вернуться с тем, что уже нашёл, или рискнуть ради следующей находки."
    )
