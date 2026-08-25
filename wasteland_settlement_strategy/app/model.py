from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Resident:
    id: str
    name: str
    strength: int
    agility: int
    perception: int
    intelligence: int
    level: int = 1
    xp: int = 0
    skill_points: int = 0
    hp: int = 100
    fatigue: int = 0
    status: str = "idle"

    def attribute(self, key: str) -> int:
        return int(getattr(self, key))


@dataclass
class Building:
    id: str
    level: int = 0
    upgrading: bool = False


@dataclass
class Expedition:
    id: str
    sector_id: str
    resident_ids: tuple[str, ...]
    started_at: datetime
    resolves_at: datetime
    status: str = "active"
    success: bool | None = None
    loot: dict[str, int] = field(default_factory=dict)
    progress_gained: int = 0
    injured_resident_ids: tuple[str, ...] = ()


@dataclass
class SettlementState:
    name: str
    day: int
    morale: int
    resources: dict[str, int]
    residents: dict[str, Resident]
    buildings: dict[str, Building]
    expeditions: dict[str, Expedition] = field(default_factory=dict)
    sector_progress: dict[str, int] = field(default_factory=dict)
    expedition_counter: int = 0
