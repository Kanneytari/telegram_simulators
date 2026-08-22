from __future__ import annotations


# base — максимальный вес события в свежей вылазке/дороге.
# recovery — сколько веса возвращается после каждого следующего шага,
# на котором событие не произошло. Только что выпавшее событие получает вес 0.
EXPEDITION_EVENTS = {
    "loot": {"base": 34, "recovery": 16},
    "enemy": {"base": 26, "recovery": 12},
    "quiet": {"base": 12, "recovery": 12},
    "cache": {"base": 12, "recovery": 5},
    "scene:warehouse": {"base": 10, "recovery": 4},
    "scene:gunfire": {"base": 8, "recovery": 3},
    "scene:basement": {"base": 7, "recovery": 3},
    "anomaly": {"base": 5, "recovery": 2},
}


ROAD_EVENTS = {
    "quiet": {"base": 32, "recovery": 18},
    "loot": {"base": 26, "recovery": 14},
    "enemy": {"base": 24, "recovery": 11},
    "wreck": {"base": 10, "recovery": 4},
    "supply_cache": {"base": 5, "recovery": 2},
}
