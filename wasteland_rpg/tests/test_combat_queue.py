from __future__ import annotations

import random
from pathlib import Path

import pytest

from app.combat_view import combat_keyboard, combat_screen
from app.db import Database
from app.game import GameError
from app.queued_combat_service import GameService


def make_game(tmp_path: Path) -> GameService:
    db = Database(tmp_path / "combat-queue.db")
    db.init()
    game = GameService(db, random.Random(7))
    game.ensure_player(1, "tester")
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        game._start_combat(conn, 1, "bone_dog", return_state="expedition")
        conn.execute("UPDATE players SET enemy_hp = 999 WHERE telegram_id = 1")
    return game


def button_texts(game: GameService) -> list[str]:
    return [button.text for row in combat_keyboard(game, 1).inline_keyboard for button in row]


def test_buttons_stay_visible_while_action_is_running(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    started = float(game.combat_timeline(1)["player_last_action_at"])

    game.combat_action(1, "shoot", now=started)

    texts = button_texts(game)
    assert any("Выстрел" in text for text in texts)
    assert any("Прицельный" in text for text in texts)
    assert any("Отступить" in text for text in texts)
    assert all(".5с" not in text for text in texts)
    assert any("Выстрел · 5с" in text for text in texts)
    assert any("Прицельный · 8с" in text for text in texts)


def test_only_one_next_action_is_kept_and_can_be_replaced(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    started = float(game.combat_timeline(1)["player_last_action_at"])
    game.combat_action(1, "shoot", now=started)

    first = game.combat_action(1, "aimed_shot", now=started + 0.5)
    assert first["queued"] is True
    assert first["replaced"] is False
    assert game.combat_queued_action(1) == "aimed_shot"

    second = game.combat_action(1, "shoot", now=started + 0.7)
    assert second["queued"] is True
    assert second["replaced"] is True
    assert game.combat_queued_action(1) == "shoot"
    assert "Следующее: 🔫 Выстрел" in combat_screen(game, 1)
    assert any(text.startswith("✓ 🔫 Выстрел") for text in button_texts(game))


def test_queued_action_starts_after_current_and_pays_full_duration(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    timeline = game.combat_timeline(1)
    started = float(timeline["player_last_action_at"])

    game.combat_action(1, "shoot", now=started)
    current_due = float(game.combat_timeline(1)["player_action_due"])
    game.combat_action(1, "aimed_shot", now=started + 1.0)

    game.tick_all_combats(current_due + 0.01)
    updated = game.combat_timeline(1)

    assert updated["player_action"] == "aimed_shot"
    assert float(updated["player_action_due"]) == pytest.approx(current_due + 7.5)
    assert game.combat_queued_action(1) is None


def test_current_action_reserves_its_ammo_from_queue(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET ammo = 1 WHERE telegram_id = 1")
    started = float(game.combat_timeline(1)["player_last_action_at"])

    game.combat_action(1, "shoot", now=started)

    assert all("Выстрел" not in text and "Прицельный" not in text for text in button_texts(game))
    with pytest.raises(GameError, match="патронов не останется"):
        game.combat_action(1, "shoot", now=started + 0.5)
