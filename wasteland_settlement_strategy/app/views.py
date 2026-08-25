from __future__ import annotations

from .content import BUILDINGS, RESOURCES, SECTORS
from .model import SettlementState
from .scenario import sector_is_unlocked, xp_to_next_level


def settlement_dashboard(state: SettlementState) -> str:
    idle = sum(1 for resident in state.residents.values() if resident.status == "idle")
    away = sum(1 for resident in state.residents.values() if resident.status == "expedition")
    injured = sum(1 for resident in state.residents.values() if resident.status == "injured")
    lines = [
        f"☢️ {state.name} · день {state.day}",
        f"🙂 Мораль: {state.morale}/100",
        f"👥 Жители: {len(state.residents)} · свободны {idle} · в вылазке {away} · ранены {injured}",
        "",
        "Запасы:",
    ]
    for resource_id in ("food", "water", "scrap", "parts", "medicine", "ammo"):
        meta = RESOURCES[resource_id]
        lines.append(f"{meta['icon']} {meta['name']}: {state.resources.get(resource_id, 0)}")

    lines.extend(["", "Объекты:"])
    for building_id, building in state.buildings.items():
        meta = BUILDINGS[building_id]
        suffix = " · строится" if building.upgrading else ""
        lines.append(f"{meta['icon']} {meta['name']}: ур. {building.level}{suffix}")

    lines.extend(["", "Сектора:"])
    for sector_id, sector in SECTORS.items():
        if sector_is_unlocked(state, sector_id):
            lines.append(f"{sector['icon']} {sector['name']}: освоение {state.sector_progress[sector_id]}/100")
        else:
            required = SECTORS[sector["requires_mastery"]]["name"]
            lines.append(f"🔒 {sector['name']}: освоить {required}")
    return "\n".join(lines)


def residents_view(state: SettlementState) -> str:
    lines = ["Жители:"]
    for resident in state.residents.values():
        lines.append(
            f"• {resident.name} · ур. {resident.level} · HP {resident.hp} · "
            f"усталость {resident.fatigue} · {resident.status} · "
            f"💪{resident.strength} 🏃{resident.agility} 👁{resident.perception} 🧠{resident.intelligence} · "
            f"XP {resident.xp}/{xp_to_next_level(resident.level)} · очки {resident.skill_points}"
        )
    return "\n".join(lines)
