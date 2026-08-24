from __future__ import annotations

import random

from app.catalog_extension import EXTRA_PRODUCTS, ExpandedCatalogSimulationEngine
from app.db import Database
from app.employee_rename import rename_employee
from app.staff_relationships import StaffRelationshipGameService, StaffRelationshipSimulationEngine


def make_expanded_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = ExpandedCatalogSimulationEngine(db, speed=1.0, rng=random.Random(91))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = StaffRelationshipGameService(db, simulation, rng=random.Random(92))
    return db, simulation, game


def test_expanded_catalog_contains_six_products_and_new_listings(tmp_path):
    db, _, _ = make_expanded_system(tmp_path)
    with db.connect() as conn:
        products = conn.execute("SELECT id, title FROM products WHERE active=1 ORDER BY id").fetchall()
        extra_listings = conn.execute(
            "SELECT product_id, pack_size FROM listings WHERE player_id=1001 AND product_id IN (4,5,6) ORDER BY product_id, pack_size"
        ).fetchall()

    assert [row["title"] for row in products] == [
        "Амфетамин",
        "MDMA",
        "Кокаин",
        "Мефедрон",
        "Кетамин",
        "LSD",
    ]
    assert len(extra_listings) == 9
    assert {int(row["pack_size"]) for row in extra_listings} == {1, 2, 5}
    assert len(EXTRA_PRODUCTS) == 3


def test_seed_catalog_upgrades_existing_player_without_reset(tmp_path):
    db = Database(str(tmp_path / "upgrade.db"))
    db.init()
    old_simulation = StaffRelationshipSimulationEngine(db, speed=1.0, rng=random.Random(93))
    old_simulation.seed_catalog()
    old_simulation.ensure_player(1001, "tester")

    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0] == 3

    upgraded = ExpandedCatalogSimulationEngine(db, speed=1.0, rng=random.Random(94))
    upgraded.seed_catalog()

    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM products WHERE active=1").fetchone()[0] == 6
        assert conn.execute(
            "SELECT COUNT(*) FROM listings WHERE player_id=1001 AND product_id IN (4,5,6)"
        ).fetchone()[0] == 9


def test_employee_can_be_renamed_and_duplicate_is_rejected(tmp_path):
    db, _, game = make_expanded_system(tmp_path)
    with db.connect() as conn:
        employees = conn.execute(
            "SELECT id, alias FROM employees WHERE player_id=1001 AND active=1 ORDER BY id"
        ).fetchall()
    first_id = int(employees[0]["id"])
    second_name = str(employees[1]["alias"])

    result = rename_employee(game, 1001, first_id, "  Барс  ")
    assert result["status"] == "renamed"
    with db.connect() as conn:
        assert conn.execute("SELECT alias FROM employees WHERE id=?", (first_id,)).fetchone()[0] == "Барс"

    duplicate = rename_employee(game, 1001, first_id, second_name)
    assert duplicate["status"] == "duplicate"


def test_employee_rename_rejects_html_breaking_name(tmp_path):
    _, _, game = make_expanded_system(tmp_path)
    with game.db.connect() as conn:
        employee_id = int(conn.execute(
            "SELECT id FROM employees WHERE player_id=1001 AND active=1 ORDER BY id LIMIT 1"
        ).fetchone()[0])

    result = rename_employee(game, 1001, employee_id, "<b>Крот</b>")
    assert result["status"] == "invalid"
