from __future__ import annotations

import random

from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from app.db import Database


PLAYER_ID = 1001


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(81))
    simulation.seed_catalog()
    simulation.ensure_player(PLAYER_ID, "tester")
    game = CourierManagementGameService(db, simulation, rng=random.Random(82))
    return db, simulation, game


def test_packaging_rule_is_shop_wide(tmp_path):
    db, _, game = make_system(tmp_path)

    assert game.global_packaging_rule(PLAYER_ID) == {"pct_1": 60, "pct_2": 30, "pct_5": 10}
    result = game.adjust_global_packaging_rule(PLAYER_ID, 1, 10)
    assert result == "×1 70% · ×2 20% · ×5 10%"

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT pct_1, pct_2, pct_5 FROM shop_packaging_rules WHERE player_id=?",
            (PLAYER_ID,),
        ).fetchall()
    assert len(rows) == 1
    assert (int(rows[0]["pct_1"]), int(rows[0]["pct_2"]), int(rows[0]["pct_5"])) == (70, 20, 10)


def test_new_courier_uses_existing_shop_packaging_rule(tmp_path):
    db, simulation, game = make_system(tmp_path)
    game.adjust_global_packaging_rule(PLAYER_ID, 5, 10)
    expected = game.global_packaging_rule(PLAYER_ID)

    with db.connect() as conn:
        conn.execute(
            """INSERT INTO employees(
                   player_id, alias, role, pay_per_job, deposit,
                   deposit_contribution_pct, has_car,
                   reliability, attention, honesty, loyalty, stress
               ) VALUES (?, 'Новый', 'courier', 0, 50000, 0, 0,
                         0.8, 0.8, 0.8, 0.7, 10)""",
            (PLAYER_ID,),
        )

    simulation._ensure_packaging_rules(PLAYER_ID)
    assert game.global_packaging_rule(PLAYER_ID) == expected
    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM shop_packaging_rules WHERE player_id=?",
            (PLAYER_ID,),
        ).fetchone()[0]
    assert int(count) == 1
