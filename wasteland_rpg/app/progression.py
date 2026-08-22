from __future__ import annotations


EARLY_LEVEL_XP = 40
GROWTH_START_LEVEL = 6


def xp_required_for_next(level: int) -> int:
    """XP needed to advance from `level` to `level + 1`.

    Levels 1-6 keep the original onboarding pace. Starting with the transition
    from level 6 to 7, the requirement grows progressively so stronger players
    do not gain a level from nearly every long expedition.
    """
    level = max(1, int(level))
    if level < GROWTH_START_LEVEL:
        return EARLY_LEVEL_XP

    step = level - (GROWTH_START_LEVEL - 1)
    return EARLY_LEVEL_XP + 15 * step + 5 * step * step


def total_xp_for_level(level: int) -> int:
    """Total accumulated XP required to reach `level`."""
    level = max(1, int(level))
    return sum(xp_required_for_next(current) for current in range(1, level))


def level_from_xp(xp: int) -> int:
    """Resolve character level from accumulated XP with no upper cap."""
    remaining = max(0, int(xp))
    level = 1
    while True:
        required = xp_required_for_next(level)
        if remaining < required:
            return level
        remaining -= required
        level += 1


def progress_from_xp(xp: int) -> tuple[int, int]:
    """Return XP earned inside the current level and XP needed for the next."""
    xp = max(0, int(xp))
    level = level_from_xp(xp)
    start = total_xp_for_level(level)
    return xp - start, xp_required_for_next(level)
