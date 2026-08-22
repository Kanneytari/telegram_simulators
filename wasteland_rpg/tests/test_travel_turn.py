from __future__ import annotations

import random
from pathlib import Path

from app.db import Database
from app.service import GameService
from app.travel_control import turn_travel
from app.travel_view import travel_keyboard, travel_screen


def make_game(tmp_path: Path) -> GameService:
    db = Database(tmp_path / "travel-turn.db")
    db.init()
    game = GameService(db, random.Random(7))
    game.ensure_player(1, "tester")
    return game


def button_texts(game: GameService) -> list[str]:
    return [button.text for row in travel_keyboard(game, 1).inline_keyboard for button in row]


def test_turning_around_mirrors_position_and_swaps_destination(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    game.start_travel(1, "refuge_miners")
    with game.db.connect() as conn:
        conn.execute("UPDATE travel SET step = 6 WHERE telegram_id = 1")

    result = turn_travel(game, 1)
    state = game.travel_state(1)

    assert result["remaining"] == 6
    assert state["origin_id"] == "miners"
    assert state["target_id"] == "refuge7"
    assert state["step"] == 4
    assert "До города: 6 участков" in result["text"]


def test_player_can_turn_around_more_than_once(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    game.start_travel(1, "refuge_miners")
    with game.db.connect() as conn:
        conn.execute("UPDATE travel SET step = 6 WHERE telegram_id = 1")

    turn_travel(game, 1)
    turn_travel(game, 1)
    state = game.travel_state(1)

    assert state["origin_id"] == "refuge7"
    assert state["target_id"] == "miners"
    assert state["step"] == 6


def test_returning_all_the_way_back_keeps_cargo(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        conn.execute("INSERT INTO cargo (telegram_id, item_id, qty) VALUES (1, 'scrap', 2)")
    game.start_travel(1, "refuge_miners")
    with game.db.connect() as conn:
        conn.execute("UPDATE travel SET step = 6 WHERE telegram_id = 1")

    turn_travel(game, 1)
    with game.db.connect() as conn:
        conn.execute("UPDATE travel SET step = 10 WHERE telegram_id = 1")

    result = game.advance_travel(1)

    assert result["arrived"] is True
    assert game.get_player(1)["state"] == "base"
    assert game.location_id(1) == "refuge7"
    assert game.cargo(1)[0]["qty"] == 2


def test_turn_before_first_section_cancels_trip_without_risk(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    game.start_travel(1, "refuge_miners")

    result = turn_travel(game, 1)

    assert result["immediate"] is True
    assert game.get_player(1)["state"] == "base"
    assert game.travel_state(1) is None
    assert game.location_id(1) == "refuge7"

    names = [row["event_name"] for row in game.analytics_events(1)]
    assert "travel_turned" in names
    assert names[-1] == "travel_finished"


def test_travel_view_shows_current_destination_and_turn_button(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    game.start_travel(1, "refuge_miners")
    with game.db.connect() as conn:
        conn.execute("UPDATE travel SET step = 6 WHERE telegram_id = 1")

    assert "👣 Осталось участков: 4" in travel_screen(game, 1)
    assert "☢️ Приют-7 → ⛏️ Шахтёрский" in travel_screen(game, 1)
    assert "👣 Дальше: ⛏️ Шахтёрский" in button_texts(game)
    assert "↩️ Развернуться: ☢️ Приют-7" in button_texts(game)

    turn_travel(game, 1)

    assert "👣 Осталось участков: 6" in travel_screen(game, 1)
    assert "⛏️ Шахтёрский → ☢️ Приют-7" in travel_screen(game, 1)
    assert "👣 Дальше: ☢️ Приют-7" in button_texts(game)
    assert "↩️ Развернуться: ⛏️ Шахтёрский" in button_texts(game)
