from __future__ import annotations

PLAYER_ACTION_SECONDS = {
    "shoot": 5.0,
    "aimed_shot": 8.0,
    "burst": 8.0,
    "melee": 2.0,
    "cover": 3.0,
    "stim": 2.0,
    "medkit": 6.0,
    "flee": 5.0,
}

PLAYER_ACTION_LABELS = {
    "shoot": "🔫 Выстрел",
    "aimed_shot": "🎯 Прицельный выстрел",
    "burst": "💥 Очередь",
    "melee": "🔪 Ближний бой",
    "cover": "🧱 Занять укрытие",
    "stim": "💉 Вколоть стимулятор",
    "medkit": "🩹 Аптечка",
    "flee": "🏃 Отступить",
}

ENEMY_ACTION_SECONDS = {
    "approach": 4.0,
    "retreat": 4.0,
    "melee_attack": 5.5,
    "ranged_attack": 7.0,
}

COMBAT_LOG_SIZE = 7
STIM_DURATION_SECONDS = 8.0
STIM_HEAL_PER_SECOND = 3
OPPORTUNITY_DURATION_SECONDS = 7.0
OPPORTUNITY_COOLDOWN_SECONDS = 12.0
OPPORTUNITY_CHANCE = 0.22
