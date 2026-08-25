from app.core.game import GameService, ROLE_NAMES
from app.game import GameService as LegacyGameService
from app.game import ROLE_NAMES as LegacyRoleNames


def test_game_legacy_module_is_a_thin_facade() -> None:
    assert LegacyGameService is GameService
    assert LegacyRoleNames is ROLE_NAMES
