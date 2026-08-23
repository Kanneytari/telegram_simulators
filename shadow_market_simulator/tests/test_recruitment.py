from __future__ import annotations

import random

from app.db import Database
from app.nightshift import NightshiftSimulationEngine
from app.recruitment_runtime import NightshiftRecruitmentService


def make_recruitment(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = NightshiftSimulationEngine(db, speed=1.0, rng=random.Random(11))
    simulation.ensure_player(1001, "tester")
    service = NightshiftRecruitmentService(db, speed=1.0, rng=random.Random(42))
    return db, simulation, service


def test_campaign_spends_money_and_waits_for_responses(tmp_path):
    db, _, service = make_recruitment(tmp_path)
    quote = service.quote(1001)
    with db.connect() as conn:
        before = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]

    result = service.start_campaign(1001)

    with db.connect() as conn:
        after = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM recruitment_campaigns WHERE player_id=1001 AND status='active'"
        ).fetchone()[0]
        source_candidates = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE player_id=1001 AND status='open' AND campaign_id IS NOT NULL"
        ).fetchone()[0]

    assert after == before - int(quote["cost"])
    assert active == 1
    assert source_candidates == 0
    assert "Размещение запущено" in result


def test_more_volume_and_duration_reduce_unit_ad_cost(tmp_path):
    _, _, service = make_recruitment(tmp_path)
    base = service.quote(1001)

    service.update_draft(1001, "traffic_multiplier", 4)
    service.update_draft(1001, "duration_hours", 24)
    large = service.quote(1001)

    assert large["cost"] > base["cost"]
    assert large["unit_cost"] < base["unit_cost"]
    assert large["discount_pct"] > base["discount_pct"]


def test_low_pay_reduces_expected_applicants(tmp_path):
    _, _, service = make_recruitment(tmp_path)
    service.update_draft(1001, "pay_per_job", 1000)
    low = service.quote(1001)
    service.update_draft(1001, "pay_per_job", 1900)
    high = service.quote(1001)
    assert high["expected"] > low["expected"]


def test_large_deposit_reduces_applicants_but_improves_generated_quality(tmp_path):
    db, _, service = make_recruitment(tmp_path)
    service.update_draft(1001, "min_deposit", 10000)
    low_requirement = service.quote(1001)
    service.update_draft(1001, "min_deposit", 90000)
    high_requirement = service.quote(1001)
    assert high_requirement["expected"] < low_requirement["expected"]

    # Generate two deterministic campaigns and compare average hidden reliability.
    service.update_draft(1001, "min_deposit", 10000)
    service.start_campaign(1001)
    service.fast_forward(1001, 30)
    with db.connect() as conn:
        low_rows = conn.execute(
            "SELECT reliability FROM candidates WHERE player_id=1001 AND campaign_id=1"
        ).fetchall()

    service.update_draft(1001, "channel", "graffiti")
    service.update_draft(1001, "min_deposit", 90000)
    service.start_campaign(1001)
    service.fast_forward(1001, 30)
    with db.connect() as conn:
        high_rows = conn.execute(
            "SELECT reliability FROM candidates WHERE player_id=1001 AND campaign_id=2"
        ).fetchall()

    if low_rows and high_rows:
        low_avg = sum(row[0] for row in low_rows) / len(low_rows)
        high_avg = sum(row[0] for row in high_rows) / len(high_rows)
        assert high_avg > low_avg


def test_tick_style_fast_forward_creates_campaign_candidates(tmp_path):
    db, _, service = make_recruitment(tmp_path)
    service.start_campaign(1001)
    created = service.fast_forward(1001, 30)

    with db.connect() as conn:
        active = conn.execute(
            "SELECT COUNT(*) FROM recruitment_campaigns WHERE player_id=1001 AND status='active'"
        ).fetchone()[0]
        candidates = conn.execute(
            "SELECT * FROM candidates WHERE player_id=1001 AND status='open' AND campaign_id IS NOT NULL"
        ).fetchall()
        notifications = conn.execute(
            "SELECT COUNT(*) FROM inbox WHERE player_id=1001 AND kind='recruitment_result' AND status='open'"
        ).fetchone()[0]

    assert active == 0
    assert len(candidates) == created
    assert notifications == 1


def test_player_reset_cascades_recruitment_campaigns_and_draft(tmp_path):
    db, _, service = make_recruitment(tmp_path)
    service.start_campaign(1001)
    with db.connect() as conn:
        conn.execute("DELETE FROM shops WHERE player_id=1001")
        campaigns = conn.execute(
            "SELECT COUNT(*) FROM recruitment_campaigns WHERE player_id=1001"
        ).fetchone()[0]
        drafts = conn.execute(
            "SELECT COUNT(*) FROM recruitment_drafts WHERE player_id=1001"
        ).fetchone()[0]
    assert campaigns == 0
    assert drafts == 0
