from __future__ import annotations

import random

from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from app.db import Database
from app.employee_rename import rename_employee


PLAYER_ID = 1001


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(91))
    simulation.seed_catalog()
    simulation.ensure_player(PLAYER_ID, "tester")
    game = CourierManagementGameService(db, simulation, rng=random.Random(92))
    return db, simulation, game


def test_current_catalog_contains_six_products_and_listings(tmp_path):
    db, _, _ = make_system(tmp_path)
    with db.connect() as conn:
        products = conn.execute("SELECT id, title FROM products WHERE active=1 ORDER BY id").fetchall()
        listings = conn.execute(
            "SELECT product_id, pack_size FROM listings WHERE player_id=? ORDER BY product_id, pack_size",
            (PLAYER_ID,),
        ).fetchall()

    assert [row["title"] for row in products] == [
        "Амфетамин",
        "MDMA",
        "Кокаин",
        "Мефедрон",
        "Кетамин",
        "LSD",
    ]
    assert len(listings) == 18
    assert {int(row["pack_size"]) for row in listings} == {1, 2, 5}


def test_employee_can_be_renamed_and_duplicate_is_rejected(tmp_path):
    db, _, game = make_system(tmp_path)
    with db.connect() as conn:
        employees = conn.execute(
            "SELECT id, alias FROM employees WHERE player_id=? AND active=1 ORDER BY id",
            (PLAYER_ID,),
        ).fetchall()
    first_id = int(employees[0]["id"])
    second_name = str(employees[1]["alias"])

    result = rename_employee(game, PLAYER_ID, first_id, "  Барс  ")
    assert result["status"] == "renamed"
    with db.connect() as conn:
        assert conn.execute("SELECT alias FROM employees WHERE id=?", (first_id,)).fetchone()[0] == "Барс"

    duplicate = rename_employee(game, PLAYER_ID, first_id, second_name)
    assert duplicate["status"] == "duplicate"


def test_employee_rename_rejects_html_breaking_name(tmp_path):
    _, _, game = make_system(tmp_path)
    with game.db.connect() as conn:
        employee_id = int(conn.execute(
            "SELECT id FROM employees WHERE player_id=? AND active=1 ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()[0])

    result = rename_employee(game, PLAYER_ID, employee_id, "<b>Крот</b>")
    assert result["status"] == "invalid"
