from __future__ import annotations

import random
from pathlib import Path

import pytest

from app.db import Database
from app.game import GameError
from app.progression import ProgressionGameService


@pytest.fixture()
def game(tmp_path: Path) -> ProgressionGameService:
    db = Database(tmp_path / "test.db")
    db.init()
    service = ProgressionGameService(db, random.Random(7))
    service.ensure_player(1, "tester")
    return service


def test_player_starts_with_four_attributes_at_one(game: ProgressionGameService) -> None:
    player = game.get_player(1)
    assert player["state"] == "base"
    assert player["strength"] == 1
    assert player["agility"] == 1
    assert player["perception"] == 1
    assert player["endurance"] == 1
    assert game.level(player) == 1
    assert game.max_hp(player) == 40
    assert player["hp"] == 40
    assert game.attribute_points(player) == 0


def test_level_grants_hp_and_one_attribute_point(game: ProgressionGameService) -> None:
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 40 WHERE telegram_id = 1")
    player = game.get_player(1)
    assert game.level(player) == 2
    assert game.max_hp(player) == 60
    assert game.attribute_points(player) == 1


def test_level_up_immediately_adds_twenty_hp_in_field(game: ProgressionGameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 39, hp = 15 WHERE telegram_id = 1")
        game._add_xp(conn, 1, 1)
    player = game.get_player(1)
    assert game.level(player) == 2
    assert game.max_hp(player) == 60
    assert player["hp"] == 35


def test_attribute_point_can_be_spent_only_once(game: ProgressionGameService) -> None:
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 40 WHERE telegram_id = 1")
    game.upgrade_attribute(1, "agility")
    player = game.get_player(1)
    assert player["agility"] == 2
    assert game.attribute_points(player) == 0
    with pytest.raises(GameError):
        game.upgrade_attribute(1, "strength")


def test_equipment_requirement_blocks_purchase(game: ProgressionGameService) -> None:
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET credits = 1000 WHERE telegram_id = 1")
    with pytest.raises(GameError, match="Ловкость 2"):
        game.buy(1, "service_revolver")
    assert game.get_player(1)["weapon_id"] == "pipe_pistol"
    assert game.get_player(1)["credits"] == 1000


def test_equipment_can_be_bought_after_requirement_is_met(game: ProgressionGameService) -> None:
    with game.db.connect() as conn:
        conn.execute(
            "UPDATE players SET xp = 40, agility = 2, credits = 1000 WHERE telegram_id = 1"
        )
    game.buy(1, "service_revolver")
    player = game.get_player(1)
    assert player["weapon_id"] == "service_revolver"
    assert player["credits"] == 820


def test_return_secures_field_loot(game: ProgressionGameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        conn.execute("INSERT INTO inventory VALUES (1, 'scrap', 0, 3)")
    result = game.return_base(1)
    assert result["value"] == 24
    assert game.inventory(1, secured=0) == []
    assert game.inventory(1, secured=1)[0]["qty"] == 3
    assert game.get_player(1)["successful_runs"] == 1


def test_death_drops_only_field_loot(game: ProgressionGameService) -> None:
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


def test_locked_sector_requires_runs_and_level(game: ProgressionGameService) -> None:
    with pytest.raises(GameError):
        game.start_expedition(1, "plant_12")
    with game.db.connect() as conn:
        conn.execute(
            "UPDATE players SET successful_runs = 3, xp = 40 WHERE telegram_id = 1"
        )
    game.start_expedition(1, "plant_12")
    assert game.get_player(1)["sector_id"] == "plant_12"


def test_sell_stash(game: ProgressionGameService) -> None:
    with game.db.connect() as conn:
        conn.execute("INSERT INTO inventory VALUES (1, 'parts', 1, 2)")
    before = game.get_player(1)["credits"]
    game.sell_all(1)
    assert game.get_player(1)["credits"] == before + 68
    assert game.inventory(1, secured=1) == []


def test_legacy_database_gets_new_attribute_columns(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE players (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            hp INTEGER NOT NULL DEFAULT 100,
            credits INTEGER NOT NULL DEFAULT 70,
            ammo INTEGER NOT NULL DEFAULT 12,
            medkits INTEGER NOT NULL DEFAULT 1,
            xp INTEGER NOT NULL DEFAULT 0,
            combat INTEGER NOT NULL DEFAULT 1,
            scavenging INTEGER NOT NULL DEFAULT 1,
            survival INTEGER NOT NULL DEFAULT 1,
            successful_runs INTEGER NOT NULL DEFAULT 0,
            deaths INTEGER NOT NULL DEFAULT 0,
            weapon_id TEXT NOT NULL DEFAULT 'pipe_pistol',
            armor_id TEXT NOT NULL DEFAULT 'old_coat',
            state TEXT NOT NULL DEFAULT 'base',
            sector_id TEXT,
            threat INTEGER NOT NULL DEFAULT 0,
            steps INTEGER NOT NULL DEFAULT 0,
            pending_event TEXT,
            enemy_id TEXT,
            enemy_hp INTEGER,
            aimed INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("INSERT INTO players (telegram_id) VALUES (1)")
    conn.commit()
    conn.close()

    db = Database(path)
    db.init()
    service = ProgressionGameService(db)
    service.ensure_player(1)
    player = service.get_player(1)
    assert player["strength"] == 1
    assert player["agility"] == 1
    assert player["perception"] == 1
    assert player["endurance"] == 1
    assert player["hp"] == 40
