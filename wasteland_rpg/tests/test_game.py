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


def test_player_baseline_and_new_tables(game: GameService) -> None:
    player = game.get_player(1)
    assert [player[k] for k in ("strength", "agility", "perception", "intelligence")] == [1, 1, 1, 1]
    assert game.location_id(1) == "refuge7"
    assert game.equipment(1)["backpack_id"] == "canvas_pack"
    with game.db.connect() as conn:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"player_world", "visited_locations", "equipment", "cargo", "travel", "combat_state"} <= tables


def test_attributes_have_no_upper_limit(game: GameService) -> None:
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp=800, intelligence=20 WHERE telegram_id=1")
    before = game.get_player(1)["intelligence"]
    message = game.upgrade_attribute(1, "intelligence")
    assert game.get_player(1)["intelligence"] == before + 1
    assert "Характеристика «Интеллект» повышена" in message


def test_backpack_increases_capacity(game: GameService) -> None:
    base = game.carry_capacity(game.get_player(1))
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET strength=2 WHERE telegram_id=1")
        conn.execute("UPDATE equipment SET backpack_id='field_pack' WHERE telegram_id=1")
    assert game.carry_capacity(game.get_player(1)) == 24
    assert game.carry_capacity(game.get_player(1)) > base


def test_market_arbitrage_between_locations(game: GameService) -> None:
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET credits=100 WHERE telegram_id=1")
        conn.execute("UPDATE player_world SET location_id='miners' WHERE telegram_id=1")
    game.buy_trade_good(1, "scrap")
    assert game.get_player(1)["credits"] == 94
    with game.db.connect() as conn:
        conn.execute("UPDATE player_world SET location_id='promgorod' WHERE telegram_id=1")
    game.sell_cargo(1)
    assert game.get_player(1)["credits"] == 108


def test_route_has_ten_stages_and_arrival_changes_location(game: GameService) -> None:
    game.start_travel(1, "refuge_miners")
    with game.db.connect() as conn:
        conn.execute("UPDATE travel SET step=10 WHERE telegram_id=1")
    result = game.advance_travel(1)
    assert result["arrived"] is True
    assert game.location_id(1) == "miners"
    assert game.get_player(1)["state"] == "base"


def test_travel_death_loses_cargo(game: GameService) -> None:
    game.buy_trade_good(1, "scrap")
    game.start_travel(1, "refuge_miners")
    with game.db.connect() as conn:
        game._start_combat(conn, 1, "raider", return_state="travel")
        conn.execute("UPDATE players SET hp=1 WHERE telegram_id=1")
    game.rng = random.Random(1)
    game.combat_action(1, "aim")
    assert game.get_player(1)["state"] == "base"
    assert game.cargo(1) == []
    assert game.location_id(1) == "refuge7"


def test_local_sector_depends_on_location(game: GameService) -> None:
    assert game.sector_unlocked(game.get_player(1), "rust_belt")
    assert not game.sector_unlocked(game.get_player(1), "quarry")
    with game.db.connect() as conn:
        conn.execute("UPDATE player_world SET location_id='miners' WHERE telegram_id=1")
        conn.execute("UPDATE players SET successful_runs=1 WHERE telegram_id=1")
    assert game.sector_unlocked(game.get_player(1), "quarry")


def test_branching_scene_can_resolve_by_attribute(game: GameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET pending_event='scene:warehouse', perception=20 WHERE telegram_id=1")
    result = game.resolve_choice(1, "careful")
    assert "Ловушка" in result["text"]
    assert game.get_player(1)["pending_event"] is None


def test_melee_requires_close_distance(game: GameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        game._start_combat(conn, 1, "bone_dog", return_state="expedition")
        conn.execute("UPDATE combat_state SET distance=3 WHERE telegram_id=1")
    with pytest.raises(GameError, match="сблизиться"):
        game.combat_action(1, "melee")


def test_carbine_supports_burst(game: GameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET weapon_id='short_carbine', ammo=10 WHERE telegram_id=1")
        game._start_combat(conn, 1, "stitched", return_state="expedition")
    before = game.get_player(1)["ammo"]
    game.combat_action(1, "burst")
    assert game.get_player(1)["ammo"] == before - 3


def test_level_point_is_spent_once(game: GameService) -> None:
    with game.db.connect() as conn:
        conn.execute("UPDATE players SET xp=40 WHERE telegram_id=1")
    game.upgrade_attribute(1, "strength")
    assert game.attribute_points(game.get_player(1)) == 0
    with pytest.raises(GameError):
        game.upgrade_attribute(1, "agility")


def test_return_secures_field_loot(game: GameService) -> None:
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        conn.execute("INSERT INTO inventory VALUES (1, 'scrap', 0, 3)")
    game.return_base(1)
    assert game.inventory(1, secured=0) == []
    assert game.inventory(1, secured=1)[0]["qty"] == 3
