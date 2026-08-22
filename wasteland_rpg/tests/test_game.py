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


def test_player_starts_with_four_attributes_at_one(game: GameService) -> None:
    player = game.get_player(1)
    assert player["strength"] == 1
    assert player["agility"] == 1
    assert player["perception"] == 1
    assert player["intelligence"] == 1
    assert game.level(player) == 1
    assert game.max_hp(player) == 40
    assert player["hp"] == 40
    assert game.attribute_points(player) == 0


def test_schema_has_no_legacy_attributes(game: GameService) -> None:
    with game.db.connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(players)")}
    assert "endurance" not in columns
    assert "combat" not in columns
    assert "scavenging" not in columns
    assert "survival" not in columns


def test_level_grants_hp_and_one_attribute_point(game: GameService) -> None:
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 40 WHERE telegram_id = 1")
    player = game.get_player(1)
    assert game.level(player) == 2
    assert game.max_hp(player) == 60
    assert game.attribute_points(player) == 1


def test_level_up_immediately_adds_twenty_hp_in_field(game: GameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 39, hp = 15 WHERE telegram_id = 1")
        game._add_xp(conn, 1, 1)
    player = game.get_player(1)
    assert game.level(player) == 2
    assert game.max_hp(player) == 60
    assert player["hp"] == 35


def test_attribute_point_can_be_spent_only_once(game: GameService) -> None:
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 40 WHERE telegram_id = 1")
    game.upgrade_attribute(1, "intelligence")
    player = game.get_player(1)
    assert player["intelligence"] == 2
    assert game.attribute_points(player) == 0
    with pytest.raises(GameError):
        game.upgrade_attribute(1, "strength")


def test_agility_controls_damage_resistance(game: GameService) -> None:
    player = game.get_player(1)
    assert game.agility_resistance(player) == 0
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET agility = 4 WHERE telegram_id = 1")
    player = game.get_player(1)
    assert game.agility_resistance(player) == 3
    assert game.combat_damage_reduction(player) == 3


def test_armor_and_agility_stack_for_damage_reduction(game: GameService) -> None:
    with game.db.connect() as conn:
        conn.execute(
            "UPDATE players SET agility = 3, armor_id = 'field_vest' WHERE telegram_id = 1"
        )
    assert game.combat_damage_reduction(game.get_player(1)) == 5


def test_equipment_requirement_blocks_purchase(game: GameService) -> None:
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET credits = 1000 WHERE telegram_id = 1")
    with pytest.raises(GameError, match="Ловкость 2"):
        game.buy(1, "service_revolver")
    assert game.get_player(1)["weapon_id"] == "pipe_pistol"
    assert game.get_player(1)["credits"] == 1000


def test_equipment_can_be_bought_after_requirement_is_met(game: GameService) -> None:
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET agility = 2, credits = 1000 WHERE telegram_id = 1")
    game.buy(1, "service_revolver")
    player = game.get_player(1)
    assert player["weapon_id"] == "service_revolver"
    assert player["credits"] == 820


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
            "UPDATE players SET state='combat', enemy_id='stitched', enemy_hp=78, hp=1 "
            "WHERE telegram_id=1"
        )
    game.rng = random.Random(1)
    game.combat_action(1, "aim")
    assert game.get_player(1)["state"] == "base"
    assert game.inventory(1, secured=0) == []
    assert game.inventory(1, secured=1)[0]["qty"] == 4


def test_locked_sector_requires_progress(game: GameService) -> None:
    with pytest.raises(GameError):
        game.start_expedition(1, "plant_12")
    with game.db.connect() as conn:
        conn.execute(
            "UPDATE players SET successful_runs = 3, xp = 40 WHERE telegram_id = 1"
        )
    game.start_expedition(1, "plant_12")
    assert game.get_player(1)["sector_id"] == "plant_12"


def test_sell_stash(game: GameService) -> None:
    with game.db.connect() as conn:
        conn.execute("INSERT INTO inventory VALUES (1, 'parts', 1, 2)")
    before = game.get_player(1)["credits"]
    game.sell_all(1)
    assert game.get_player(1)["credits"] == before + 68
    assert game.inventory(1, secured=1) == []
