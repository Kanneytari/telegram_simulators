from __future__ import annotations


BASE_LEVEL_XP = 40
XP_GROWTH_FACTOR = 1.35
XP_ROUNDING = 5


def xp_required_for_next(level: int) -> int:
    """XP needed to advance from `level` to `level + 1`.

    The same exponential formula is used at every level. Each next level costs
    about 35% more XP than the previous one, rounded to a convenient 5 XP.
    """
    level = max(1, int(level))
    raw = BASE_LEVEL_XP * (XP_GROWTH_FACTOR ** (level - 1))
    return max(XP_ROUNDING, int(round(raw / XP_ROUNDING)) * XP_ROUNDING)


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
