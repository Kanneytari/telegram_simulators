from __future__ import annotations

from dataclasses import dataclass

from .simulation import clamp




TRAIT_OVERHEATS = "overheats"
TRAIT_METICULOUS = "meticulous"
TRAIT_STEADY = "steady"
TRAIT_PRESSURE_PROOF = "pressure_proof"
TRAIT_CONCEALS = "conceals"
TRAIT_SENSITIVE = "sensitive"
TRAIT_LEARNER = "learner"


@dataclass(frozen=True)
class CourierBlueprint:
    pace: float
    precision: float
    resilience: float
    integrity: float
    trait: str


_ARCHETYPES = (
    # Fast and productive, but pressure turns into visible quality problems.
    (TRAIT_OVERHEATS, (0.90, 0.99), (0.62, 0.78), (0.45, 0.64), (0.66, 0.94)),
    # Slow, deliberate specialist. Strong quality is bought with time.
    (TRAIT_METICULOUS, (0.50, 0.68), (0.92, 0.99), (0.76, 0.94), (0.82, 0.99)),
    # No spectacular edge, but consistently above average in normal work.
    (TRAIT_STEADY, (0.70, 0.83), (0.80, 0.91), (0.74, 0.90), (0.76, 0.96)),
    # Built for sustained load; quality is only average-good.
    (TRAIT_PRESSURE_PROOF, (0.76, 0.89), (0.70, 0.84), (0.93, 0.99), (0.66, 0.93)),
    # Attractive performance with a material hidden trust problem.
    (TRAIT_CONCEALS, (0.84, 0.97), (0.78, 0.92), (0.64, 0.84), (0.34, 0.58)),
    # Good worker in normal conditions, unusually reactive to pressure.
    (TRAIT_SENSITIVE, (0.77, 0.90), (0.82, 0.94), (0.42, 0.60), (0.82, 0.98)),
    # Cheap-looking novice with room to become a valuable long-term employee.
    (TRAIT_LEARNER, (0.57, 0.73), (0.72, 0.86), (0.78, 0.94), (0.82, 0.99)),
)


def generate_courier_blueprint(rng, *, quality_bonus: float = 0.0, experience_level: int = 0) -> CourierBlueprint:
    trait, pace_range, precision_range, resilience_range, integrity_range = rng.choice(_ARCHETYPES)
    experience = max(0, min(2, int(experience_level)))

    pace = rng.uniform(*pace_range)
    precision = rng.uniform(*precision_range)
    resilience = rng.uniform(*resilience_range)
    integrity = rng.uniform(*integrity_range)

    # Better channels and experience improve the professional side, but do not
    # erase personality. Integrity intentionally receives only a tiny shift.
    professional_bonus = clamp(float(quality_bonus), -0.08, 0.10)
    pace += professional_bonus * 0.45 + experience * 0.018
    precision += professional_bonus * 0.70 + experience * 0.025
    resilience += professional_bonus * 0.25 + experience * 0.012
    integrity += professional_bonus * 0.08

    if trait == TRAIT_LEARNER and experience:
        pace += 0.025 * experience
        precision += 0.030 * experience

    return CourierBlueprint(
        pace=clamp(pace, 0.40, 0.99),
        precision=clamp(precision, 0.40, 0.995),
        resilience=clamp(resilience, 0.35, 0.995),
        integrity=clamp(integrity, 0.28, 0.995),
        trait=trait,
    )


def condition_band(stress: float) -> tuple[str, str]:
    value = float(stress)
    if value >= 78:
        return "🔴", "на пределе"
    if value >= 52:
        return "🟡", "напряжён"
    return "🟢", "в порядке"


def pace_band(score: float) -> str:
    value = float(score)
    if value >= 0.91:
        return "очень высокий"
    if value >= 0.80:
        return "высокий"
    if value >= 0.68:
        return "средний"
    return "низкий"


def relationship_band(loyalty: float) -> str:
    value = float(loyalty)
    if value >= 0.82:
        return "🟢 очень хорошее"
    if value >= 0.67:
        return "🟢 хорошее"
    if value >= 0.50:
        return "⚪ нормальное"
    if value >= 0.36:
        return "🟡 прохладное"
    return "🔴 плохое"
