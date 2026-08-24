from __future__ import annotations

import random
from datetime import timedelta

from app.courier_core import CourierCoreGameService, CourierCoreSimulationEngine
from app.courier_model import (
    TRAIT_METICULOUS,
    TRAIT_OVERHEATS,
    TRAIT_PRESSURE_PROOF,
    TRAIT_SENSITIVE,
)
from app.courier_recruitment import CourierRecruitmentService
from app.db import Database
from app.recruitment import CHANNELS
from app.simulation import iso, utcnow


PLAYER_ID = 1001


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierCoreSimulationEngine(db, speed=1.0, rng=random.Random(901))
    simulation.seed_catalog()
    simulation.ensure_player(PLAYER_ID, "tester")
    game = CourierCoreGameService(db, simulation, rng=random.Random(902))
    recruitment = CourierRecruitmentService(db, speed=1.0, rng=random.Random(903))
    return db, simulation, game, recruitment


def add_courier(db: Database, *, alias: str, pace: float, precision: float, resilience: float, integrity: float, trait: str, stress: float = 10.0) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO employees(
                   player_id, alias, role, deposit, has_car,
                   reliability, attention, honesty, loyalty, stress
               ) VALUES (?, ?, 'courier', 50000, 0, ?, ?, ?, 0.60, ?)""",
            (PLAYER_ID, alias, pace, precision, integrity, stress),
        )
        employee_id = int(cur.lastrowid)
        conn.execute(
            """INSERT INTO courier_profiles(
                   employee_id, player_id, pace, precision, resilience, integrity, trait
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (employee_id, PLAYER_ID, pace, precision, resilience, integrity, trait),
        )
    return employee_id


def test_new_players_receive_canonical_courier_profiles(tmp_path):
    db, _, _, _ = make_system(tmp_path)
    with db.connect() as conn:
        couriers = int(conn.execute(
            "SELECT COUNT(*) FROM employees WHERE player_id=? AND role='courier'",
            (PLAYER_ID,),
        ).fetchone()[0])
        profiles = int(conn.execute(
            "SELECT COUNT(*) FROM courier_profiles WHERE player_id=?",
            (PLAYER_ID,),
        ).fetchone()[0])
        mismatches = int(conn.execute(
            """SELECT COUNT(*) FROM employees e JOIN courier_profiles cp ON cp.employee_id=e.id
               WHERE e.player_id=? AND e.role='courier'
                 AND (ABS(e.reliability-cp.pace)>0.00001
                      OR ABS(e.attention-cp.precision)>0.00001
                      OR ABS(e.honesty-cp.integrity)>0.00001)""",
            (PLAYER_ID,),
        ).fetchone()[0])
    assert couriers > 0
    assert profiles == couriers
    assert mismatches == 0


def test_candidate_generation_produces_distinct_hidden_archetypes(tmp_path):
    db, _, _, recruitment = make_system(tmp_path)
    channel = CHANNELS["forums"]
    campaign = {
        "id": 999,
        "role": "courier",
        "min_deposit": 0,
        "transport_required": 0,
        "experience_required": 0,
    }
    now = utcnow()
    with db.connect() as conn:
        for _ in range(35):
            recruitment._create_candidate(conn, PLAYER_ID, campaign, channel, now)
        rows = conn.execute(
            """SELECT cp.* FROM courier_candidate_profiles cp
               JOIN candidates c ON c.id=cp.candidate_id
               WHERE c.player_id=?""",
            (PLAYER_ID,),
        ).fetchall()
    traits = {row["trait"] for row in rows}
    paces = [float(row["pace"]) for row in rows]
    precisions = [float(row["precision"]) for row in rows]
    assert len(traits) >= 4
    assert max(paces) - min(paces) >= 0.25
    assert max(precisions) - min(precisions) >= 0.20


def test_hiring_preserves_hidden_candidate_personality(tmp_path):
    db, _, game, recruitment = make_system(tmp_path)
    campaign = {
        "id": 1000,
        "role": "courier",
        "min_deposit": 0,
        "transport_required": 0,
        "experience_required": 0,
    }
    with db.connect() as conn:
        recruitment._create_candidate(conn, PLAYER_ID, campaign, CHANNELS["forums"], utcnow())
        candidate = conn.execute(
            "SELECT * FROM candidates WHERE player_id=? AND status='open' ORDER BY id DESC LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        hidden = conn.execute(
            "SELECT * FROM courier_candidate_profiles WHERE candidate_id=?",
            (candidate["id"],),
        ).fetchone()
    result = game.hire_candidate(PLAYER_ID, int(candidate["id"]))
    assert "принят" in result
    with db.connect() as conn:
        employee = conn.execute(
            "SELECT * FROM employees WHERE player_id=? AND alias=? ORDER BY id DESC LIMIT 1",
            (PLAYER_ID, candidate["alias"]),
        ).fetchone()
        profile = conn.execute(
            "SELECT * FROM courier_profiles WHERE employee_id=?",
            (employee["id"],),
        ).fetchone()
    assert profile is not None
    assert profile["trait"] == hidden["trait"]
    assert float(profile["pace"]) == float(hidden["pace"])
    assert float(profile["precision"]) == float(hidden["precision"])
    assert float(profile["resilience"]) == float(hidden["resilience"])
    assert float(profile["integrity"]) == float(hidden["integrity"])


def test_fast_and_slow_couriers_get_materially_different_task_times(tmp_path):
    db, simulation, _, _ = make_system(tmp_path)
    fast_id = add_courier(
        db,
        alias="Fast",
        pace=0.97,
        precision=0.76,
        resilience=0.80,
        integrity=0.90,
        trait=TRAIT_OVERHEATS,
    )
    slow_id = add_courier(
        db,
        alias="Slow",
        pace=0.54,
        precision=0.97,
        resilience=0.88,
        integrity=0.95,
        trait=TRAIT_METICULOUS,
    )
    future = iso(utcnow() + timedelta(days=2))
    with db.connect() as conn:
        for employee_id in (fast_id, slow_id):
            conn.execute(
                """INSERT INTO employee_tasks(
                       player_id, employee_id, kind, quantity, completes_at, note
                   ) VALUES (?, ?, 'prepare_positions', 36, ?, 'test')""",
                (PLAYER_ID, employee_id, future),
            )
        simulation._process_tasks(conn, PLAYER_ID, utcnow())
        fast = conn.execute(
            "SELECT planned_game_hours FROM courier_task_metrics WHERE employee_id=?",
            (fast_id,),
        ).fetchone()
        slow = conn.execute(
            "SELECT planned_game_hours FROM courier_task_metrics WHERE employee_id=?",
            (slow_id,),
        ).fetchone()
    assert fast is not None and slow is not None
    assert float(fast["planned_game_hours"]) < float(slow["planned_game_hours"]) * 0.72


def test_stress_penalizes_fragile_courier_much_more_than_pressure_proof_one(tmp_path):
    db, simulation, _, _ = make_system(tmp_path)
    fragile_id = add_courier(
        db,
        alias="Fragile",
        pace=0.88,
        precision=0.90,
        resilience=0.45,
        integrity=0.95,
        trait=TRAIT_SENSITIVE,
        stress=90,
    )
    tough_id = add_courier(
        db,
        alias="Tough",
        pace=0.84,
        precision=0.82,
        resilience=0.97,
        integrity=0.90,
        trait=TRAIT_PRESSURE_PROOF,
        stress=90,
    )
    with db.connect() as conn:
        fragile = conn.execute("SELECT * FROM courier_profiles WHERE employee_id=?", (fragile_id,)).fetchone()
        tough = conn.execute("SELECT * FROM courier_profiles WHERE employee_id=?", (tough_id,)).fetchone()
    fragile_precision = simulation._effective_precision(fragile, 90)
    tough_precision = simulation._effective_precision(tough, 90)
    fragile_pace = simulation._effective_pace(fragile, 90)
    tough_pace = simulation._effective_pace(tough, 90)
    assert fragile_precision < 0.65
    assert tough_precision > 0.79
    assert fragile_pace + 0.18 < tough_pace


def test_profile_reveals_history_gradually_without_exposing_hidden_trait(tmp_path):
    db, _, game, _ = make_system(tmp_path)
    employee_id = add_courier(
        db,
        alias="Observed",
        pace=0.95,
        precision=0.93,
        resilience=0.85,
        integrity=0.36,
        trait="conceals",
    )
    early = game.employee_details(PLAYER_ID, employee_id)
    assert early is not None
    assert "Темп: <b>пока мало данных</b>" in early
    assert "conceals" not in early
    assert "порядоч" not in early.lower()

    with db.connect() as conn:
        conn.execute(
            """UPDATE courier_profiles
               SET prep_tasks=5, prep_units=120, prep_game_hours=8,
                   pace_observation_sum=4.65, pace_observation_count=5,
                   observed_orders=20, rating_sum=96
               WHERE employee_id=?""",
            (employee_id,),
        )
        conn.execute("UPDATE employees SET jobs_done=20 WHERE id=?", (employee_id,))
    mature = game.employee_details(PLAYER_ID, employee_id)
    assert mature is not None
    assert "Темп: <b>очень высокий</b>" in mature
    assert "Работает быстрее большинства сотрудников." in mature
    assert "conceals" not in mature


def test_high_stress_can_cause_visible_work_breakdown_for_fragile_courier(tmp_path):
    db, simulation, _, _ = make_system(tmp_path)
    employee_id = add_courier(
        db,
        alias="Breakdown",
        pace=0.86,
        precision=0.88,
        resilience=0.40,
        integrity=0.90,
        trait=TRAIT_SENSITIVE,
        stress=96,
    )

    class ForcedRng:
        def random(self):
            return 0.0

        def choice(self, values):
            return values[0]

    simulation.rng = ForcedRng()
    with db.connect() as conn:
        created = simulation._simulate_courier_problem_conn(conn, PLAYER_ID, 12.0, utcnow())
        employee = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
        profile = conn.execute("SELECT * FROM courier_profiles WHERE employee_id=?", (employee_id,)).fetchone()
        notice = conn.execute(
            """SELECT * FROM inbox WHERE player_id=? AND kind='courier_problem'
               AND json_extract(payload_json, '$.employee_id')=? ORDER BY id DESC LIMIT 1""",
            (PLAYER_ID, employee_id),
        ).fetchone()
    assert created == 1
    assert int(employee["available"]) == 0
    assert int(profile["negative_events"]) == 1
    assert notice is not None


def test_customer_rating_differs_materially_between_precise_and_sloppy_couriers(tmp_path):
    db, simulation, _, _ = make_system(tmp_path)
    precise_id = add_courier(
        db,
        alias="Precise",
        pace=0.65,
        precision=0.98,
        resilience=0.90,
        integrity=0.95,
        trait=TRAIT_METICULOUS,
    )
    sloppy_id = add_courier(
        db,
        alias="Sloppy",
        pace=0.96,
        precision=0.62,
        resilience=0.55,
        integrity=0.90,
        trait=TRAIT_OVERHEATS,
    )
    simulation.rng = random.Random(7)
    precise = simulation._courier_rating({"id": precise_id, "stress": 15.0, "loyalty": 0.60})
    sloppy = simulation._courier_rating({"id": sloppy_id, "stress": 70.0, "loyalty": 0.60})
    assert precise >= 4
    assert sloppy <= 3
    assert precise - sloppy >= 1


def test_live_order_records_rating_and_courier_observation(tmp_path):
    db, simulation, _, _ = make_system(tmp_path)
    with db.connect() as conn:
        courier = conn.execute(
            "SELECT * FROM employees WHERE player_id=? AND role='courier' AND active=1 ORDER BY id LIMIT 1",
            (PLAYER_ID,),
        ).fetchone()
        batch = conn.execute(
            """SELECT * FROM batches WHERE player_id=? AND responsible_employee_id IS NOT NULL
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
                courier["id"],
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
                courier["id"],
                batch["product_id"],
                batch["unit_cost"],
                batch["quality"],
            ),
        )
        before = conn.execute(
            "SELECT observed_orders FROM courier_profiles WHERE employee_id=?",
            (courier["id"],),
        ).fetchone()
        result = simulation._create_retail_order(conn, PLAYER_ID, listing, utcnow())
        after = conn.execute(
            "SELECT observed_orders FROM courier_profiles WHERE employee_id=?",
            (courier["id"],),
        ).fetchone()
        rating = conn.execute(
            "SELECT COUNT(*) FROM order_ratings WHERE player_id=? AND employee_id=?",
            (PLAYER_ID, courier["id"]),
        ).fetchone()[0]
    assert result in {True, False}
    assert int(after["observed_orders"]) == int(before["observed_orders"]) + 1
    assert int(rating) >= 1
