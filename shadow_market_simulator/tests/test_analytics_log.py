from __future__ import annotations

import random

from app.analytics_log import AnalyticsLogger, normalize_callback
from app.courier_management import CourierManagementGameService, CourierManagementSimulationEngine
from app.courier_recruitment import CourierRecruitmentService
from app.db import Database


def make_system(tmp_path):
    db = Database(str(tmp_path / "game.db"))
    db.init()
    simulation = CourierManagementSimulationEngine(db, rng=random.Random(51))
    simulation.seed_catalog()
    game = CourierManagementGameService(db, simulation, rng=random.Random(52))
    recruitment = CourierRecruitmentService(db, rng=random.Random(53))
    analytics = AnalyticsLogger(db)
    analytics.install()
    simulation.ensure_player(1001, "tester")
    return db, simulation, game, recruitment, analytics


def test_callback_normalization_removes_high_cardinality_ids():
    assert normalize_callback("workflow:alloc:123:456:10") == "callback.workflow.alloc.*.*.*"
    assert normalize_callback("menu:team") == "callback.menu.team"


def test_player_action_log_contains_state_snapshot(tmp_path):
    db, _, _, _, analytics = make_system(tmp_path)
    analytics.log(
        1001,
        "player_action",
        "callback.menu.team",
        "telegram",
        payload={"callback_data": "menu:team"},
    )
    with db.connect() as conn:
        row = conn.execute(
            """SELECT * FROM analytics_events
               WHERE player_id=1001 AND event_kind='player_action'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    assert row is not None
    assert row["event_name"] == "callback.menu.team"
    assert row["run_id"] is not None
    assert row["balance"] is not None
    assert row["rating"] is not None
    assert row["time_multiplier"] == 1.0


def test_gameplay_mutations_are_logged_by_triggers(tmp_path):
    db, _, game, _, _ = make_system(tmp_path)
    with db.connect() as conn:
        listing = conn.execute(
            "SELECT id FROM listings WHERE player_id=1001 ORDER BY id LIMIT 1"
        ).fetchone()
    game.change_listing_price(1001, int(listing["id"]), 5)
    with db.connect() as conn:
        row = conn.execute(
            """SELECT * FROM analytics_events
               WHERE player_id=1001 AND event_name='listing_price_changed'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    assert row is not None
    assert row["source"] == "storefront"
    assert row["entity_type"] == "listing"


def test_analytics_history_survives_progress_reset(tmp_path):
    db, _, _, _, analytics = make_system(tmp_path)
    analytics.log(1001, "player_action", "command.reset", "telegram")
    with db.connect() as conn:
        run_before = conn.execute(
            "SELECT created_at FROM shops WHERE player_id=1001"
        ).fetchone()[0]
        conn.execute("DELETE FROM shops WHERE player_id=1001")
        reset_event = conn.execute(
            """SELECT * FROM analytics_events
               WHERE player_id=1001 AND event_name='progress_reset'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM analytics_events WHERE player_id=1001"
        ).fetchone()[0]
    assert reset_event is not None
    assert reset_event["run_id"] == run_before
    assert count > 1


def test_recruitment_campaign_is_logged(tmp_path):
    db, _, _, recruitment, _ = make_system(tmp_path)
    recruitment.update_draft(1001, "role", "courier")
    recruitment.update_draft(1001, "traffic_multiplier", 1)
    recruitment.update_draft(1001, "duration_hours", 4)
    result = recruitment.start_campaign(1001)
    assert "запущено" in result.lower()
    with db.connect() as conn:
        event = conn.execute(
            """SELECT * FROM analytics_events
               WHERE player_id=1001 AND event_name='recruitment_campaign_started'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    assert event is not None
    assert event["source"] == "recruitment"
