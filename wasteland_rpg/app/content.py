from __future__ import annotations

GAME_TITLE = "КОНТУР"
BASE_NAME = "Приют-7"
XP_PER_LEVEL = 40

ATTRIBUTES = {
    "strength": {"name": "Сила", "icon": "💪"},
    "agility": {"name": "Ловкость", "icon": "🏃"},
    "perception": {"name": "Восприятие", "icon": "👁"},
    "intelligence": {"name": "Интеллект", "icon": "🧠"},
}

ITEMS = {
    "scrap": {"name": "Металлолом", "icon": "🔩", "weight": 1, "value": 8},
    "wire": {"name": "Проводка", "icon": "🧵", "weight": 1, "value": 14},
    "chem": {"name": "Реагенты", "icon": "🧪", "weight": 1, "value": 22},
    "parts": {"name": "Механизмы", "icon": "⚙️", "weight": 2, "value": 34},
    "shard": {"name": "Искажённый осколок", "icon": "💠", "weight": 1, "value": 120},
}

WEAPONS = {
    "pipe_pistol": {"name": "Самодельный пистолет", "damage": 17, "accuracy": 66, "range": 2, "modes": ("single", "aim"), "price": 0, "order": 0, "requirements": {}},
    "service_revolver": {"name": "Служебный револьвер", "damage": 23, "accuracy": 72, "range": 2, "modes": ("single", "aim"), "price": 180, "order": 1, "requirements": {"agility": 2}},
    "short_carbine": {"name": "Короткий карабин", "damage": 30, "accuracy": 78, "range": 3, "modes": ("single", "aim", "burst"), "price": 430, "order": 2, "requirements": {"strength": 2, "agility": 3}},
    "pump_shotgun": {"name": "Помповый дробовик", "damage": 41, "accuracy": 67, "range": 1, "modes": ("single", "aim"), "price": 690, "order": 3, "requirements": {"strength": 4, "agility": 2}},
}

ARMORS = {
    "old_coat": {"name": "Плотный плащ", "reduction": 0, "price": 0, "order": 0, "requirements": {}},
    "field_vest": {"name": "Полевой жилет", "reduction": 3, "price": 220, "order": 1, "requirements": {"agility": 2}},
    "composite": {"name": "Композитный нагрудник", "reduction": 6, "price": 520, "order": 2, "requirements": {"strength": 3, "agility": 3}},
    "heavy_shell": {"name": "Тяжёлый панцирь", "reduction": 10, "price": 920, "order": 3, "requirements": {"strength": 5}},
}

BACKPACKS = {
    "canvas_pack": {"name": "Холщовый рюкзак", "capacity": 0, "price": 0, "order": 0, "requirements": {}},
    "field_pack": {"name": "Полевой рюкзак", "capacity": 10, "price": 190, "order": 1, "requirements": {"strength": 2}},
    "military_pack": {"name": "Военный рюкзак", "capacity": 18, "price": 430, "order": 2, "requirements": {"strength": 4}},
}

HEADGEAR = {
    "cloth_hood": {"name": "Тканевый капюшон", "reduction": 0, "bonuses": {}, "price": 0, "order": 0, "requirements": {}},
    "scout_hood": {"name": "Капюшон разведчика", "reduction": 0, "bonuses": {"perception": 1}, "price": 240, "order": 1, "requirements": {"perception": 2}},
    "combat_helmet": {"name": "Боевой шлем", "reduction": 2, "bonuses": {}, "price": 480, "order": 2, "requirements": {"strength": 3}},
}

GADGETS = {
    "none": {"name": "Нет", "bonuses": {}, "price": 0, "order": 0, "requirements": {}},
    "field_scanner": {"name": "Полевой сканер", "bonuses": {"perception": 1, "intelligence": 1}, "price": 360, "order": 1, "requirements": {"intelligence": 2}},
    "contour_analyzer": {"name": "Анализатор контура", "bonuses": {"intelligence": 2}, "price": 720, "order": 2, "requirements": {"intelligence": 4, "perception": 3}},
}

LOCATIONS = {
    "refuge7": {"name": "Приют-7", "icon": "☢️", "description": "Старый защищённый узел у внешнего контура. Здесь всё знакомо и дорого.", "ammo_price": 24, "medkit_price": 32, "market": {"scrap": {"buy": 10, "sell": 8}, "wire": {"buy": 18, "sell": 14}, "chem": {"buy": 30, "sell": 22}, "parts": {"buy": 46, "sell": 34}}},
    "miners": {"name": "Шахтёрский", "icon": "⛏️", "description": "Посёлок вокруг старого карьера. Металла много, медикаментов мало.", "ammo_price": 27, "medkit_price": 38, "market": {"scrap": {"buy": 6, "sell": 5}, "wire": {"buy": 12, "sell": 10}, "chem": {"buy": 32, "sell": 24}, "parts": {"buy": 48, "sell": 36}}},
    "station": {"name": "Станция Северная", "icon": "🚉", "description": "Транспортный узел между поселениями. Здесь дешевле реагенты и механизмы.", "ammo_price": 21, "medkit_price": 29, "market": {"scrap": {"buy": 12, "sell": 9}, "wire": {"buy": 19, "sell": 15}, "chem": {"buy": 18, "sell": 15}, "parts": {"buy": 32, "sell": 27}}},
    "promgorod": {"name": "Промгород", "icon": "🏭", "description": "Крупный укреплённый город. Производству постоянно нужны металл и механизмы.", "ammo_price": 19, "medkit_price": 31, "market": {"scrap": {"buy": 19, "sell": 14}, "wire": {"buy": 26, "sell": 20}, "chem": {"buy": 28, "sell": 22}, "parts": {"buy": 58, "sell": 46}}},
}

ROUTES = {
    "refuge_miners": {"name": "Старая трасса", "a": "refuge7", "b": "miners", "danger": 1, "stages": 10, "level": 1},
    "miners_station": {"name": "Карьерная дорога", "a": "miners", "b": "station", "danger": 2, "stages": 10, "level": 2},
    "station_prom": {"name": "Чёрное шоссе", "a": "station", "b": "promgorod", "danger": 3, "stages": 10, "level": 4},
}

SECTORS = {
    # Приют-7 сохраняет все три исходные вылазки.
    "rust_belt": {
        "name": "Ржавый пояс", "icon": "🏚", "hub": "refuge7", "danger": 1,
        "runs": 0, "level": 1,
        "description": "Развалины у внешнего контура. Много лома, мало хороших причин расслабляться.",
        "loot": ["scrap", "scrap", "wire", "wire", "chem"],
        "enemies": ["bone_dog", "scavenger"],
    },
    "plant_12": {
        "name": "Промзона-12", "icon": "🏭", "hub": "refuge7", "danger": 2,
        "runs": 3, "level": 2,
        "description": "Цеха, склады и затопленные тоннели. Добыча дороже, встречи хуже.",
        "loot": ["wire", "chem", "chem", "parts", "parts"],
        "enemies": ["scavenger", "crawler", "raider"],
    },
    "black_contour": {
        "name": "Чёрный контур", "icon": "☣️", "hub": "refuge7", "danger": 3,
        "runs": 7, "level": 4,
        "description": "Место, где карты быстро устаревают. Редкие находки здесь действительно стоят риска.",
        "loot": ["chem", "parts", "parts", "parts", "shard"],
        "enemies": ["crawler", "raider", "stitched"],
    },

    # Шахтёрский.
    "quarry": {
        "name": "Старый карьер", "icon": "🪨", "hub": "miners", "danger": 1,
        "runs": 0, "level": 1,
        "description": "Открытая выработка с техникой под слоями пыли. Хорошее место для металла и деталей.",
        "loot": ["scrap", "scrap", "wire", "parts", "parts"],
        "enemies": ["bone_dog", "scavenger", "raider"],
    },
    "north_mine": {
        "name": "Шахта Север-4", "icon": "⛏️", "hub": "miners", "danger": 2,
        "runs": 2, "level": 2,
        "description": "Полузатопленные штреки, старые конвейеры и провалы в нижние горизонты. В глубине осталось много техники.",
        "loot": ["scrap", "wire", "wire", "parts", "parts", "chem"],
        "enemies": ["scavenger", "crawler", "raider"],
    },

    # Станция Северная.
    "freight_yard": {
        "name": "Грузовой терминал", "icon": "🚧", "hub": "station", "danger": 2,
        "runs": 0, "level": 2,
        "description": "Ряды контейнеров и разбитых платформ. Грузы давно разграблены, но самые тяжёлые ящики так и не увезли.",
        "loot": ["wire", "wire", "chem", "parts", "parts"],
        "enemies": ["scavenger", "raider", "crawler"],
    },
    "depot_6": {
        "name": "Депо-6", "icon": "🚂", "hub": "station", "danger": 3,
        "runs": 4, "level": 3,
        "description": "Тёмное ремонтное депо с техническими тоннелями. Здесь много полезных механизмов и слишком много слепых зон.",
        "loot": ["wire", "chem", "parts", "parts", "parts", "shard"],
        "enemies": ["crawler", "raider", "stitched"],
    },

    # Промгород.
    "foundry": {
        "name": "Литейный квартал", "icon": "🔥", "hub": "promgorod", "danger": 3,
        "runs": 0, "level": 4,
        "description": "Остывшие печи, шлаковые поля и полуразрушенные цеха. Металла здесь больше, чем безопасных маршрутов.",
        "loot": ["scrap", "parts", "parts", "parts", "chem"],
        "enemies": ["raider", "crawler", "stitched"],
    },
    "dead_substation": {
        "name": "Мёртвая подстанция", "icon": "⚡", "hub": "promgorod", "danger": 3,
        "runs": 8, "level": 5,
        "description": "Силовой узел, вокруг которого до сих пор гуляют нестабильные поля. Хорошее место для редких компонентов и плохое для ошибок.",
        "loot": ["wire", "chem", "chem", "parts", "shard"],
        "enemies": ["crawler", "raider", "stitched"],
    },
    "reactor_yard": {
        "name": "Реакторный двор", "icon": "☢️", "hub": "promgorod", "danger": 3,
        "runs": 11, "level": 6,
        "description": "Закрытая промышленная зона у старого энергоблока. Самые ценные находки лежат там, где долго не задерживаются даже опытные ходоки.",
        "loot": ["chem", "parts", "parts", "shard", "shard"],
        "enemies": ["raider", "stitched", "stitched", "crawler"],
    },
}

ENEMIES = {
    "bone_dog": {"name": "Костяной пёс", "hp": 34, "damage": (7, 12), "xp": 8, "loot": "scrap", "style": "melee", "start_distance": 2, "bleed": 0},
    "scavenger": {"name": "Падальщик", "hp": 42, "damage": (9, 14), "xp": 10, "loot": "wire", "style": "melee", "start_distance": 2, "bleed": 10},
    "crawler": {"name": "Шорох", "hp": 54, "damage": (11, 17), "xp": 13, "loot": "chem", "style": "melee", "start_distance": 3, "bleed": 25},
    "raider": {"name": "Мародёр", "hp": 62, "damage": (12, 18), "xp": 15, "loot": "parts", "style": "ranged", "start_distance": 3, "bleed": 0},
    "stitched": {"name": "Сшитый", "hp": 78, "damage": (15, 22), "xp": 20, "loot": "parts", "style": "melee", "start_distance": 3, "bleed": 35},
}

EXPEDITION_SCENES = {
    "warehouse": {"title": "Полуразрушенный склад", "icon": "🏚️", "text": "Впереди склад с приоткрытыми воротами. Внутри что-то осталось, но вход выглядит слишком удобным.", "options": {"careful": "👁 Осмотреть вход", "force": "💪 Войти напрямую", "bypass": "🚶 Обойти"}},
    "basement": {"title": "Подземный уровень", "icon": "🔦", "text": "Под плитой нашлась лестница вниз. Из шахты тянет холодом, а датчик ведёт себя нестабильно.", "options": {"scan": "🧠 Разобраться с датчиком", "descend": "🏃 Спуститься быстро", "bypass": "🚶 Не лезть"}},
    "gunfire": {"title": "Стрельба впереди", "icon": "💥", "text": "За развалинами короткая перестрелка. Можно подождать, зайти сбоку или уйти, пока тебя не заметили.", "options": {"observe": "👁 Наблюдать", "ambush": "🏃 Зайти сбоку", "bypass": "🚶 Уйти"}},
}

START_INTRO = (
    "После Срыва старые промышленные районы стали нестабильными. "
    "Посёлки вокруг внешнего контура живут торговлей, вылазками и дорогами между безопасными узлами.\n\n"
    "Правило простое: чем дальше заходишь, тем ценнее находки и тем выше шанс не вернуться. "
    "Добыча становится безопасной после возвращения в поселение, а торговый груз особенно уязвим в дороге."
)
