from __future__ import annotations

from typing import Any


__all__ = ["NightshiftSimulationMixin", "PlayerSimulationMixin"]


def __getattr__(name: str) -> Any:
    if name == "NightshiftSimulationMixin":
        from .timers import NightshiftSimulationMixin

        return NightshiftSimulationMixin
    if name == "PlayerSimulationMixin":
        from .player_time import PlayerSimulationMixin

        return PlayerSimulationMixin
    raise AttributeError(name)
