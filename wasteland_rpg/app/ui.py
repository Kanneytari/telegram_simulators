from __future__ import annotations

from html import escape

from .content import (
    ARMORS, ATTRIBUTES, BACKPACKS, ENEMIES, EXPEDITION_SCENES, GADGETS,
    HEADGEAR, ITEMS, LOCATIONS, ROUTES, SECTORS, WEAPONS, XP_PER_LEVEL,
)
from .game import GameService


def notice(text: str, message: str | None = None) -> str:
    return f"<blockquote>▸ {escape(message)}</blockquote>\n\n{text}" if message else text


def level_up_notice(game: GameService, player: dict) -> str:
    points = game.attribute_points(player)
    if points <= 0:
        return ""
    message = (
        "⬆️ Новый уровень! Выбери характеристику для улучшения."
        if points == 1
        else f"⬆️ Новые уровни! Доступно очков характеристик: {points}."
    )
    return f"<blockquote>{message}</blockquote>"


def _level_line(game: GameService, player: dict) -> str:
    block = level_up_notice(game, player)
    return f"{block}\n" if block else ""


def requirements_text(item: dict) -> str:
    req = item.get("requirements", {})
    return "без требований" if not req else " · ".join(
        f"{ATTRIBUTES[k]['icon']} {ATTRIBUTES[k]['name']} {v}" for k, v in req.items()
    )


def threat_label(value: int) -> str:
    return "🟢 низкая" if value < 30 else "🟡 растёт" if value < 65 else "🔴 высокая"


def main_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id)
    loc = game.location(telegram_id)
    eq = game.equipment(telegram_id)
    stash = sum(r["qty"] for r in game.inventory(telegram_id, secured=1))
    cargo = sum(r["qty"] for r in game.cargo(telegram_id))
    return (
        f"{loc['icon']} <b>{escape(loc['name']).upper()}</b> · уровень {game.level(p)}\n"
        "━━━━━━━━━━━━\n"
        f"{_level_line(game, p)}"
        f"❤️ {p['hp']}/{game.max_hp(p)} · 🔫 {p['ammo']} · 🩹 {p['medkits']}\n"
        f"💰 {p['credits']} жет. · 📦 склад {stash} · 🚚 груз {cargo}\n\n"
        f"🔫 {escape(WEAPONS[p['weapon_id']]['name'])}\n"
        f"🦺 {escape(ARMORS[p['armor_id']]['name'])} · 🎒 {escape(BACKPACKS[eq['backpack_id']]['name'])}\n"
        f"🪖 {escape(HEADGEAR[eq['headgear_id']]['name'])} · 📡 {escape(GADGETS[eq['gadget_id']]['name'])}\n\n"
        f"💪 {p['strength']} · 🏃 {p['agility']} · 👁 {p['perception']} · 🧠 {p['intelligence']}\n"
        f"✨ Опыт {p['xp']}\n\n"
        f"🧭 Успешных вылазок: {p['successful_runs']} · ☠️ смертей: {p['deaths']}"
    )


def map_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id)
    loc = game.location(telegram_id)
    visited = game.visited_locations(telegram_id)
    lines = [f"🗺 <b>КАРТА · {escape(loc['name']).upper()}</b>", "━━━━━━━━━━━━"]
    if level_up_notice(game, p): lines.append(level_up_notice(game, p))
    lines += [escape(loc["description"]), ""]
    for route in game.connected_routes(telegram_id):
        target = LOCATIONS[route["target"]]
        status = "🔒" if not route["unlocked"] else "✅" if route["target"] in visited else "🆕"
        lines += [f"{status} <b>{escape(route['name'])}</b> → {target['icon']} {escape(target['name'])}", f"   {route['stages']} участков · опасность {route['danger']}/3 · уровень {route['level']}"]
    return "\n".join(lines)


def travel_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); t = game.travel_state(telegram_id)
    if not t: return main_screen(game, telegram_id)
    route = ROUTES[t["route_id"]]; origin = LOCATIONS[t["origin_id"]]; target = LOCATIONS[t["target_id"]]
    final = "Дорога пройдена. Осталось войти в поселение." if t["step"] >= route["stages"] else "В дороге торговый груз теряется при смерти."
    return f"🛣 <b>{escape(route['name']).upper()}</b>\n{origin['icon']} {escape(origin['name'])} → {target['icon']} {escape(target['name'])}\n━━━━━━━━━━━━\n{_level_line(game, p)}👣 Путь: {t['step']}/{route['stages']} участков\n⚠️ Опасность: {route['danger']}/3\n🚚 Груз: {game.cargo_weight(telegram_id)}/{game.carry_capacity(p)} веса\n💰 В пункте назначения: ~{game.cargo_value_at(telegram_id, t['target_id'])} жет.\n\n<i>{final}</i>"


def market_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); loc = game.location(telegram_id)
    lines = [f"📈 <b>РЫНОК · {escape(loc['name']).upper()}</b>", "━━━━━━━━━━━━"]
    if level_up_notice(game, p): lines.append(level_up_notice(game, p))
    lines += [f"💰 {p['credits']} жет.", f"🚚 Груз {game.cargo_weight(telegram_id)}/{game.carry_capacity(p)} · здесь {game.cargo_value_at(telegram_id)} жет.", f"📦 Склад · здесь {game.stash_value(telegram_id)} жет.", "", "<b>Купить / продать</b>"]
    for item_id, price in loc["market"].items():
        item = ITEMS[item_id]; lines.append(f"{item['icon']} {escape(item['name'])}: {price['buy']} / {price['sell']} жет.")
    lines += ["", "<i>Купленные товары сразу попадают в торговый груз.</i>"]
    return "\n".join(lines)


def sector_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); loc = game.location(telegram_id)
    lines = [f"🧭 <b>ВЫЛАЗКИ · {escape(loc['name']).upper()}</b>", "━━━━━━━━━━━━"]
    if level_up_notice(game, p): lines.append(level_up_notice(game, p))
    for sid, s in game.local_sectors(telegram_id):
        unlocked = game.sector_unlocked(p, sid)
        lines += [f"{'🟢' if unlocked else '🔒'} <b>{s['icon']} {escape(s['name'])}</b> · опасность {s['danger']}/3", escape(s["description"])]
        if not unlocked: lines.append(f"Нужно: {s['runs']} вылазок · уровень {s['level']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def expedition_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); s = SECTORS[p["sector_id"]]
    field = game.inventory(telegram_id, secured=0); value = sum(r["qty"] * ITEMS[r["item_id"]]["value"] for r in field)
    return f"{s['icon']} <b>{escape(s['name']).upper()}</b>\n━━━━━━━━━━━━\n{_level_line(game, p)}❤️ {p['hp']}/{game.max_hp(p)} · 🔫 {p['ammo']} · 🩹 {p['medkits']}\n🎒 {game.field_weight(telegram_id)}/{game.carry_capacity(p)} · ~{value} жет.\n\n☣️ Угроза: <b>{threat_label(p['threat'])}</b> ({p['threat']}/100)\n👣 Участков: {p['steps']}\n\n<i>Поиск может привести к добыче, бою или развилке.</i>"


def choice_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); scene_id = game.pending_scene(telegram_id)
    if not scene_id: return expedition_screen(game, telegram_id)
    scene = EXPEDITION_SCENES[scene_id]; hints = []
    if scene_id == "warehouse" and game.effective_attribute(p, "perception") >= 3: hints.append("👁 У входа заметна тонкая проволока. Там почти наверняка ловушка.")
    if scene_id == "basement" and game.effective_attribute(p, "intelligence") >= 3: hints.append("🧠 Скачки датчика повторяются — безопасный момент можно вычислить.")
    if scene_id == "gunfire" and game.effective_attribute(p, "perception") >= 3: hints.append("👁 По звуку стреляет один человек.")
    if scene_id == "gunfire" and game.effective_attribute(p, "agility") >= 4: hints.append("🏃 Слева есть быстрый путь во фланг.")
    hint_text = "\n".join(hints)
    if hint_text: hint_text = "\n\n" + hint_text
    return f"{scene['icon']} <b>{escape(scene['title']).upper()}</b>\n━━━━━━━━━━━━\n{_level_line(game, p)}{escape(scene['text'])}{hint_text}\n\n<i>Характеристики меняют шансы и доступную информацию.</i>"


def event_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); s = SECTORS[p["sector_id"]]
    per = game.effective_attribute(p, "perception"); intel = game.effective_attribute(p, "intelligence")
    if p["pending_event"] == "anomaly":
        chance = min(90, 36 + per * 6 + intel * 5 - s["danger"] * 4)
        return f"💠 <b>НЕСТАБИЛЬНЫЙ КОНТУР</b>\n━━━━━━━━━━━━\n{_level_line(game, p)}Попытаться снять образец или обойти.\n\nШанс успеха: <b>{chance}%</b>"
    chance = min(94, 48 + per * 6 + intel * 3 - s["danger"] * 4)
    return f"🧰 <b>ТЕХНИЧЕСКИЙ ЯЩИК</b>\n━━━━━━━━━━━━\n{_level_line(game, p)}Старый контейнер и подозрительная растяжка.\n\nШанс успеха: <b>{chance}%</b>"


def combat_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); enemy = ENEMIES[p["enemy_id"]]; weapon = WEAPONS[p["weapon_id"]]; c = game.combat_state(telegram_id)
    distance = {1: "вплотную", 2: "средняя", 3: "дальняя"}.get(c["distance"], str(c["distance"]))
    aim = " · 🎯 прицел" if p["aimed"] else ""; cover = " · 🧱 укрытие" if c["cover"] else ""; bleed = f"\n🩸 {c['bleeding']} HP/ход" if c["bleeding"] else ""
    return f"⚔️ <b>БОЙ · {escape(enemy['name']).upper()}</b>\n━━━━━━━━━━━━\n{_level_line(game, p)}❤️ {p['hp']}/{game.max_hp(p)}{bleed}\n☠️ {p['enemy_hp']} HP\n📏 {distance}{cover}\n\n🔫 {escape(weapon['name'])} · {p['ammo']} патр.{aim}\n🛡 Защита: {game.combat_damage_reduction(p)}\n\n<i>Ближний бой требует дистанции 1. Очередь тратит 3 патрона.</i>"


def _items(rows: list[dict]) -> list[str]:
    if not rows: return ["Пусто."]
    return [f"{ITEMS[r['item_id']]['icon']} {escape(ITEMS[r['item_id']]['name'])} ×{r['qty']}" for r in rows]


def inventory_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); lines = ["🎒 <b>ИНВЕНТАРЬ</b>", "━━━━━━━━━━━━"]
    if level_up_notice(game, p): lines.append(level_up_notice(game, p))
    if p["state"] == "expedition":
        lines += [f"🎒 Рюкзак {game.field_weight(telegram_id)}/{game.carry_capacity(p)}", ""] + _items(game.inventory(telegram_id, secured=0)) + ["", "<i>Добыча потеряется при смерти.</i>"]
    elif p["state"] == "travel":
        lines += [f"🚚 Груз {game.cargo_weight(telegram_id)}/{game.carry_capacity(p)}", ""] + _items(game.cargo(telegram_id)) + ["", "<i>Груз потеряется при смерти в дороге.</i>"]
    else:
        lines += [f"📦 Склад · {game.stash_value(telegram_id)} жет.", ""] + _items(game.inventory(telegram_id, secured=1)) + ["", f"🚚 Груз {game.cargo_weight(telegram_id)}/{game.carry_capacity(p)}", ""] + _items(game.cargo(telegram_id))
    return "\n".join(lines)


def character_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); eq = game.equipment(telegram_id)
    lines = ["🧬 <b>ПЕРСОНАЖ</b>", "━━━━━━━━━━━━"]
    if level_up_notice(game, p): lines.append(level_up_notice(game, p))
    lines += [f"Уровень: <b>{game.level(p)}</b> · ❤️ {game.max_hp(p)} HP", f"Опыт: {p['xp'] % XP_PER_LEVEL}/{XP_PER_LEVEL}", f"Свободных очков: <b>{game.attribute_points(p)}</b>", "", f"💪: <b>{p['strength']}</b> · 🏃: <b>{p['agility']}</b> · 👁: <b>{p['perception']}</b> · 🧠: <b>{p['intelligence']}</b>", "", f"🔫 {escape(WEAPONS[p['weapon_id']]['name'])}", f"🦺 {escape(ARMORS[p['armor_id']]['name'])}", f"🎒 {escape(BACKPACKS[eq['backpack_id']]['name'])}", f"🪖 {escape(HEADGEAR[eq['headgear_id']]['name'])}", f"📡 {escape(GADGETS[eq['gadget_id']]['name'])}"]
    return "\n".join(lines)


def shop_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); loc = game.location(telegram_id)
    return f"🏪 <b>ТОРГОВЕЦ · {escape(loc['name']).upper()}</b>\n━━━━━━━━━━━━\n{_level_line(game, p)}💰 {p['credits']} жет.\n📦 Склад: {game.stash_value(telegram_id)} жет.\n\nВыбери категорию. Торговые ресурсы находятся в «Рынке»."


def shop_weapons_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); loc = game.location(telegram_id); lines = ["🔫 <b>ТОРГОВЕЦ · ОРУЖИЕ</b>", "━━━━━━━━━━━━", f"💰 {p['credits']} · патроны ×6: {loc['ammo_price']}", f"Сейчас: {escape(WEAPONS[p['weapon_id']]['name'])}", ""]
    order = WEAPONS[p["weapon_id"]]["order"]
    for item in WEAPONS.values():
        if item["price"] and item["order"] > order:
            lines.append(f"{'🔒' if game.missing_requirements(p, item) else '•'} {escape(item['name'])} · {item['price']} · урон {item['damage']} · точн. {item['accuracy']}% · дальн. {item['range']}\n   Нужно: {requirements_text(item)}")
    return "\n".join(lines)


def _effect(item: dict) -> str:
    parts = []
    if item.get("reduction"): parts.append(f"защита +{item['reduction']}")
    if item.get("capacity"): parts.append(f"груз +{item['capacity']}")
    parts += [f"{ATTRIBUTES[k]['icon']} +{v}" for k, v in item.get("bonuses", {}).items()]
    return " · ".join(parts) or "без прямого бонуса"


def shop_equipment_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); eq = game.equipment(telegram_id); lines = ["🦺 <b>ТОРГОВЕЦ · ЭКИПИРОВКА</b>", "━━━━━━━━━━━━", f"💰 {p['credits']} жет.", ""]
    for title, catalog, current in [("Броня", ARMORS, p["armor_id"]), ("Рюкзаки", BACKPACKS, eq["backpack_id"]), ("Головные уборы", HEADGEAR, eq["headgear_id"]), ("Устройства", GADGETS, eq["gadget_id"])]:
        lines.append(f"<b>{title}</b>"); found = False
        for item in catalog.values():
            if item["price"] and item["order"] > catalog[current]["order"]:
                found = True; lines.append(f"{'🔒' if game.missing_requirements(p, item) else '•'} {escape(item['name'])} · {item['price']} · {_effect(item)}\n   Нужно: {requirements_text(item)}")
        if not found: lines.append("✓ Улучшений пока нет.")
        lines.append("")
    return "\n".join(lines).rstrip()


def shop_medicine_screen(game: GameService, telegram_id: int) -> str:
    p = game.get_player(telegram_id); price = game.location(telegram_id)["medkit_price"]
    return f"🩹 <b>ТОРГОВЕЦ · МЕДИЦИНА</b>\n━━━━━━━━━━━━\n💰 {p['credits']} жет. · 🩹 {p['medkits']} шт.\n\n🩹 <b>Аптечка</b> · {price} жет.\nЛечит и останавливает кровотечение. Интеллект повышает эффективность."


def rules_screen() -> str:
    return "ℹ️ <b>КАК ИГРАТЬ</b>\n━━━━━━━━━━━━\n1. Вылазки: добыча, риск, развилки и возврат.\n2. Между поселениями дороги по 10 участков.\n3. Цены рынков различаются; груз можно перевозить ради прибыли.\n4. Груз теряется при смерти в дороге, добыча — при смерти в вылазке.\n5. Слоты: оружие, броня, рюкзак, головной убор, устройство.\n6. В бою есть дистанция, укрытие, очередь и кровотечение.\n7. Каждый уровень: +20 HP и 1 очко характеристики. Верхнего лимита характеристик нет."
