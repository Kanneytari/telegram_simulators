from __future__ import annotations

import random
from dataclasses import replace

from app.catalog_extension import ExpandedCatalogSimulationEngine
from app.db import Database
from app.recruitment import CHANNELS
from app.recruitment_deposit_cap import (
    RETAIL_STARTING_DEPOSIT_CAP,
    RetailDepositCappedRecruitmentService,
)
from app.simulation import utcnow


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = ExpandedCatalogSimulationEngine(db, speed=1.0, rng=random.Random(91))
    simulation.seed_catalog()
    simulation.ensure_player(1001, "tester")
    recruitment = RetailDepositCappedRecruitmentService(db, speed=1.0, rng=random.Random(92))
    return db, recruitment


def test_retail_minimum_deposit_setting_cannot_exceed_100k(tmp_path):
    _, recruitment = make_system(tmp_path)

    recruitment.update_draft(1001, "role", "courier")
    recruitment.update_draft(1001, "min_deposit", 200_000)
    draft = recruitment.ensure_draft(1001)
    assert int(draft["min_deposit"]) == RETAIL_STARTING_DEPOSIT_CAP

    recruitment.adjust_draft(1001, "min_deposit", 50_000)
    draft = recruitment.ensure_draft(1001)
    assert int(draft["min_deposit"]) == RETAIL_STARTING_DEPOSIT_CAP


def test_generated_retail_candidate_starting_deposit_is_capped(tmp_path):
    db, recruitment = make_system(tmp_path)
    recruitment.update_draft(1001, "role", "courier")
    recruitment.update_draft(1001, "channel", "forums")
    recruitment.update_draft(1001, "min_deposit", RETAIL_STARTING_DEPOSIT_CAP)
    recruitment.start_campaign(1001)

    forced_large_deposit_channel = replace(
        CHANNELS["forums"],
        deposit_pool=(120_000,),
    )
    with db.connect() as conn:
        campaign = conn.execute(
            """SELECT * FROM recruitment_campaigns
               WHERE player_id=1001 AND role='courier'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        recruitment._create_candidate(conn, 1001, campaign, forced_large_deposit_channel, utcnow())
        candidate = conn.execute(
            """SELECT * FROM candidates
               WHERE player_id=1001 AND role='courier'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()

    assert int(candidate["deposit"]) == RETAIL_STARTING_DEPOSIT_CAP
    assert int(candidate["min_deposit"]) <= RETAIL_STARTING_DEPOSIT_CAP
    assert "Готовый депозит: 100,000 ₽" in candidate["summary"]


def test_wholesale_recruitment_keeps_large_deposit_range(tmp_path):
    _, recruitment = make_system(tmp_path)

    recruitment.update_draft(1001, "role", "warehouse")
    recruitment.update_draft(1001, "min_deposit", 600_000)
    draft = recruitment.ensure_draft(1001)

    assert int(draft["min_deposit"]) == 600_000
    assert int(draft["min_deposit"]) > RETAIL_STARTING_DEPOSIT_CAP
