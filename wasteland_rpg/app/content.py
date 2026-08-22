from __future__ import annotations

GAME_TITLE = "КОНТУР"
BASE_NAME = "Приют-7"
MAX_SKILL = 10  # legacy internal scale; player-facing progression uses ATTRIBUTES
XP_PER_SKILL_POINT = 40  # retained for compatibility with the base game service
XP_PER_LEVEL = 40
MAX_ATTRIBUTE = 10

ATTRIBUTES = {
    "strength": {"name": "Сила", "icon": "💪"},
    "agility": {"name": "Ловкость", "icon": "⚡"},
    "perception": {"name": "Восприятие", "icon": "👁"},
    "endurance": {"name": "Выносливость", "icon": "🛡"},
}

ITEMS = {
    "scrap": {"name": "Металлолом", "icon": "🔩", "weight": 1, "value": 8},
    "wire": {"name": "Проводка", "icon": "🧵", "weight": 1, "value": 14},
    "chem": {"name": "Реагенты", "icon": "🧪", "weight": 1, "value": 22},
    "parts": {"name": "Механизмы", "icon": "⚙️", "weight": 2, "value": 34},
    "shard": {"name": "Искажённый осколок", "icon": "💠", "weight": 1, "value": 120},
}

WEAPONS = {
    "pipe_pistol": {
        "name": "Самодельный пистолет", "damage": 17, "accuracy": 66,
        "price": 0, "order": 0, "requirements": {},
    },
    "service_revolver": {
        "name": "Служебный револьвер", "damage": 23, "accuracy": 72,
        "price": 180, "order": 1, "requirements": {"agility": 2},
    },
    "short_carbine": {
        "name": "Короткий карабин", "damage": 30, "accuracy": 78,
        "price": 430, "order": 2, "requirements": {"strength": 2, "agility": 3},
    },
}

ARMORS = {
    "old_coat": {
        "name": "Плотный плащ", "reduction": 0, "price": 0, "order": 0,
        "requirements": {},
    },
    "field_vest": {
        "name": "Полевой жилет", "reduction": 3, "price": 220, "order": 1,
        "requirements": {"endurance": 2},
    },
    "composite": {
        "name": "Композитный нагрудник", "reduction": 6, "price": 520, "order": 2,
        "requirements": {"strength": 3, "endurance": 3},
    },
}

SECTORS = {
    "rust_belt": {
        "name": "Ржавый пояс", "icon": "🏚", "danger": 1,
        "runs": 0, "survival": 0, "level": 1,
        "description": "Развалины у внешнего контура. Много лома, мало хороших причин расслабляться.",
        "loot": ["scrap", "scrap", "wire", "wire", "chem"],
        "enemies": ["bone_dog", "scavenger"],
    },
    "plant_12": {
        "name": "Промзона-12", "icon": "🏭", "danger": 2,
        "runs": 3, "survival": 1, "level": 2,
        "description": "Цеха, склады и затопленные тоннели. Добыча дороже, встречи хуже.",
        "loot": ["wire", "chem", "chem", "parts", "parts"],
        "enemies": ["scavenger", "crawler", "raider"],
    },
    "black_contour": {
        "name": "Чёрный контур", "icon": "☣️", "danger": 3,
        "runs": 7, "survival": 2, "level": 4,
        "description": "Место, где карты быстро устаревают. Редкие находки здесь действительно стоят риска.",
        "loot": ["chem", "parts", "parts", "parts", "shard"],
        "enemies": ["crawler", "raider", "stitched"],
    },
}

ENEMIES = {
    "bone_dog": {"name": "Костяной пёс", "hp": 34, "damage": (7, 12), "xp": 8, "loot": "scrap"},
    "scavenger": {"name": "Падальщик", "hp": 42, "damage": (9, 14), "xp": 10, "loot": "wire"},
    "crawler": {"name": "Шорох", "hp": 54, "damage": (11, 17), "xp": 13, "loot": "chem"},
    "raider": {"name": "Мародёр", "hp": 62, "damage": (12, 18), "xp": 15, "loot": "parts"},
    "stitched": {"name": "Сшитый", "hp": 78, "damage": (15, 22), "xp": 20, "loot": "parts"},
}

START_INTRO = (
    "После Срыва старые промышленные районы стали нестабильными. "
    "Посёлки вокруг внешнего контура живут тем, что ходоки выносят из руин.\n\n"
    "Правило простое: чем дальше заходишь, тем ценнее находки и тем выше шанс не вернуться. "
    "Добыча становится безопасной только после возвращения в Приют-7."
)
