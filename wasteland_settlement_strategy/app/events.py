from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExpeditionStarted:
    expedition_id: str
    sector_id: str
    resident_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExpeditionCompleted:
    expedition_id: str
    sector_id: str
    success: bool
    loot: dict[str, int]
    progress_gained: int
    injured_resident_ids: tuple[str, ...]


@dataclass(frozen=True)
class SectorMastered:
    sector_id: str


@dataclass(frozen=True)
class ResidentLeveled:
    resident_id: str
    new_level: int


@dataclass(frozen=True)
class ResidentTrainingStarted:
    resident_id: str
    attribute: str


@dataclass(frozen=True)
class ResidentTrainingCompleted:
    resident_id: str
    attribute: str
    new_value: int


@dataclass(frozen=True)
class BuildingUpgradeStarted:
    building_id: str
    target_level: int


@dataclass(frozen=True)
class BuildingUpgraded:
    building_id: str
    new_level: int


@dataclass(frozen=True)
class DayAdvanced:
    day: int
    food_delta: int
    water_delta: int
    morale_delta: int
