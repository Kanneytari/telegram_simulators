from __future__ import annotations

import random
from pathlib import Path

import pytest

from app.db import Database
from app.game import GameError, GameService


@pytest.fixture()
def game(tmp_path: Path) -> GameService:
    db = Database(tmp_path / "test.db")
    db.init()
    service = GameService(db, random.Random(7))
    service.ensure_player(1, "tester")
    return service


def test_player_starts_at_base(game: GameService) -> None:
    player = game.get_player(1)
    assert player["state"] == "base"
    assert player["combat"] == 1
    assert player["scavenging"] == 1
    assert player["survival"] == 1
    assert player["ammo"] == 12


def test_return_secures_field_loot(game: GameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        conn.execute("INSERT INTO inventory VALUES (1, 'scrap', 0, 3)")
    result = game.return_base(1)
    assert result["value"] == 24
    assert game.inventory(1, secured=0) == []
    assert game.inventory(1, secured=1)[0]["qty"] == 3
    assert game.get_player(1)["successful_runs"] == 1


def test_death_drops_only_field_loot(game: GameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        conn.execute("INSERT INTO inventory VALUES (1, 'scrap', 0, 2)")
        conn.execute("INSERT INTO inventory VALUES (1, 'wire', 1, 4)")
        conn.execute(
            "UPDATE players SET state='combat', enemy_id='stitched', enemy_hp=78, hp=1 WHERE telegram_id=1"
        )
    game.rng = random.Random(1)
    game.combat_action(1, "aim")
    assert game.get_player(1)["state"] == "base"
    assert game.inventory(1, secured=0) == []
    assert game.inventory(1, secured=1)[0]["qty"] == 4


def test_skill_points_come_from_experience(game: GameService) -> None:
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 40 WHERE telegram_id = 1")
    assert game.skill_points(game.get_player(1)) == 1
    game.upgrade_skill(1, "combat")
    assert game.get_player(1)["combat"] == 2
    assert game.skill_points(game.get_player(1)) == 0


def test_locked_sector_requires_progress(game: GameService) -> None:
    with pytest.raises(GameError):
        game.start_expedition(1, "plant_12")
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET successful_runs = 3 WHERE telegram_id = 1")
    game.start_expedition(1, "plant_12")
    assert game.get_player(1)["sector_id"] == "plant_12"


def test_sell_stash(game: GameService) -> None:
    with game.db.connect() as conn:
        conn.execute("INSERT INTO inventory VALUES (1, 'parts', 1, 2)")
    before = game.get_player(1)["credits"]
    game.sell_all(1)
    assert game.get_player(1)["credits"] == before + 68
    assert game.inventory(1, secured=1) == []
