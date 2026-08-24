from __future__ import annotations

import random
from datetime import timedelta

from app.courier_management import (
    BONUS_COST,
    CourierManagementGameService,
    CourierManagementSimulationEngine,
)
from app.courier_model import TRAIT_LEARNER
from app.courier_recruitment import CourierRecruitmentService
from app.db import Database
from app.recruitment import CHANNELS
from app.simulation import iso, utcnow


PLAYER_ID = 1001


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(1201))
    simulation.seed_catalog()
    simulation.ensure_player(PLAYER_ID, "tester")
    game = CourierManagementGameService(db, simulation, rng=random.Random(1202))
    recruitment = CourierRecruitmentService(db, speed=1.0, rng=random.Random(1203))
    return db, simulation, game, recruitment


def first_courier(db: Database):
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM employees WHERE player_id=? AND role='courier' AND active=1 ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()


def prepare_live_order(db: Database, courier_id: int):
    with db.connect() as conn:
        conn.execute("DELETE FROM retail_positions WHERE player_id=?", (PLAYER_ID,))
        batch = conn.execute(
            """SELECT * FROM batches
               WHERE player_id=? AND responsible_employee_id IS NOT NULL
               ORDER BY id LIMIT 1""",
            (PLAYER_ID,),
        ).fetchone()
        listing = conn.execute(
            """SELECT l.*, p.complaint_modifier FROM listings l
               JOIN products p ON p.id=l.product_id
               WHERE l.player_id=? AND l.product_id=? AND l.pack_size=1 LIMIT 1""",
            (PLAYER_ID, batch["product_id"]),
        ).fetchone()
        allocation = conn.execute(
            """INSERT INTO retail_allocations(
                   player_id, batch_id, wholesale_employee_id, retail_employee_id,
                   product_id, quantity, unit_cost, quality, status, received_at, completed_at
               ) VALUES (?, ?, ?, ?, ?, 5, ?, ?, 'published', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (
                PLAYER_ID,
                batch["id"],
                batch["responsible_employee_id"],
                courier_id,
                batch["product_id"],
                batch["unit_cost"],
                batch["quality"],
            ),
        )
        conn.execute(
            """INSERT INTO retail_positions(
                   player_id, allocation_id, batch_id, employee_id, product_id,
                   pack_size, position_count, unit_cost, quality
               ) VALUES (?, ?, ?, ?, ?, 1, 5, ?, ?)""",
            (
                PLAYER_ID,
                int(allocation.lastrowid),
                batch["id"],
                courier_id,
                batch["product_id"],
                batch["unit_cost"],
                batch["quality"],
            ),
        )
        return dict(listing)


def test_management_rows_exist_for_every_live_courier(tmp_path):
    db, _, _, _ = make_system(tmp_path)
    with db.connect() as conn:
        couriers = int(conn.execute(
            "SELECT COUNT(*) FROM employees WHERE player_id=? AND role='courier'",
            (PLAYER_ID,),
        ).fetchone()[0])
        management = int(conn.execute(
            "SELECT COUNT(*) FROM courier_management WHERE player_id=?",
            (PLAYER_ID,),
        ).fetchone()[0])
    assert couriers > 0
    assert management == couriers


def test_equipment_materially_improves_real_work_effects(tmp_path):
    db, simulation, _, _ = make_system(tmp_path)
    courier = first_courier(db)
    employee_id = int(courier["id"])
    with db.connect() as conn:
        conn.execute(
            """UPDATE courier_profiles
               SET pace=0.66, precision=0.73, resilience=0.82, trait='steady'
               WHERE employee_id=?""",
            (employee_id,),
        )
        conn.execute(
            "UPDATE courier_management SET transport_level=0, phone_level=0 WHERE employee_id=?",
            (employee_id,),
        )
    with db.connect() as conn:
        profile = conn.execute(
            "SELECT * FROM courier_profiles WHERE employee_id=?",
            (employee_id,),
        ).fetchone()
    base_pace = simulation._effective_pace(profile, 20)
    base_precision = simulation._effective_precision(profile, 20)

    with db.connect() as conn:
        conn.execute(
            "UPDATE courier_management SET transport_level=2, phone_level=2 WHERE employee_id=?",
            (employee_id,),
        )
    improved_pace = simulation._effective_pace(profile, 20)
    improved_precision = simulation._effective_precision(profile, 20)

    assert improved_pace - base_pace >= 0.15
    assert improved_precision - base_precision >= 0.08


def test_long_term_learner_plus_equipment_becomes_materially_better(tmp_path):
    db, simulation, _, _ = make_system(tmp_path)
    courier = first_courier(db)
    employee_id = int(courier["id"])
    with db.connect() as conn:
        conn.execute(
            """UPDATE courier_profiles
               SET pace=0.60, precision=0.74, resilience=0.86, trait=?, observed_orders=0
               WHERE employee_id=?""",
            (TRAIT_LEARNER, employee_id),
        )
        conn.execute(
            "UPDATE courier_management SET transport_level=0, phone_level=0 WHERE employee_id=?",
            (employee_id,),
        )
        profile = conn.execute(
            "SELECT * FROM courier_profiles WHERE employee_id=?",
            (employee_id,),
        ).fetchone()
    early_pace = simulation._effective_pace(profile, 20)
    early_precision = simulation._effective_precision(profile, 20)

    with db.connect() as conn:
        conn.execute(
            "UPDATE courier_profiles SET observed_orders=180 WHERE employee_id=?",
            (employee_id,),
        )
        conn.execute(
            "UPDATE courier_management SET transport_level=2, phone_level=2 WHERE employee_id=?",
            (employee_id,),
        )
        mature = conn.execute(
            "SELECT * FROM courier_profiles WHERE employee_id=?",
            (employee_id,),
        ).fetchone()
    mature_pace = simulation._effective_pace(mature, 20)
    mature_precision = simulation._effective_precision(mature, 20)

    assert mature_pace - early_pace >= 0.23
    assert mature_precision - early_precision >= 0.16


def test_bonus_has_real_cost_effect_and_cooldown(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    courier = first_courier(db)
    employee_id = int(courier["id"])
    with db.connect() as conn:
        conn.execute("UPDATE shops SET balance=500000, reserve_target=0 WHERE player_id=?", (PLAYER_ID,))
        conn.execute("UPDATE employees SET deposit=0, wages_accrued=0 WHERE player_id=?", (PLAYER_ID,))
        conn.execute(
            "UPDATE employees SET stress=70, loyalty=0.50 WHERE id=?",
            (employee_id,),
        )
        before_balance = int(conn.execute(
            "SELECT balance FROM shops WHERE player_id=?", (PLAYER_ID,)
        ).fetchone()[0])

    result = game.give_bonus(PLAYER_ID, employee_id)
    assert result["status"] == "ok"

    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE id=?", (employee_id,)
        ).fetchone()
        management = conn.execute(
            "SELECT * FROM courier_management WHERE employee_id=?", (employee_id,)
        ).fetchone()
        after_balance = int(conn.execute(
            "SELECT balance FROM shops WHERE player_id=?", (PLAYER_ID,)
        ).fetchone()[0])
    assert before_balance - after_balance == BONUS_COST
    assert float(employee["stress"]) <= 62
    assert float(employee["loyalty"]) > 0.50
    assert int(management["invested_total"]) == BONUS_COST
    assert game.give_bonus(PLAYER_ID, employee_id)["status"] == "cooldown"


def test_management_spending_cannot_use_reserved_employee_money(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    courier = first_courier(db)
    employee_id = int(courier["id"])
    with db.connect() as conn:
        conn.execute("UPDATE employees SET deposit=0, wages_accrued=0 WHERE player_id=?", (PLAYER_ID,))
        conn.execute("UPDATE employees SET deposit=50000 WHERE id=?", (employee_id,))
        conn.execute("UPDATE shops SET balance=85000, reserve_target=30000 WHERE player_id=?", (PLAYER_ID,))
    result = game.upgrade_equipment(PLAYER_ID, employee_id, "transport")
    assert result["status"] == "money"


def test_rest_is_paid_meaningful_and_not_spammable(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    courier = first_courier(db)
    employee_id = int(courier["id"])
    with db.connect() as conn:
        conn.execute("UPDATE shops SET balance=500000, reserve_target=0 WHERE player_id=?", (PLAYER_ID,))
        conn.execute("UPDATE employees SET deposit=0, wages_accrued=0 WHERE player_id=?", (PLAYER_ID,))
        conn.execute("UPDATE employee_tasks SET status='completed' WHERE employee_id=?", (employee_id,))
        conn.execute("UPDATE employees SET stress=92, loyalty=0.50, available=1, unavailable_until=NULL WHERE id=?", (employee_id,))

    result = game.send_to_rest(PLAYER_ID, employee_id, 24)
    assert result["status"] == "ok"
    with db.connect() as conn:
        employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
        management = conn.execute(
            "SELECT * FROM courier_management WHERE employee_id=?", (employee_id,)
        ).fetchone()
    assert int(employee["available"]) == 0
    assert float(employee["stress"]) <= 44
    assert float(employee["loyalty"]) > 0.50
    assert int(management["rests_taken"]) == 1

    with db.connect() as conn:
        conn.execute("UPDATE employees SET available=1, unavailable_until=NULL WHERE id=?", (employee_id,))
    assert game.send_to_rest(PLAYER_ID, employee_id, 12)["status"] == "cooldown"


def test_rest_waits_for_current_task_instead_of_breaking_workflow(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    courier = first_courier(db)
    employee_id = int(courier["id"])
    with db.connect() as conn:
        conn.execute("UPDATE shops SET balance=500000, reserve_target=0 WHERE player_id=?", (PLAYER_ID,))
        conn.execute("UPDATE employees SET deposit=0, wages_accrued=0 WHERE player_id=?", (PLAYER_ID,))
        conn.execute(
            """INSERT INTO employee_tasks(player_id, employee_id, kind, quantity, completes_at, note)
               VALUES (?, ?, 'place_stashes', 5, ?, 'test')""",
            (PLAYER_ID, employee_id, iso(utcnow() + timedelta(hours=2))),
        )
    assert game.send_to_rest(PLAYER_ID, employee_id, 12)["status"] == "tasks"


def test_harsh_deposit_plan_builds_faster_but_has_relationship_cost(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    courier = first_courier(db)
    employee_id = int(courier["id"])
    with db.connect() as conn:
        conn.execute("UPDATE employees SET loyalty=0.60 WHERE id=?", (employee_id,))
        conn.execute(
            "UPDATE courier_management SET deposit_contribution_pct=50, deposit_target=100000 WHERE employee_id=?",
            (employee_id,),
        )
    hard = game.set_deposit_plan(PLAYER_ID, employee_id, 80)
    assert hard["status"] == "ok"
    with db.connect() as conn:
        after_hard = float(conn.execute(
            "SELECT loyalty FROM employees WHERE id=?", (employee_id,)
        ).fetchone()[0])
    assert after_hard < 0.60

    soft = game.set_deposit_plan(PLAYER_ID, employee_id, 20)
    assert soft["status"] == "ok"
    with db.connect() as conn:
        after_cycle = float(conn.execute(
            "SELECT loyalty FROM employees WHERE id=?", (employee_id,)
        ).fetchone()[0])
    assert after_cycle <= 0.60


def test_individual_deposit_plan_changes_real_order_allocation_and_caps_target(tmp_path):
    db, simulation, _, _ = make_system(tmp_path)
    courier = first_courier(db)
    employee_id = int(courier["id"])
    with db.connect() as conn:
        conn.execute("UPDATE employees SET deposit=59950, deposit_accrued=0 WHERE id=?", (employee_id,))
        conn.execute(
            "UPDATE courier_management SET deposit_target=60000, deposit_contribution_pct=80 WHERE employee_id=?",
            (employee_id,),
        )
    listing = prepare_live_order(db, employee_id)
    with db.connect() as conn:
        simulation._create_retail_order(conn, PLAYER_ID, listing, utcnow())

    with db.connect() as conn:
        order = conn.execute(
            "SELECT * FROM orders WHERE player_id=? AND employee_id=? ORDER BY id DESC LIMIT 1",
            (PLAYER_ID, employee_id),
        ).fetchone()
        employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    assert int(order["employee_deposit_contribution"]) == 50
    assert int(employee["deposit_accrued"]) >= 50


def test_reached_deposit_target_returns_to_team_standard_rate(tmp_path):
    db, simulation, game, _ = make_system(tmp_path)
    courier = first_courier(db)
    employee_id = int(courier["id"])
    with db.connect() as conn:
        conn.execute("UPDATE employees SET deposit=60000, deposit_accrued=0 WHERE id=?", (employee_id,))
        conn.execute(
            "UPDATE courier_management SET deposit_target=60000, deposit_contribution_pct=80 WHERE employee_id=?",
            (employee_id,),
        )
    listing = prepare_live_order(db, employee_id)
    with db.connect() as conn:
        simulation._create_retail_order(conn, PLAYER_ID, listing, utcnow())

    with db.connect() as conn:
        order = conn.execute(
            "SELECT * FROM orders WHERE player_id=? AND employee_id=? ORDER BY id DESC LIMIT 1",
            (PLAYER_ID, employee_id),
        ).fetchone()
    expected = int(round(int(order["employee_cost"]) * game.compensation_policy(PLAYER_ID, "courier")["deposit_contribution_pct"] / 100))
    assert int(order["employee_deposit_contribution"]) == expected


def test_candidate_phone_profile_transfers_on_hire(tmp_path):
    db, _, game, recruitment = make_system(tmp_path)
    campaign = {
        "id": 999,
        "role": "courier",
        "min_deposit": 0,
        "transport_required": 0,
        "experience_required": 0,
    }
    with db.connect() as conn:
        recruitment._create_candidate(conn, PLAYER_ID, campaign, CHANNELS["forums"], utcnow())
        candidate = conn.execute(
            "SELECT * FROM candidates WHERE player_id=? ORDER BY id DESC LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        equipment = conn.execute(
            "SELECT * FROM courier_candidate_profiles WHERE candidate_id=?",
            (candidate["id"],),
        ).fetchone()
    assert equipment is not None
    assert int(equipment["phone_level"]) in {0, 1, 2}
    game.hire_candidate(PLAYER_ID, int(candidate["id"]))
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT id FROM employees WHERE player_id=? AND alias=? ORDER BY id DESC LIMIT 1",
            (PLAYER_ID, candidate["alias"]),
        ).fetchone()
        management = conn.execute(
            "SELECT * FROM courier_management WHERE employee_id=?",
            (employee["id"],),
        ).fetchone()
    assert int(management["phone_level"]) == int(equipment["phone_level"])
