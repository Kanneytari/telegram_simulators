from __future__ import annotations

from .gameplay import GameService as GameplayService
from .progression import level_from_xp, progress_from_xp, xp_required_for_next


class GameService(GameplayService):
    """Runtime game service with the current progression curve."""

    def level(self, player) -> int:
        return level_from_xp(int(player["xp"]))

    def xp_progress(self, player) -> tuple[int, int]:
        return progress_from_xp(int(player["xp"]))

    def xp_needed_for_next_level(self, player) -> int:
        return xp_required_for_next(self.level(player))
