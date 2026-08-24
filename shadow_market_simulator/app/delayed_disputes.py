from __future__ import annotations

from .procurement_market import ProcurementMarketGameService, ProcurementMarketSimulationEngine


class DelayedDisputeSimulationEngine(ProcurementMarketSimulationEngine):
    """Current dispute simulation. Employee explanations are immediate."""


class DelayedDisputeGameService(ProcurementMarketGameService):
    """Current dispute service with immediate employee explanations."""
