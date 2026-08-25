from __future__ import annotations

ATTRIBUTES = {
    "strength": {"name": "Сила", "icon": "💪"},
    "agility": {"name": "Ловкость", "icon": "🏃"},
    "perception": {"name": "Восприятие", "icon": "👁"},
    "intelligence": {"name": "Интеллект", "icon": "🧠"},
}

RESOURCES = {
    "food": {"name": "Еда", "icon": "🥫"},
    "water": {"name": "Вода", "icon": "💧"},
    "scrap": {"name": "Металлолом", "icon": "🔩"},
    "wire": {"name": "Проводка", "icon": "🧵"},
    "chem": {"name": "Реагенты", "icon": "🧪"},
    "parts": {"name": "Механизмы", "icon": "⚙️"},
    "medicine": {"name": "Медицина", "icon": "🩹"},
    "ammo": {"name": "Боеприпасы", "icon": "📦"},
    "shard": {"name": "Искажённый осколок", "icon": "💠"},
}

SECTORS = {
    "rust_belt": {
        "name": "Ржавый пояс",
        "icon": "🏚",
        "danger": 1,
        "duration_minutes": 20,
        "requires_mastery": None,
        "supplies_per_resident": {"food": 1, "water": 2, "ammo": 1},
        "loot": {
            "food": (3, 8),
            "water": (2, 6),
            "scrap": (8, 18),
            "wire": (1, 5),
            "medicine": (0, 2),
        },
    },
    "plant_12": {
        "name": "Промзона-12",
        "icon": "🏭",
        "danger": 2,
        "duration_minutes": 45,
        "requires_mastery": "rust_belt",
        "supplies_per_resident": {"food": 2, "water": 3, "ammo": 2},
        "loot": {
            "food": (2, 6),
            "scrap": (5, 13),
            "wire": (3, 8),
            "chem": (2, 7),
            "parts": (1, 5),
            "medicine": (0, 3),
        },
    },
    "black_contour": {
        "name": "Чёрный контур",
        "icon": "☣️",
        "danger": 3,
        "duration_minutes": 90,
        "requires_mastery": "plant_12",
        "supplies_per_resident": {"food": 3, "water": 4, "ammo": 3},
        "loot": {
            "chem": (4, 10),
            "parts": (3, 8),
            "medicine": (1, 5),
            "shard": (0, 2),
        },
    },
}

BUILDINGS = {
    "water_collector": {
        "name": "Водосборник",
        "icon": "💧",
        "max_level": 4,
        "base_duration_minutes": 35,
        "base_cost": {"scrap": 10, "parts": 2},
        "effect": "+8 воды в сутки за уровень",
    },
    "greenhouse": {
        "name": "Теплица",
        "icon": "🌱",
        "max_level": 4,
        "base_duration_minutes": 45,
        "base_cost": {"scrap": 12, "parts": 2},
        "effect": "+6 еды в сутки за уровень",
    },
    "infirmary": {
        "name": "Медпункт",
        "icon": "🩹",
        "max_level": 3,
        "base_duration_minutes": 60,
        "base_cost": {"scrap": 14, "parts": 3, "chem": 2},
        "effect": "+15 HP восстановления в сутки за уровень",
    },
    "training_ground": {
        "name": "Тренировочный двор",
        "icon": "🎯",
        "max_level": 3,
        "base_duration_minutes": 55,
        "base_cost": {"scrap": 16, "parts": 3},
        "effect": "сокращает обучение жителей",
    },
    "watchtower": {
        "name": "Наблюдательная вышка",
        "icon": "🔭",
        "max_level": 3,
        "base_duration_minutes": 70,
        "base_cost": {"scrap": 18, "parts": 4, "wire": 3},
        "effect": "+3% к успеху вылазок за уровень",
    },
}

INITIAL_RESIDENTS = (
    {"id": "rook", "name": "Грач", "strength": 3, "agility": 3, "perception": 4, "intelligence": 2},
    {"id": "mole", "name": "Крот", "strength": 4, "agility": 2, "perception": 3, "intelligence": 2},
    {"id": "spark", "name": "Искра", "strength": 2, "agility": 3, "perception": 2, "intelligence": 4},
    {"id": "fox", "name": "Лис", "strength": 2, "agility": 4, "perception": 4, "intelligence": 2},
    {"id": "marta", "name": "Марта", "strength": 2, "agility": 2, "perception": 3, "intelligence": 4},
    {"id": "scar", "name": "Шрам", "strength": 4, "agility": 3, "perception": 2, "intelligence": 2},
)
