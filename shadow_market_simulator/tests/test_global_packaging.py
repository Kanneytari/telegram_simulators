from __future__ import annotations

import random

from app.db import Database
from app.employee_profile_handlers import employee_profile_keyboard
from app.global_packaging import GlobalPackagingGameService, GlobalPackagingSimulationEngine
from app.team_keyboard import employee_list


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
               ) VALUES (1001, 'Новый', 'courier', 1500, 50000, 10, 0,
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


def test_team_keyboard_has_only_recruitment_and_global_packaging_controls():
    markup = employee_list([])
    labels = [button.text for row in markup.inline_keyboard for button in row]

    assert "🔎 Набор" in labels
    assert "⚙️ Фасовки" in labels
    assert "👤 Кандидаты" not in labels
    assert "📦 Без ответственного" not in labels


def test_courier_profile_has_no_individual_packaging_button():
    markup = employee_profile_keyboard(17, "courier")
    labels = [button.text for row in markup.inline_keyboard for button in row]

    assert "⚙️ Фасовки" not in labels
    assert "✏️ Переименовать" in labels
    assert "💰 Доля в депозит" in labels
