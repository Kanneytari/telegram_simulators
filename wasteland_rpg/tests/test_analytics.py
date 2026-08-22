from __future__ import annotations

import json
import random
from pathlib import Path

from app.db import Database
from app.service import ANALYTICS_GAME_VERSION, GameService


def make_game(tmp_path: Path) -> GameService:
    db = Database(tmp_path / "analytics.db")
    db.init()
    game = GameService(db, random.Random(7))
    game.ensure_player(1, "tester")
    return game


def events(game: GameService, name: str | None = None) -> list[dict]:
    rows = game.analytics_events(1)
    return [row for row in rows if name is None or row["event_name"] == name]


def test_new_player_is_logged_without_username_in_metadata(tmp_path: Path) -> None:
    game = make_game(tmp_path)

    created = events(game, "player_created")
    assert len(created) == 1
    assert created[0]["game_version"] == ANALYTICS_GAME_VERSION

    metadata = json.loads(created[0]["metadata"])
    assert "username" not in metadata
    assert metadata["state"] == "base"
    assert metadata["level"] == 1


def test_expedition_events_share_one_run_id(tmp_path: Path) -> None:
    game = make_game(tmp_path)

    game.start_expedition(1, "rust_belt")
    game.return_base(1)

    started = events(game, "expedition_started")[-1]
    returned = events(game, "expedition_returned")[-1]
    assert started["run_id"]
    assert started["run_id"].startswith("expedition:")
    assert returned["run_id"] == started["run_id"]


def test_combat_action_is_logged_with_action_and_snapshot(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        game._start_combat(conn, 1, "bone_dog", return_state="expedition")

    game.combat_action(1, "shoot")

    action = events(game, "combat_action")[-1]
    assert action["entity_id"] == "shoot"
    assert action["context"] == "combat"
    metadata = json.loads(action["metadata"])
    assert metadata["enemy_id"] == "bone_dog"
    assert metadata["ammo_after"] == metadata["ammo_before"] - 1


def test_analytics_survive_character_reset(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    before = len(events(game))

    game.db.reset_player(1)
    assert len(game.analytics_events(1)) == before

    game.ensure_player(1, "tester")
    recreated = events(game, "character_recreated")
    assert len(recreated) == 1
