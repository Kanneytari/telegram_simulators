from __future__ import annotations

import random
from pathlib import Path

from app.combat_view import combat_keyboard
from app.db import Database
from app.service import GameService


def make_game(tmp_path: Path) -> GameService:
    db = Database(tmp_path / "runtime-edge-cases.db")
    db.init()
    game = GameService(db, random.Random(7))
    game.ensure_player(1, "tester")
    return game


def button_texts(game: GameService) -> list[str]:
    markup = combat_keyboard(game, 1)
    return [button.text for row in markup.inline_keyboard for button in row]


def test_out_of_ammo_requires_real_waiting_not_a_wait_button(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    game.start_expedition(1, "rust_belt")
    with game.db.connect() as conn:
        game._start_combat(conn, 1, "bone_dog", return_state="expedition")
        conn.execute("UPDATE combat_state SET distance = 3 WHERE telegram_id = 1")
        conn.execute("UPDATE players SET ammo = 0 WHERE telegram_id = 1")

    far_buttons = button_texts(game)
    assert all("Ждать" not in text for text in far_buttons)
    assert all("Выстрел" not in text for text in far_buttons)
    assert all("Ближний бой" not in text for text in far_buttons)

    timeline = game.combat_timeline(1)
    game.tick_all_combats(float(timeline["enemy_action_due"]) + 0.01)
    assert game.combat_state(1)["distance"] == 2

    timeline = game.combat_timeline(1)
    game.tick_all_combats(float(timeline["enemy_action_due"]) + 0.01)
    assert game.combat_state(1)["distance"] == 1
    assert any("Ближний бой" in text for text in button_texts(game))


def test_load_stash_to_cargo_does_not_insert_negative_inventory_qty(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        conn.execute(
            "INSERT INTO inventory (telegram_id, item_id, secured, qty) VALUES (1, 'scrap', 1, 3)"
        )

    message = game.load_stash_to_cargo(1)

    assert "В груз перенесено" in message
    assert game.inventory(1, secured=1) == []
    cargo = game.cargo(1)
    assert len(cargo) == 1
    assert cargo[0]["item_id"] == "scrap"
    assert cargo[0]["qty"] == 3


def test_negative_cargo_change_never_violates_check_constraint(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    with game.db.connect() as conn:
        conn.execute("INSERT INTO cargo (telegram_id, item_id, qty) VALUES (1, 'wire', 2)")
        game._change_cargo(conn, 1, "wire", -2)

    assert game.cargo(1) == []
