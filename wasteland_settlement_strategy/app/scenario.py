from __future__ import annotations

from datetime import datetime, timedelta

from .actions import (
    AdvanceDay,
    CompleteBuildingUpgrade,
    CompleteTraining,
    ResolveExpedition,
    StartExpedition,
    TrainResident,
    UpgradeBuilding,
)
from .content import ATTRIBUTES, BUILDINGS, INITIAL_RESIDENTS, SECTORS
from .events import (
    BuildingUpgradeStarted,
    BuildingUpgraded,
    DayAdvanced,
    ExpeditionCompleted,
    ExpeditionStarted,
    ResidentLeveled,
    ResidentTrainingCompleted,
    ResidentTrainingStarted,
    SectorMastered,
)
from .model import Building, Expedition, Resident, SettlementState
from .prototype_runtime import ActionSpec, Context, Scenario


def bootstrap_state() -> SettlementState:
    residents = {
        item["id"]: Resident(
            id=item["id"],
            name=item["name"],
            strength=item["strength"],
            agility=item["agility"],
            perception=item["perception"],
            intelligence=item["intelligence"],
        )
        for item in INITIAL_RESIDENTS
    }
    return SettlementState(
        name="Приют-7",
        day=1,
        morale=68,
        resources={
            "food": 72,
            "water": 96,
            "scrap": 42,
            "wire": 10,
            "chem": 6,
            "parts": 12,
            "medicine": 8,
            "ammo": 30,
            "shard": 0,
        },
        residents=residents,
        buildings={
            "water_collector": Building("water_collector", level=1),
            "greenhouse": Building("greenhouse", level=1),
            "infirmary": Building("infirmary", level=0),
            "training_ground": Building("training_ground", level=1),
            "watchtower": Building("watchtower", level=0),
        },
        sector_progress={sector_id: 0 for sector_id in SECTORS},
    )


def xp_to_next_level(level: int) -> int:
    raw = 40 * (1.35 ** (level - 1))
    return max(5, int(round(raw / 5.0) * 5))


def sector_is_unlocked(state: SettlementState, sector_id: str) -> bool:
    sector = SECTORS[sector_id]
    required = sector["requires_mastery"]
    return required is None or state.sector_progress.get(required, 0) >= 100


def _scaled_cost(building_id: str, target_level: int) -> dict[str, int]:
    base = BUILDINGS[building_id]["base_cost"]
    factor = 1 + 0.6 * (target_level - 1)
    return {resource: max(1, int(round(amount * factor))) for resource, amount in base.items()}


def _add_xp(ctx: Context, resident: Resident, amount: int) -> None:
    resident.xp += amount
    while resident.xp >= xp_to_next_level(resident.level):
        resident.xp -= xp_to_next_level(resident.level)
        resident.level += 1
        resident.skill_points += 1
        ctx.emit(ResidentLeveled(resident_id=resident.id, new_level=resident.level))


def start_expedition(ctx: Context, action: StartExpedition) -> None:
    ctx.require(action.sector_id in SECTORS, "unknown_sector")
    ctx.require(1 <= len(action.resident_ids) <= 3, "invalid_squad_size")
    ctx.require(len(set(action.resident_ids)) == len(action.resident_ids), "duplicate_resident")
    ctx.require(sector_is_unlocked(ctx.state, action.sector_id), "sector_locked")

    residents: list[Resident] = []
    for resident_id in action.resident_ids:
        resident = ctx.state.residents.get(resident_id)
        ctx.require(resident is not None, "resident_not_found")
        ctx.require(resident.status == "idle", "resident_busy")
        ctx.require(resident.hp >= 60, "resident_unfit")
        ctx.require(resident.fatigue <= 75, "resident_exhausted")
        residents.append(resident)

    sector = SECTORS[action.sector_id]
    needed = {
        resource: amount * len(residents)
        for resource, amount in sector["supplies_per_resident"].items()
    }
    for resource, amount in needed.items():
        ctx.require(ctx.state.resources.get(resource, 0) >= amount, f"not_enough_{resource}")
    for resource, amount in needed.items():
        ctx.state.resources[resource] -= amount

    ctx.state.expedition_counter += 1
    expedition_id = f"exp-{ctx.state.expedition_counter}"
    resolves_at = ctx.clock.now() + timedelta(minutes=sector["duration_minutes"])
    ctx.state.expeditions[expedition_id] = Expedition(
        id=expedition_id,
        sector_id=action.sector_id,
        resident_ids=action.resident_ids,
        started_at=ctx.clock.now(),
        resolves_at=resolves_at,
    )
    for resident in residents:
        resident.status = "expedition"
        resident.fatigue = min(100, resident.fatigue + 10 + sector["danger"] * 5)

    ctx.schedule(
        ResolveExpedition(expedition_id=expedition_id),
        at=resolves_at,
        idempotency_key=f"timer:resolve:{expedition_id}",
    )
    ctx.emit(
        ExpeditionStarted(
            expedition_id=expedition_id,
            sector_id=action.sector_id,
            resident_ids=action.resident_ids,
        )
    )


def resolve_expedition(ctx: Context, action: ResolveExpedition) -> None:
    expedition = ctx.state.expeditions.get(action.expedition_id)
    ctx.require(expedition is not None, "expedition_not_found")
    ctx.require(expedition.status == "active", "expedition_already_resolved")

    sector = SECTORS[expedition.sector_id]
    residents = [ctx.state.residents[resident_id] for resident_id in expedition.resident_ids]
    team_size = len(residents)
    avg_agility = sum(r.agility for r in residents) / team_size
    avg_perception = sum(r.perception for r in residents) / team_size
    avg_strength = sum(r.strength for r in residents) / team_size
    watchtower_bonus = ctx.state.buildings["watchtower"].level * 0.03

    success_probability = (
        0.52
        + team_size * 0.06
        + avg_perception * 0.035
        + avg_agility * 0.02
        + avg_strength * 0.01
        + watchtower_bonus
        - sector["danger"] * 0.12
    )
    success = ctx.random.chance(
        f"expedition_success:{expedition.id}",
        max(0.15, min(0.92, success_probability)),
    )

    loot: dict[str, int] = {}
    loot_factor = 1.0 if success else 0.35
    perception_bonus = 1.0 + max(0.0, avg_perception - 2) * 0.05
    for resource, (low, high) in sector["loot"].items():
        rolled = ctx.random.randint(f"loot:{expedition.id}:{resource}", low, high)
        amount = int(round(rolled * loot_factor * perception_bonus))
        if amount > 0:
            loot[resource] = amount
            ctx.state.resources[resource] = ctx.state.resources.get(resource, 0) + amount

    progress_before = ctx.state.sector_progress[expedition.sector_id]
    progress_roll = ctx.random.randint(f"progress:{expedition.id}", 24, 38)
    progress_gained = progress_roll if success else max(8, progress_roll // 2)
    ctx.state.sector_progress[expedition.sector_id] = min(100, progress_before + progress_gained)
    if progress_before < 100 <= ctx.state.sector_progress[expedition.sector_id]:
        ctx.emit(SectorMastered(sector_id=expedition.sector_id))

    injured: list[str] = []
    for resident in residents:
        injury_probability = 0.05 + sector["danger"] * 0.08 - resident.agility * 0.012
        if not success:
            injury_probability += 0.16
        if ctx.random.chance(f"injury:{expedition.id}:{resident.id}", injury_probability):
            damage = ctx.random.randint(f"injury_damage:{expedition.id}:{resident.id}", 18, 42)
            resident.hp = max(20, resident.hp - damage)
            resident.status = "injured"
            injured.append(resident.id)
        else:
            resident.status = "idle"

        xp = 10 + sector["danger"] * 8 + (6 if success else 0)
        _add_xp(ctx, resident, xp)

    expedition.status = "completed"
    expedition.success = success
    expedition.loot = loot
    expedition.progress_gained = progress_gained
    expedition.injured_resident_ids = tuple(injured)
    ctx.emit(
        ExpeditionCompleted(
            expedition_id=expedition.id,
            sector_id=expedition.sector_id,
            success=success,
            loot=loot,
            progress_gained=progress_gained,
            injured_resident_ids=tuple(injured),
        )
    )


def upgrade_building(ctx: Context, action: UpgradeBuilding) -> None:
    ctx.require(action.building_id in BUILDINGS, "unknown_building")
    building = ctx.state.buildings[action.building_id]
    definition = BUILDINGS[action.building_id]
    ctx.require(not building.upgrading, "building_busy")
    ctx.require(building.level < definition["max_level"], "building_max_level")

    target_level = building.level + 1
    cost = _scaled_cost(action.building_id, target_level)
    for resource, amount in cost.items():
        ctx.require(ctx.state.resources.get(resource, 0) >= amount, f"not_enough_{resource}")
    for resource, amount in cost.items():
        ctx.state.resources[resource] -= amount

    building.upgrading = True
    duration = definition["base_duration_minutes"] * target_level
    ctx.schedule(
        CompleteBuildingUpgrade(building_id=action.building_id),
        at=ctx.clock.now() + timedelta(minutes=duration),
        idempotency_key=f"timer:building:{action.building_id}:{target_level}",
    )
    ctx.emit(BuildingUpgradeStarted(building_id=action.building_id, target_level=target_level))


def complete_building_upgrade(ctx: Context, action: CompleteBuildingUpgrade) -> None:
    ctx.require(action.building_id in BUILDINGS, "unknown_building")
    building = ctx.state.buildings[action.building_id]
    ctx.require(building.upgrading, "building_not_upgrading")
    building.level += 1
    building.upgrading = False
    ctx.emit(BuildingUpgraded(building_id=action.building_id, new_level=building.level))


def train_resident(ctx: Context, action: TrainResident) -> None:
    ctx.require(action.attribute in ATTRIBUTES, "unknown_attribute")
    resident = ctx.state.residents.get(action.resident_id)
    ctx.require(resident is not None, "resident_not_found")
    ctx.require(resident.status == "idle", "resident_busy")
    ctx.require(resident.skill_points > 0, "no_skill_points")

    resident.status = "training"
    training_level = ctx.state.buildings["training_ground"].level
    duration = max(15, 55 - training_level * 10)
    ctx.schedule(
        CompleteTraining(resident_id=resident.id, attribute=action.attribute),
        at=ctx.clock.now() + timedelta(minutes=duration),
        idempotency_key=f"timer:training:{resident.id}:{resident.level}:{action.attribute}",
    )
    ctx.emit(ResidentTrainingStarted(resident_id=resident.id, attribute=action.attribute))


def complete_training(ctx: Context, action: CompleteTraining) -> None:
    resident = ctx.state.residents.get(action.resident_id)
    ctx.require(resident is not None, "resident_not_found")
    ctx.require(resident.status == "training", "resident_not_training")
    ctx.require(resident.skill_points > 0, "no_skill_points")
    ctx.require(action.attribute in ATTRIBUTES, "unknown_attribute")

    setattr(resident, action.attribute, resident.attribute(action.attribute) + 1)
    resident.skill_points -= 1
    resident.fatigue = min(100, resident.fatigue + 12)
    resident.status = "idle"
    ctx.emit(
        ResidentTrainingCompleted(
            resident_id=resident.id,
            attribute=action.attribute,
            new_value=resident.attribute(action.attribute),
        )
    )


def advance_day(ctx: Context, action: AdvanceDay) -> None:
    del action
    population = len(ctx.state.residents)
    food_before = ctx.state.resources.get("food", 0)
    water_before = ctx.state.resources.get("water", 0)
    morale_before = ctx.state.morale

    food_produced = ctx.state.buildings["greenhouse"].level * 6
    water_produced = ctx.state.buildings["water_collector"].level * 8
    food_needed = population * 2
    water_needed = population * 3

    available_food = food_before + food_produced
    available_water = water_before + water_produced
    food_shortage = max(0, food_needed - available_food)
    water_shortage = max(0, water_needed - available_water)
    ctx.state.resources["food"] = max(0, available_food - food_needed)
    ctx.state.resources["water"] = max(0, available_water - water_needed)

    morale_delta = 1
    if food_shortage:
        morale_delta -= min(10, 2 + food_shortage)
    if water_shortage:
        morale_delta -= min(14, 3 + water_shortage * 2)
    ctx.state.morale = max(0, min(100, ctx.state.morale + morale_delta))

    healing = 5 + ctx.state.buildings["infirmary"].level * 15
    medicine_available = ctx.state.resources.get("medicine", 0)
    for resident in ctx.state.residents.values():
        if resident.status != "expedition" and resident.status != "training":
            resident.fatigue = max(0, resident.fatigue - 25)
        if resident.status == "injured":
            effective_healing = healing
            if ctx.state.buildings["infirmary"].level > 0 and medicine_available > 0:
                medicine_available -= 1
            elif ctx.state.buildings["infirmary"].level > 0:
                effective_healing = 5
            resident.hp = min(100, resident.hp + effective_healing)
            if resident.hp >= 80:
                resident.status = "idle"
    ctx.state.resources["medicine"] = medicine_available

    ctx.state.day += 1
    ctx.emit(
        DayAdvanced(
            day=ctx.state.day,
            food_delta=ctx.state.resources["food"] - food_before,
            water_delta=ctx.state.resources["water"] - water_before,
            morale_delta=ctx.state.morale - morale_before,
        )
    )


settlement_scenario = Scenario(
    name="wasteland_settlement",
    actions={
        StartExpedition: ActionSpec(start_expedition),
        ResolveExpedition: ActionSpec(resolve_expedition),
        UpgradeBuilding: ActionSpec(upgrade_building),
        CompleteBuildingUpgrade: ActionSpec(complete_building_upgrade),
        TrainResident: ActionSpec(train_resident),
        CompleteTraining: ActionSpec(complete_training),
        AdvanceDay: ActionSpec(advance_day),
    },
)


def make_demo_clock() -> datetime:
    return datetime(2026, 8, 25, 12, 0, 0)
