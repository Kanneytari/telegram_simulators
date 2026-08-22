from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .content import ARMORS, ATTRIBUTES, BACKPACKS, EXPEDITION_SCENES, GADGETS, HEADGEAR, ITEMS, LOCATIONS, ROUTES, WEAPONS
from .game import GameService


def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows])


def home() -> InlineKeyboardMarkup:
    return _kb([[('🧭 Вылазка', 'menu:sectors'), ('🗺 Карта', 'menu:map')], [('🎒 Инвентарь', 'menu:inventory'), ('📈 Рынок', 'menu:market')], [('🧬 Персонаж', 'menu:character'), ('🏪 Торговец', 'menu:shop')], [('ℹ️ Как играть', 'menu:rules')]])


def back_home() -> InlineKeyboardMarkup:
    return _kb([[('◀️ Меню', 'menu:home')]])


def reset_confirm() -> InlineKeyboardMarkup:
    return _kb([[('🗑 Да, сбросить всё', 'reset:confirm')], [('Отмена', 'reset:cancel')]])


def map_routes(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    rows = []
    for route in game.connected_routes(telegram_id):
        target = LOCATIONS[route['target']]
        lock = '🔒 ' if not route['unlocked'] else ''
        rows.append([(f"{lock}{target['icon']} {target['name']}", f"route:{route['id']}")])
    rows.append([('◀️ Меню', 'menu:home')])
    return _kb(rows)


def travel(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    state = game.travel_state(telegram_id)
    if not state:
        return home()
    route = ROUTES[state['route_id']]
    main_button = ('🏁 Войти в поселение', 'road:advance') if int(state['step']) >= int(route['stages']) else ('👣 Следующий участок', 'road:advance')
    return _kb([[main_button], [('🚚 Груз', 'road:cargo')]])


def travel_inventory() -> InlineKeyboardMarkup:
    return _kb([[('◀️ К дороге', 'road:back')]])


def sectors(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    player = game.get_player(telegram_id)
    rows = [[(f"{sector['icon']} {sector['name']}", f"sector:{sector_id}")] for sector_id, sector in game.local_sectors(telegram_id) if game.sector_unlocked(player, sector_id)]
    rows.append([('◀️ Меню', 'menu:home')])
    return _kb(rows)


def expedition() -> InlineKeyboardMarkup:
    return _kb([[('🔎 Искать путь и добычу', 'expedition:explore')], [('🎒 Рюкзак', 'expedition:inventory'), ('↩️ Вернуться', 'expedition:return')]])


def event() -> InlineKeyboardMarkup:
    return _kb([[('⚠️ Рискнуть', 'event:try'), ('🚶 Обойти', 'event:bypass')], [('🎒 Рюкзак', 'expedition:inventory')]])


def choice(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    scene_id = game.pending_scene(telegram_id)
    if not scene_id:
        return expedition()
    rows = [[(label, f"choice:{action}")] for action, label in EXPEDITION_SCENES[scene_id]['options'].items()]
    rows.append([('🎒 Рюкзак', 'expedition:inventory')])
    return _kb(rows)


def combat(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    weapon = WEAPONS[game.get_player(telegram_id)['weapon_id']]
    rows = [[('🔫 Выстрел', 'combat:shoot'), ('🎯 Прицелиться', 'combat:aim')]]
    if 'burst' in weapon.get('modes', ()):
        rows.append([('💥 Очередь ×3', 'combat:burst')])
    rows += [[('➡️ Сблизиться', 'combat:approach'), ('🔪 Ближний бой', 'combat:melee')], [('🧱 В укрытие', 'combat:cover'), ('🩹 Аптечка', 'combat:medkit')], [('🏃 Отступить', 'combat:flee')]]
    return _kb(rows)


def character(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    player = game.get_player(telegram_id)
    rows = []
    if game.attribute_points(player) > 0:
        buttons = [(f"⬆️ {meta['icon']}", f"attribute:{key}") for key, meta in ATTRIBUTES.items()]
        rows.extend([buttons[:2], buttons[2:]])
    rows.append([('◀️ Меню', 'menu:home')])
    return _kb(rows)


def market(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    buy_buttons = [(f"{ITEMS[item_id]['icon']} +1 · {price['buy']}", f"market:buy:{item_id}") for item_id, price in game.location(telegram_id)['market'].items()]
    return _kb([buy_buttons[:2], buy_buttons[2:], [('💰 Продать груз', 'market:sell_cargo')], [('📦 Склад → груз', 'market:load'), ('🚚 Груз → склад', 'market:unload')], [('◀️ Меню', 'menu:home')]])


def shop() -> InlineKeyboardMarkup:
    return _kb([[('🔫 Оружие', 'shopcat:weapons'), ('🦺 Экипировка', 'shopcat:equipment')], [('🩹 Медицина', 'shopcat:medicine')], [('💰 Продать весь склад', 'shop:sell')], [('◀️ Меню', 'menu:home')]])


def _shop_navigation() -> list[list[tuple[str, str]]]:
    return [[('🔫 Оружие', 'shopcat:weapons'), ('🦺 Экипировка', 'shopcat:equipment')], [('🩹 Медицина', 'shopcat:medicine'), ('◀️ Торговец', 'menu:shop')]]


def shop_weapons(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    player = game.get_player(telegram_id)
    rows = [[(f"🔫 Патроны ×6 · {game.location(telegram_id)['ammo_price']}", 'shopbuy:weapons:ammo')]]
    current_order = WEAPONS[player['weapon_id']]['order']
    for item_id, item in WEAPONS.items():
        if item['price'] and item['order'] > current_order:
            lock = '🔒 ' if game.missing_requirements(player, item) else ''
            rows.append([(f"{lock}🔫 {item['name']} · {item['price']}", f"shopbuy:weapons:{item_id}")])
    rows.extend(_shop_navigation())
    return _kb(rows)


def shop_equipment(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    player = game.get_player(telegram_id)
    eq = game.equipment(telegram_id)
    rows = []
    for catalog, current_id, icon in [(ARMORS, player['armor_id'], '🦺'), (BACKPACKS, eq['backpack_id'], '🎒'), (HEADGEAR, eq['headgear_id'], '🪖'), (GADGETS, eq['gadget_id'], '📡')]:
        current_order = catalog[current_id]['order']
        for item_id, item in catalog.items():
            if item['price'] and item['order'] > current_order:
                lock = '🔒 ' if game.missing_requirements(player, item) else ''
                rows.append([(f"{lock}{icon} {item['name']} · {item['price']}", f"shopbuy:equipment:{item_id}")])
    rows.extend(_shop_navigation())
    return _kb(rows)


def shop_medicine(game: GameService, telegram_id: int) -> InlineKeyboardMarkup:
    return _kb([[(f"🩹 Аптечка · {game.location(telegram_id)['medkit_price']}", 'shopbuy:medicine:medkit')], *_shop_navigation()])


def expedition_inventory() -> InlineKeyboardMarkup:
    return _kb([[('◀️ Назад', 'expedition:back')]])
