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


def test_early_levels_keep_original_pace() -> None:
    assert [xp_required_for_next(level) for level in range(1, 6)] == [40, 40, 40, 40, 40]
    assert total_xp_for_level(6) == 200
    assert level_from_xp(199) == 5
    assert level_from_xp(200) == 6


def test_high_level_thresholds_grow_progressively() -> None:
    assert [xp_required_for_next(level) for level in range(6, 11)] == [60, 90, 130, 180, 240]
    assert total_xp_for_level(7) == 260
    assert total_xp_for_level(8) == 350
    assert total_xp_for_level(9) == 480
    assert total_xp_for_level(10) == 660
    assert level_from_xp(259) == 6
    assert level_from_xp(260) == 7
    assert level_from_xp(349) == 7
    assert level_from_xp(350) == 8


def test_progress_is_measured_inside_current_level() -> None:
    assert progress_from_xp(220) == (20, 60)
    assert progress_from_xp(300) == (40, 90)
    assert progress_from_xp(400) == (50, 130)


def test_runtime_level_up_still_grants_hp_and_attribute_point(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 259, hp = 140 WHERE telegram_id = 1")
        game._add_xp(conn, 1, 1)

    player = game.get_player(1)
    assert game.level(player) == 7
    assert player["hp"] == 160
    assert game.max_hp(player) == 160
    assert game.attribute_points(player) == 6


def test_character_screen_shows_dynamic_requirement(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 220 WHERE telegram_id = 1")

    screen = character_screen(game, 1)
    assert "Уровень: <b>6</b>" in screen
    assert "Опыт: 20/60" in screen
