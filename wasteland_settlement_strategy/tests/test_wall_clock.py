from datetime import datetime, timedelta

from app.actions import StartExpedition
from app.prototype_runtime import ManualClock, PrototypeEngine
from app.scenario import bootstrap_state, settlement_scenario


def test_wall_clock_can_finish_scheduled_expedition() -> None:
    started_at = datetime(2026, 8, 25, 12, 0, 0)
    clock = ManualClock(started_at)
    engine = PrototypeEngine(
        scenario=settlement_scenario,
        state=bootstrap_state(),
        clock=clock,
        seed=1,
    )

    result = engine.execute(
        StartExpedition(sector_id="rust_belt", resident_ids=("rook",)),
        idempotency_key="expedition:start",
    )

    assert result.status == "success"
    assert len(engine.pending_triggers) == 1
    expedition = next(iter(engine.state.expeditions.values()))
    assert expedition.status == "active"

    clock.advance_to(started_at + timedelta(minutes=21))
    assert engine.run_due() == 1
    assert engine.state.expeditions[expedition.id].status == "completed"
    assert len(engine.pending_triggers) == 0


def test_clock_never_moves_backwards() -> None:
    started_at = datetime(2026, 8, 25, 12, 0, 0)
    clock = ManualClock(started_at)
    clock.advance_to(started_at + timedelta(minutes=10))
    clock.advance_to(started_at + timedelta(minutes=5))
    assert clock.now() == started_at + timedelta(minutes=10)
