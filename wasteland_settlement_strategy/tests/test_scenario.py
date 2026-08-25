from __future__ import annotations

from datetime import datetime

from app.actions import AdvanceDay, StartExpedition, TrainResident, UpgradeBuilding
from app.events import BuildingUpgraded, ExpeditionCompleted, ResidentTrainingCompleted
from app.prototype_runtime import ManualClock, PrototypeEngine
from app.scenario import bootstrap_state, settlement_scenario


def make_engine(seed: int = 7) -> PrototypeEngine:
    return PrototypeEngine(
        scenario=settlement_scenario,
        state=bootstrap_state(),
        clock=ManualClock(datetime(2026, 8, 25, 12, 0, 0)),
        seed=seed,
    )


def test_expedition_is_idempotent_and_resolves_later() -> None:
    engine = make_engine()
    food_before = engine.state.resources["food"]

    first = engine.execute(
        StartExpedition("rust_belt", ("rook", "fox")),
        idempotency_key="callback:1",
    )
    duplicate = engine.execute(
        StartExpedition("rust_belt", ("rook", "fox")),
        idempotency_key="callback:1",
    )

    assert first.status == "success"
    assert duplicate.duplicate is True
    assert engine.state.resources["food"] == food_before - 2
    assert engine.state.residents["rook"].status == "expedition"
    assert len(engine.pending_triggers) == 1

    engine.clock.advance(minutes=20)
    assert engine.run_due() == 1
    assert engine.state.expeditions["exp-1"].status == "completed"
    assert any(isinstance(event, ExpeditionCompleted) for event in engine.event_log)


def test_locked_sector_requires_previous_mastery() -> None:
    engine = make_engine()
    result = engine.execute(
        StartExpedition("plant_12", ("rook",)),
        idempotency_key="callback:locked",
    )
    assert result.status == "rejected"
    assert result.code == "sector_locked"

    engine.state.sector_progress["rust_belt"] = 100
    result = engine.execute(
        StartExpedition("plant_12", ("rook",)),
        idempotency_key="callback:unlocked",
    )
    assert result.status == "success"


def test_building_upgrade_commits_on_timer() -> None:
    engine = make_engine()
    scrap_before = engine.state.resources["scrap"]
    result = engine.execute(UpgradeBuilding("watchtower"), idempotency_key="upgrade:1")

    assert result.status == "success"
    assert engine.state.buildings["watchtower"].level == 0
    assert engine.state.buildings["watchtower"].upgrading is True
    assert engine.state.resources["scrap"] < scrap_before

    engine.clock.advance(minutes=70)
    engine.run_due()
    assert engine.state.buildings["watchtower"].level == 1
    assert engine.state.buildings["watchtower"].upgrading is False
    assert any(isinstance(event, BuildingUpgraded) for event in engine.event_log)


def test_training_spends_skill_point_only_on_completion() -> None:
    engine = make_engine()
    resident = engine.state.residents["rook"]
    resident.skill_points = 1
    before = resident.perception

    result = engine.execute(
        TrainResident("rook", "perception"),
        idempotency_key="train:1",
    )
    assert result.status == "success"
    assert engine.state.residents["rook"].perception == before
    assert engine.state.residents["rook"].status == "training"

    engine.clock.advance(minutes=45)
    engine.run_due()
    trained = engine.state.residents["rook"]
    assert trained.perception == before + 1
    assert trained.skill_points == 0
    assert trained.status == "idle"
    assert any(isinstance(event, ResidentTrainingCompleted) for event in engine.event_log)


def test_day_cycle_consumes_and_produces_resources() -> None:
    engine = make_engine()
    food_before = engine.state.resources["food"]
    water_before = engine.state.resources["water"]

    result = engine.execute(AdvanceDay(), idempotency_key="day:2")

    assert result.status == "success"
    assert engine.state.day == 2
    assert engine.state.resources["food"] == food_before + 6 - 12
    assert engine.state.resources["water"] == water_before + 8 - 18


def test_same_seed_produces_same_expedition_result() -> None:
    left = make_engine(seed=11)
    right = make_engine(seed=11)
    for engine in (left, right):
        engine.execute(StartExpedition("rust_belt", ("rook", "fox")), idempotency_key="exp:1")
        engine.clock.advance(minutes=20)
        engine.run_due()

    a = left.state.expeditions["exp-1"]
    b = right.state.expeditions["exp-1"]
    assert (a.success, a.loot, a.progress_gained, a.injured_resident_ids) == (
        b.success,
        b.loot,
        b.progress_gained,
        b.injured_resident_ids,
    )
