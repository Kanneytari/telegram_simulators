from __future__ import annotations

import random
from pathlib import Path

import pytest

from app.combat_view import combat_keyboard
from app.db import Database
from app.event_pools import EXPEDITION_EVENTS, ROAD_EVENTS
from app.game import GameError
from app.gameplay import GameService


@pytest.fixture()
def game(tmp_path: Path) -> GameService:
    db = Database(tmp_path / "gameplay.db")
    db.init()
    service = GameService(db, random.Random(7))
    service.ensure_player(1, "tester")
    return service


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_rotating_event_cannot_repeat_on_next_step(game: GameService) -> None:
    pool = {
        "common": {"base": 20, "recovery": 10},
        "rare": {"base": 5, "recovery": 1},
    }
    with game.db.connect() as conn:
        first = game._pick_rotating_event(conn, 1, "test", pool)
    weights_after_first = game.event_weights(1, "test")
    assert weights_after_first[first] == 0

    with game.db.connect() as conn:
        second = game._pick_rotating_event(conn, 1, "test", pool)
    assert second != first

    weights_after_second = game.event_weights(1, "test")
    assert weights_after_second[first] == pool[first]["recovery"]
    assert weights_after_second[second] == 0


def test_common_events_recover_faster_than_rare_events() -> None:
    assert EXPEDITION_EVENTS["loot"]["base"] > EXPEDITION_EVENTS["anomaly"]["base"]
    assert EXPEDITION_EVENTS["loot"]["recovery"] > EXPEDITION_EVENTS["anomaly"]["recovery"]
    assert ROAD_EVENTS["quiet"]["base"] > ROAD_EVENTS["supply_cache"]["base"]
    assert ROAD_EVENTS["quiet"]["recovery"] > ROAD_EVENTS["supply_cache"]["recovery"]


def test_starting_new_expedition_resets_event_rotation(game: GameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        game._pick_rotating_event(conn, 1, "expedition", EXPEDITION_EVENTS)
    assert any(weight == 0 for weight in game.event_weights(1, "expedition").values())

    game.return_base(1)
    game.start_expedition(1, "rust_belt")
    assert game.event_weights(1, "expedition") == {}


def test_melee_button_appears_only_after_enemy_closes(game: GameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        game._start_combat(conn, 1, "bone_dog", return_state="expedition")

    before = _button_texts(combat_keyboard(game, 1))
    assert "🔪 Ближний бой" not in before
    assert all("Прицел" not in text for text in before)
    assert all("Сблиз" not in text for text in before)

    game.combat_action(1, "shoot")
    assert game.combat_state(1)["distance"] == 1
    after = _button_texts(combat_keyboard(game, 1))
    assert "🔪 Ближний бой" in after


def test_manual_aim_and_approach_are_disabled(game: GameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        game._start_combat(conn, 1, "bone_dog", return_state="expedition")

    with pytest.raises(GameError, match="больше не используется"):
        game.combat_action(1, "aim")
    with pytest.raises(GameError, match="больше не используется"):
        game.combat_action(1, "approach")
