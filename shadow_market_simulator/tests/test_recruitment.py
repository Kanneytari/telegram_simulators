from __future__ import annotations

import random

from app.db import Database
from app.recruitment import CHANNELS, RecruitmentService
from app.simulation import SimulationEngine


def make_recruitment(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = SimulationEngine(db, speed=1.0, rng=random.Random(11))
    simulation.ensure_player(1001, "tester")
    service = RecruitmentService(db, speed=1.0, rng=random.Random(42))
    return db, service


def test_campaign_spends_money_and_waits_for_responses(tmp_path):
    db, service = make_recruitment(tmp_path)
    channel = CHANNELS["stickers"]
    with db.connect() as conn:
        before = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]

    result = service.start_campaign(1001, "stickers")

    with db.connect() as conn:
        after = conn.execute("SELECT balance FROM shops WHERE player_id=1001").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM recruitment_campaigns WHERE player_id=1001 AND status='active'"
        ).fetchone()[0]
        source_candidates = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE player_id=1001 AND status='open' AND summary LIKE 'Источник:%'"
        ).fetchone()[0]

    assert after == before - channel.cost
    assert active == 1
    assert source_candidates == 0
    assert "кампания запущена" in result


def test_tick_style_fast_forward_creates_source_candidates(tmp_path):
    db, service = make_recruitment(tmp_path)
    service.start_campaign(1001, "stickers")

    created = service.fast_forward(1001, 8)

    with db.connect() as conn:
        active = conn.execute(
            "SELECT COUNT(*) FROM recruitment_campaigns WHERE player_id=1001 AND status='active'"
        ).fetchone()[0]
        candidates = conn.execute(
            "SELECT * FROM candidates WHERE player_id=1001 AND status='open' AND summary LIKE 'Источник:%'"
        ).fetchall()
        notifications = conn.execute(
            "SELECT COUNT(*) FROM inbox WHERE player_id=1001 AND kind='recruitment_result' AND status='open'"
        ).fetchone()[0]

    assert created >= CHANNELS["stickers"].min_candidates
    assert active == 0
    assert len(candidates) == created
    assert notifications == 1
    assert all("Расклейщики стикеров" in row["summary"] for row in candidates)


def test_same_channel_cannot_be_stacked(tmp_path):
    _, service = make_recruitment(tmp_path)
    service.start_campaign(1001, "forums")
    result = service.start_campaign(1001, "forums")
    assert "уже запущена" in result


def test_player_reset_cascades_recruitment_campaigns(tmp_path):
    db, service = make_recruitment(tmp_path)
    service.start_campaign(1001, "graffiti")
    with db.connect() as conn:
        conn.execute("DELETE FROM shops WHERE player_id=1001")
        campaigns = conn.execute(
            "SELECT COUNT(*) FROM recruitment_campaigns WHERE player_id=1001"
        ).fetchone()[0]
    assert campaigns == 0
