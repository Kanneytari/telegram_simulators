from __future__ import annotations

PLAYER_ACTION_SECONDS = {
    "shoot": 4.5,
    "aimed_shot": 7.5,
    "burst": 7.5,
    "melee": 3.0,
    "cover": 3.0,
    "stim": 1.5,
    "medkit": 6.0,
    "flee": 7.5,
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
    "approach": 3.0,
    "retreat": 3.0,
    "melee_attack": 4.5,
    "ranged_attack": 6.0,
}

COMBAT_LOG_SIZE = 7
STIM_DURATION_SECONDS = 8.0
STIM_HEAL_PER_SECOND = 3
OPPORTUNITY_DURATION_SECONDS = 10.5
OPPORTUNITY_COOLDOWN_SECONDS = 12.0
OPPORTUNITY_CHANCE = 0.22
