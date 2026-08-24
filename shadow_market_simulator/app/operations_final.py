from __future__ import annotations

from .operations import OperationsGameService, OperationsSimulationEngine


class FinalOperationsSimulationEngine(OperationsSimulationEngine):
    """Final operations layer kept as a stable inheritance boundary."""


class FinalOperationsGameService(OperationsGameService):
    """Final operations service kept as a stable inheritance boundary."""
