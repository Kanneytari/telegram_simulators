from __future__ import annotations

import random
from pathlib import Path

from app import ui
from app.db import Database
from app.game import GameService


def make_game(tmp_path: Path) -> GameService:
    db = Database(tmp_path / "test.db")
    db.init()
    game = GameService(db, random.Random(7))
    game.ensure_player(1, "tester")
    return game


def test_level_notice_stays_until_attribute_is_spent(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 40 WHERE telegram_id = 1")

    screen = ui.main_screen(game, 1)
    assert "<blockquote>⬆️ Новый уровень! Выбери характеристику для улучшения.</blockquote>" in screen
    assert "⬆️ очков:" not in screen

    game.upgrade_attribute(1, "strength")
    screen = ui.main_screen(game, 1)
    assert "Новый уровень!" not in screen


def test_level_notice_is_visible_during_expedition(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp = 39 WHERE telegram_id = 1")
        game._add_xp(conn, 1, 1)

    screen = ui.expedition_screen(game, 1)
    assert "<blockquote>⬆️ Новый уровень! Выбери характеристику для улучшения.</blockquote>" in screen
