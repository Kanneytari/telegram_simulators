from __future__ import annotations

import random
from pathlib import Path

from app.db import Database
from app.service import GameService


def make_game(tmp_path: Path) -> GameService:
    db = Database(tmp_path / "sectors.db")
    db.init()
    game = GameService(db, random.Random(7))
    game.ensure_player(1, "tester")
    return game


def test_refuge_sector_chain_requires_previous_mastery(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    player = game.get_player(1)

    assert game.sector_unlocked(player, "rust_belt")
    assert not game.sector_unlocked(player, "plant_12")
    assert not game.sector_unlocked(player, "black_contour")

    game._record_sector_progress(1, "rust_belt", 99)
    assert not game.sector_unlocked(game.get_player(1), "plant_12")

    game._record_sector_progress(1, "rust_belt", 100)
    assert game.sector_mastered(1, "rust_belt")
    assert game.sector_unlocked(game.get_player(1), "plant_12")
    assert not game.sector_unlocked(game.get_player(1), "black_contour")

    game._record_sector_progress(1, "plant_12", 100)
    assert game.sector_unlocked(game.get_player(1), "black_contour")


def test_reaching_100_threat_during_explore_unlocks_next_sector(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET threat = 99 WHERE telegram_id = 1")

    result = game.explore(1)

    assert game.sector_mastered(1, "rust_belt")
    assert game.sector_unlocked(game.get_player(1), "plant_12")
    assert result["progress_notice"] == "Сектор пройден\nОткрыта новая локация: Промзона-12"
    assert "Угроза достигла 100/100" not in result["text"]
    assert "Открыта новая вылазка" not in result["text"]


def test_each_settlement_has_its_own_mastery_chain(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    chains = [
        ("miners", "quarry", "north_mine"),
        ("station", "freight_yard", "depot_6"),
        ("promgorod", "foundry", "dead_substation"),
    ]

    for location_id, first_sector, next_sector in chains:
        with game.db.connect() as conn:
            conn.execute(
                "UPDATE player_world SET location_id = ? WHERE telegram_id = 1",
                (location_id,),
            )
        player = game.get_player(1)
        assert game.sector_unlocked(player, first_sector)
        assert not game.sector_unlocked(player, next_sector)
        game._record_sector_progress(1, first_sector, 100)
        assert game.sector_unlocked(game.get_player(1), next_sector)


def test_sector_progress_is_removed_by_full_reset(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    game._record_sector_progress(1, "rust_belt", 100)
    assert game.sector_mastered(1, "rust_belt")

    game.db.reset_player(1)
    game.ensure_player(1, "tester")

    assert not game.sector_mastered(1, "rust_belt")
    assert not game.sector_unlocked(game.get_player(1), "plant_12")
