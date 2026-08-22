from __future__ import annotations

import random
from pathlib import Path

from app.db import Database
from app.progression import level_from_xp, progress_from_xp, total_xp_for_level, xp_required_for_next
from app.progression_view import character_screen
from app.service import GameService


def make_game(tmp_path: Path) -> GameService:
    db = Database(tmp_path / "progression.db")
    db.init()
    game = GameService(db, random.Random(7))
    game.ensure_player(1, "tester")
    return game


def test_every_level_uses_same_exponential_formula() -> None:
    assert [xp_required_for_next(level) for level in range(1, 11)] == [
        40,
        55,
        75,
        100,
        135,
        180,
        240,
        325,
        440,
        595,
    ]
    costs = [xp_required_for_next(level) for level in range(1, 15)]
    assert all(next_cost > cost for cost, next_cost in zip(costs, costs[1:]))


def test_cumulative_level_thresholds_follow_formula() -> None:
    assert total_xp_for_level(2) == 40
    assert total_xp_for_level(3) == 95
    assert total_xp_for_level(4) == 170
    assert total_xp_for_level(5) == 270
    assert total_xp_for_level(6) == 405
    assert total_xp_for_level(7) == 585
    assert total_xp_for_level(8) == 825
    assert level_from_xp(404) == 5
    assert level_from_xp(405) == 6
    assert level_from_xp(584) == 6
    assert level_from_xp(585) == 7


def test_progress_is_measured_inside_current_level() -> None:
    assert progress_from_xp(50) == (10, 55)
    assert progress_from_xp(220) == (50, 100)
    assert progress_from_xp(450) == (45, 180)


def test_runtime_level_up_still_grants_hp_and_attribute_point(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 584, hp = 140 WHERE telegram_id = 1")
        game._add_xp(conn, 1, 1)

    player = game.get_player(1)
    assert game.level(player) == 7
    assert player["hp"] == 160
    assert game.max_hp(player) == 160
    assert game.attribute_points(player) == 6


def test_character_screen_shows_dynamic_requirement(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 450 WHERE telegram_id = 1")

    screen = character_screen(game, 1)
    assert "Уровень: <b>6</b>" in screen
    assert "Опыт: 45/180" in screen
