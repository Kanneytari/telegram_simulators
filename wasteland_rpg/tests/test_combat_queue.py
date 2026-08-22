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


def test_combat_keyboard_has_fixed_four_by_two_layout(tmp_path: Path) -> None:
    game = make_game(tmp_path)

    markup = combat_keyboard(game, 1)
    assert len(markup.inline_keyboard) == 4
    assert all(len(row) == 2 for row in markup.inline_keyboard)

    with game.db.connect() as conn:
        timeline = conn.execute("SELECT * FROM combat_timeline WHERE telegram_id = 1").fetchone()
        conn.execute(
            "UPDATE combat_timeline SET opportunity_kind = 'stim', opportunity_until = ? WHERE telegram_id = 1",
            (float(timeline["player_last_action_at"]) + 20.0,),
        )
        conn.execute("UPDATE combat_state SET distance = 1 WHERE telegram_id = 1")

    changed = combat_keyboard(game, 1)
    assert len(changed.inline_keyboard) == 4
    assert all(len(row) == 2 for row in changed.inline_keyboard)


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
    assert any("Ближний бой · 2с" in text for text in texts)
    assert any("Отступить · 5с" in text for text in texts)


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

    screen = combat_screen(game, 1)
    assert "Следующее:" not in screen
    assert "Противник:" not in screen
    assert any(text.startswith("🕒 🔫 Выстрел") for text in button_texts(game))


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
    assert float(updated["player_action_due"]) == pytest.approx(current_due + 8.0)
    assert game.combat_queued_action(1) is None


def test_current_action_reserves_its_ammo_from_queue(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET ammo = 1 WHERE telegram_id = 1")
    started = float(game.combat_timeline(1)["player_last_action_at"])

    game.combat_action(1, "shoot", now=started)

    texts = button_texts(game)
    assert any(text.startswith("▫️ 🔫 Выстрел") for text in texts)
    assert any(text.startswith("▫️ 🎯 Прицельный") for text in texts)
    with pytest.raises(GameError, match="патронов не останется"):
        game.combat_action(1, "shoot", now=started + 0.5)
