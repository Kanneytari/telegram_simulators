from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StartExpedition:
    sector_id: str
    resident_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResolveExpedition:
    expedition_id: str


@dataclass(frozen=True)
class UpgradeBuilding:
    building_id: str


@dataclass(frozen=True)
class CompleteBuildingUpgrade:
    building_id: str


@dataclass(frozen=True)
class TrainResident:
    resident_id: str
    attribute: str


@dataclass(frozen=True)
class CompleteTraining:
    resident_id: str
    attribute: str


@dataclass(frozen=True)
class AdvanceDay:
    pass
