from __future__ import annotations

import random
from dataclasses import replace

from app.staff.couriers.management import CourierManagementSimulationEngine
from app.staff.couriers.recruitment import CourierRecruitmentService
from app.core.database import Database
from app.staff.recruitment import CHANNELS
from app.staff.recruitment import RETAIL_STARTING_DEPOSIT_CAP
from app.engine.simulation import utcnow


PLAYER_ID = 1001


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, speed=1.0, rng=random.Random(91))
    simulation.seed_catalog()
    simulation.ensure_player(PLAYER_ID, "tester")
    recruitment = CourierRecruitmentService(db, speed=1.0, rng=random.Random(92))
    return db, recruitment


def test_retail_minimum_deposit_setting_cannot_exceed_100k(tmp_path):
    _, recruitment = make_system(tmp_path)

    recruitment.update_draft(PLAYER_ID, "role", "courier")
    recruitment.update_draft(PLAYER_ID, "min_deposit", 200_000)
    draft = recruitment.ensure_draft(PLAYER_ID)
    assert int(draft["min_deposit"]) == RETAIL_STARTING_DEPOSIT_CAP

    recruitment.adjust_draft(PLAYER_ID, "min_deposit", 50_000)
    draft = recruitment.ensure_draft(PLAYER_ID)
    assert int(draft["min_deposit"]) == RETAIL_STARTING_DEPOSIT_CAP


def test_generated_retail_candidate_starting_deposit_is_capped(tmp_path):
    db, recruitment = make_system(tmp_path)
    recruitment.update_draft(PLAYER_ID, "role", "courier")
    recruitment.update_draft(PLAYER_ID, "channel", "forums")
    recruitment.update_draft(PLAYER_ID, "min_deposit", RETAIL_STARTING_DEPOSIT_CAP)
    recruitment.start_campaign(PLAYER_ID)

    forced_large_deposit_channel = replace(CHANNELS["forums"], deposit_pool=(120_000,))
    with db.connect() as conn:
        campaign = conn.execute(
            """SELECT * FROM recruitment_campaigns
               WHERE player_id=? AND role='courier'
               ORDER BY id DESC LIMIT 1""",
            (PLAYER_ID,),
        ).fetchone()
        recruitment._create_candidate(conn, PLAYER_ID, campaign, forced_large_deposit_channel, utcnow())
        candidate = conn.execute(
            """SELECT * FROM candidates
               WHERE player_id=? AND role='courier'
               ORDER BY id DESC LIMIT 1""",
            (PLAYER_ID,),
        ).fetchone()

    assert int(candidate["deposit"]) <= RETAIL_STARTING_DEPOSIT_CAP
    assert int(candidate["min_deposit"]) <= RETAIL_STARTING_DEPOSIT_CAP


def test_wholesale_recruitment_keeps_large_deposit_range(tmp_path):
    _, recruitment = make_system(tmp_path)

    recruitment.update_draft(PLAYER_ID, "role", "warehouse")
    recruitment.update_draft(PLAYER_ID, "min_deposit", 600_000)
    draft = recruitment.ensure_draft(PLAYER_ID)

    assert int(draft["min_deposit"]) == 600_000
    assert int(draft["min_deposit"]) > RETAIL_STARTING_DEPOSIT_CAP
