from __future__ import annotations

import random

from app.db import Database
from app.global_packaging import GlobalPackagingGameService, GlobalPackagingSimulationEngine


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = GlobalPackagingSimulationEngine(db, speed=1.0, rng=random.Random(81))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    game = GlobalPackagingGameService(db, simulation, rng=random.Random(82))
    return db, simulation, game


def test_global_packaging_adjustment_syncs_all_couriers_and_products(tmp_path):
    db, _, game = make_system(tmp_path)

    assert game.global_packaging_rule(1001) == {"pct_1": 60, "pct_2": 30, "pct_5": 10}
    result = game.adjust_global_packaging_rule(1001, 1, 10)
    assert result == "×1 70% · ×2 20% · ×5 10%"

    with db.connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT pct_1, pct_2, pct_5
               FROM packaging_rules WHERE player_id=1001"""
        ).fetchall()
    assert len(rows) == 1
    assert (int(rows[0]["pct_1"]), int(rows[0]["pct_2"]), int(rows[0]["pct_5"])) == (70, 20, 10)


def test_new_courier_inherits_global_packaging_mix(tmp_path):
    db, simulation, game = make_system(tmp_path)
    game.adjust_global_packaging_rule(1001, 5, 10)

    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO employees(
                   player_id, alias, role, pay_per_job, deposit,
                   deposit_contribution_pct, has_car,
                   reliability, attention, honesty, loyalty, stress
               ) VALUES (1001, 'Новый', 'courier', 0, 50000, 0, 0,
                         0.8, 0.8, 0.8, 0.7, 10)"""
        )
        employee_id = int(cur.lastrowid)

    simulation._ensure_packaging_rules(1001)
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT pct_1, pct_2, pct_5 FROM packaging_rules
               WHERE player_id=1001 AND employee_id=? ORDER BY product_id""",
            (employee_id,),
        ).fetchall()

    assert rows
    expected = game.global_packaging_rule(1001)
    assert all(
        (int(row["pct_1"]), int(row["pct_2"]), int(row["pct_5"]))
        == (expected["pct_1"], expected["pct_2"], expected["pct_5"])
        for row in rows
    )
