from app.staff_relationships import (
    SALES_ACTIVITY_MULTIPLIER,
    StaffRelationshipSimulationEngine,
)
from app.wholesale_compensation import WholesaleCompensationSimulationEngine


def test_live_sales_window_is_tripled_without_changing_parent_formula(monkeypatch):
    captured = {}

    def fake_parent_sales(self, conn, player_id, shop, sim_hours, now):
        captured["sim_hours"] = sim_hours
        return 7, 2

    monkeypatch.setattr(
        WholesaleCompensationSimulationEngine,
        "_simulate_sales",
        fake_parent_sales,
        raising=False,
    )

    engine = object.__new__(StaffRelationshipSimulationEngine)
    result = engine._simulate_sales(None, 1001, None, 2.0, None)

    assert SALES_ACTIVITY_MULTIPLIER == 3.0
    assert captured["sim_hours"] == 6.0
    assert result == (7, 2)


def test_sales_multiplier_never_turns_negative_time_into_sales(monkeypatch):
    captured = {}

    def fake_parent_sales(self, conn, player_id, shop, sim_hours, now):
        captured["sim_hours"] = sim_hours
        return 0, 0

    monkeypatch.setattr(
        WholesaleCompensationSimulationEngine,
        "_simulate_sales",
        fake_parent_sales,
        raising=False,
    )

    engine = object.__new__(StaffRelationshipSimulationEngine)
    engine._simulate_sales(None, 1001, None, -1.0, None)

    assert captured["sim_hours"] == 0.0
