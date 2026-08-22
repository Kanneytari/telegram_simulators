from __future__ import annotations

import random
from pathlib import Path

import pytest

from app.combat_rules import ENEMY_ACTION_SECONDS, PLAYER_ACTION_SECONDS
from app.db import Database
from app.service import GameService


def make_game(tmp_path: Path) -> GameService:
    db = Database(tmp_path / "realtime-combat.db")
    db.init()
    game = GameService(db, random.Random(7))
    game.ensure_player(1, "tester")
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        game._start_combat(conn, 1, "bone_dog", return_state="expedition")
    return game


def test_action_cost_uses_time_already_elapsed_since_previous_action(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    timeline = game.combat_timeline(1)
    started_at = float(timeline["player_last_action_at"])

    game.combat_action(1, "aimed_shot", now=started_at + 6.5)
    updated = game.combat_timeline(1)

    assert updated["player_action"] == "aimed_shot"
    assert float(updated["player_action_due"]) == pytest.approx(started_at + 7.5)


def test_combat_action_times_are_slowed_by_fifty_percent() -> None:
    assert PLAYER_ACTION_SECONDS == {
        "shoot": 4.5,
        "aimed_shot": 7.5,
        "burst": 7.5,
        "melee": 3.0,
        "cover": 3.0,
        "stim": 1.5,
        "medkit": 6.0,
        "flee": 7.5,
    }
    assert ENEMY_ACTION_SECONDS == {
        "approach": 3.0,
        "retreat": 3.0,
        "melee_attack": 4.5,
        "ranged_attack": 6.0,
    }


def test_enemy_progresses_without_player_action(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    before = game.combat_state(1)["distance"]
    timeline = game.combat_timeline(1)

    game.tick_all_combats(float(timeline["enemy_action_due"]) + 0.01)

    assert game.combat_state(1)["distance"] == before - 1


def test_combat_log_keeps_only_seven_latest_events(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        for index in range(10):
            game._log_conn(conn, 1, f"event-{index}")

    log = game.combat_log(1)
    assert len(log) == 7
    assert log[0] == "event-3"
    assert log[-1] == "event-9"


def test_stim_heals_each_second_after_use(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET hp = 20 WHERE telegram_id = 1")
        timeline = conn.execute("SELECT * FROM combat_timeline WHERE telegram_id = 1").fetchone()
        start = float(timeline["player_last_action_at"])
        conn.execute(
            "UPDATE combat_timeline SET opportunity_kind = 'stim', opportunity_until = ? WHERE telegram_id = 1",
            (start + 20.0,),
        )

    game.combat_action(1, "stim", now=start + 1.5)
    after_use = game.get_player(1)["hp"]
    game.tick_all_combats(start + 2.51)

    assert game.get_player(1)["hp"] >= after_use + 3
