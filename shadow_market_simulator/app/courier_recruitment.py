from __future__ import annotations

from datetime import timedelta

from .courier_model import COURIER_SCHEMA, generate_courier_blueprint
from .recruitment_runtime import NightshiftRecruitmentService, ROLE_TITLES
from .simulation import clamp, iso


class CourierRecruitmentService(NightshiftRecruitmentService):
    """Recruitment with deliberately distinct hidden courier personalities."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.executescript(COURIER_SCHEMA)

    def _create_candidate(self, conn, player_id: int, campaign, channel, now) -> None:
        if campaign["role"] != "courier":
            super()._create_candidate(conn, player_id, campaign, channel, now)
            return

        min_deposit = int(campaign["min_deposit"])
        car_required = bool(campaign["car_required"])
        experience_required = bool(campaign["experience_required"])

        deposit_quality_bonus = clamp((min_deposit - 25_000) / 100_000.0 * 0.10, -0.05, 0.08)
        requirement_quality_bonus = (0.02 if car_required else 0.0) + (0.05 if experience_required else 0.0)
        quality_bonus = channel.quality_bonus + deposit_quality_bonus + requirement_quality_bonus

        if experience_required:
            experience_level = self.rng.choice([1, 1, 2])
        elif channel.code == "forums":
            experience_level = self.rng.choice([0, 1, 1, 2])
        elif channel.code == "graffiti":
            experience_level = self.rng.choice([0, 0, 1, 1])
        else:
            experience_level = self.rng.choice([0, 0, 0, 1])

        blueprint = generate_courier_blueprint(
            self.rng,
            quality_bonus=quality_bonus,
            experience_level=experience_level,
        )
        alias = self.rng.choice(
            ["Гриф", "Луна", "Рысь", "Штрих", "Кедр", "Ноль", "Фаза", "Север", "Ток", "Сова", "Мята"]
        ) + str(self.rng.randint(10, 99))
        has_car = 1 if car_required else int(self.rng.random() < channel.car_probability)

        # Low-deposit candidates are intentional: they create a meaningful choice
        # between immediate financial safety and long-term employee potential.
        deposit_pool = (5_000, 10_000, 15_000, 25_000, 40_000, 60_000, 90_000, 100_000)
        available = [value for value in deposit_pool if value >= min_deposit]
        deposit = self.rng.choice(available) if available else min(100_000, max(min_deposit, 25_000))

        starting_loyalty = clamp(
            self.rng.uniform(0.48, 0.66) + experience_level * 0.015 + quality_bonus * 0.15,
            0.38,
            0.78,
        )
        experience_text = {
            0: "без подтверждённого опыта",
            1: "есть опыт",
            2: "опыт выглядит сильным",
        }[experience_level]
        summary = (
            f"Источник: {channel.title}\n"
            f"Роль: {ROLE_TITLES['courier']}\n"
            f"Опыт: {experience_text}\n"
            f"Автомобиль: {'есть' if has_car else 'нет'}\n"
            f"Готовый депозит: {deposit:,} ₽"
        )

        cur = conn.execute(
            """INSERT INTO candidates(
                   player_id, alias, role, desired_pay, deposit, has_car,
                   reliability, attention, honesty, loyalty, summary, expires_at,
                   campaign_id, source_channel, offered_pay, min_deposit,
                   deposit_contribution_pct, experience_level
               ) VALUES (?, ?, 'courier', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0, ?)""",
            (
                player_id,
                alias,
                deposit,
                has_car,
                blueprint.pace,
                blueprint.precision,
                blueprint.integrity,
                starting_loyalty,
                summary,
                iso(now + timedelta(hours=10 / self.effective_speed(player_id))),
                campaign["id"],
                channel.code,
                min_deposit,
                experience_level,
            ),
        )
        conn.execute(
            """INSERT INTO courier_candidate_profiles(
                   candidate_id, pace, precision, resilience, integrity, trait
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                int(cur.lastrowid),
                blueprint.pace,
                blueprint.precision,
                blueprint.resilience,
                blueprint.integrity,
                blueprint.trait,
            ),
        )
