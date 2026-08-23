from __future__ import annotations

import math

from .recruitment import MARKET_PAY_PER_JOB, RecruitmentService
from .runtime import ROLE_MARKET_PAY
from .simulation import clamp, iso
from datetime import timedelta


class NightshiftRecruitmentService(RecruitmentService):
    """Recruitment model calibrated to the current retail wage scale."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE recruitment_drafts SET pay_per_job=? WHERE pay_per_job<500",
                (ROLE_MARKET_PAY["courier"],),
            )
            conn.execute(
                "UPDATE recruitment_campaigns SET pay_per_job=? WHERE pay_per_job<500 AND status='active'",
                (ROLE_MARKET_PAY["courier"],),
            )

    def ensure_draft(self, player_id: int, channel: str | None = None):
        draft = super().ensure_draft(player_id, channel)
        if int(draft["pay_per_job"]) < 500:
            self.update_draft(player_id, "pay_per_job", ROLE_MARKET_PAY["courier"])
            draft = super().ensure_draft(player_id, channel)
        return draft

    def quote(self, player_id: int, draft=None) -> dict[str, float | int]:
        draft = draft or self.ensure_draft(player_id)
        channel = self.get_channel(draft["channel"])
        volume = int(draft["traffic_multiplier"])
        duration = int(draft["duration_hours"])
        pay = int(draft["pay_per_job"])
        min_deposit = int(draft["min_deposit"])
        contribution = int(draft["deposit_contribution_pct"])

        blocks = volume * duration / 4.0
        volume_discount = {1: 1.00, 2: 0.92, 4: 0.82}.get(volume, 1.0)
        duration_discount = {4: 1.00, 12: 0.90, 24: 0.82}.get(duration, 1.0)
        undiscounted = channel.base_cost * blocks
        cost = int(round(undiscounted * volume_discount * duration_discount / 100.0) * 100)
        discount_pct = max(0.0, (1.0 - cost / undiscounted) * 100.0) if undiscounted else 0.0

        market_pay = ROLE_MARKET_PAY["courier"]
        net_pay = pay * (1.0 - contribution / 100.0)
        market_net = market_pay * 0.90
        pay_factor = clamp((net_pay / market_net) ** 1.55, 0.18, 1.90)

        if min_deposit <= 15000:
            deposit_factor = 1.14
        else:
            deposit_factor = clamp(math.exp(-(min_deposit - 15000) / 85000.0), 0.22, 1.0)

        requirement_factor = 1.0
        if int(draft["car_required"]):
            requirement_factor *= 0.58
        if int(draft["experience_required"]):
            requirement_factor *= 0.55

        expected = (
            channel.base_leads
            * (blocks ** 0.82)
            * pay_factor
            * deposit_factor
            * requirement_factor
        )
        low = max(0, int(math.floor(expected * 0.65)))
        high = max(low + 1, int(math.ceil(expected * 1.35)))
        return {
            "cost": cost,
            "undiscounted": int(round(undiscounted)),
            "discount_pct": discount_pct,
            "expected": expected,
            "expected_min": low,
            "expected_max": high,
            "net_pay": int(round(net_pay)),
            "unit_cost": int(round(cost / max(blocks, 1.0))),
            "market_pay": market_pay,
        }

    def _create_candidate(self, conn, player_id: int, campaign, channel, now) -> None:
        min_deposit = int(campaign["min_deposit"])
        offered_pay = int(campaign["pay_per_job"])
        contribution = int(campaign["deposit_contribution_pct"])
        car_required = bool(campaign["car_required"])
        experience_required = bool(campaign["experience_required"])

        deposit_quality_bonus = clamp((min_deposit - 25000) / 100000.0 * 0.12, -0.05, 0.08)
        requirement_quality_bonus = (0.02 if car_required else 0.0) + (0.05 if experience_required else 0.0)
        quality_bonus = channel.quality_bonus + deposit_quality_bonus + requirement_quality_bonus

        alias = self.rng.choice(
            ["Гриф", "Луна", "Рысь", "Штрих", "Кедр", "Ноль", "Фаза", "Север", "Ток"]
        ) + str(self.rng.randint(10, 99))
        reliability = clamp(self.rng.uniform(0.52, 0.90) + quality_bonus, 0.38, 0.99)
        attention = clamp(self.rng.uniform(0.52, 0.92) + quality_bonus * 0.9, 0.38, 0.99)
        honesty = clamp(self.rng.uniform(0.48, 0.94) + quality_bonus * 0.45, 0.35, 0.99)
        loyalty = clamp(self.rng.uniform(0.42, 0.86) + quality_bonus * 0.25, 0.30, 0.96)

        if experience_required:
            experience_level = self.rng.choice([1, 1, 2])
        elif channel.code == "forums":
            experience_level = self.rng.choice([0, 1, 1, 2])
        elif channel.code == "graffiti":
            experience_level = self.rng.choice([0, 0, 1, 1])
        else:
            experience_level = self.rng.choice([0, 0, 0, 1])

        has_car = 1 if car_required else int(self.rng.random() < channel.car_probability)
        available_deposits = [value for value in channel.deposit_pool if value >= min_deposit]
        deposit = self.rng.choice(available_deposits) if available_deposits else min_deposit + self.rng.choice([0, 10000, 25000])

        market = ROLE_MARKET_PAY["courier"]
        performance_premium = ((reliability + attention) / 2.0 - 0.70) * 0.45
        experience_premium = experience_level * 0.08
        desired = int(market * (0.92 + performance_premium + experience_premium) * channel.pay_multiplier)
        desired += self.rng.randint(-100, 150)
        desired = max(1000, min(2600, int(round(desired / 50) * 50)))

        experience_text = {
            0: "без подтверждённого опыта",
            1: "есть опыт",
            2: "опыт выглядит сильным",
        }[experience_level]
        summary = (
            f"Источник: {channel.title}\n"
            f"Опыт: {experience_text}\n"
            f"Автомобиль: {'есть' if has_car else 'нет'}\n"
            f"Готовый депозит: {deposit:,} ₽"
        )
        conn.execute(
            """INSERT INTO candidates(
                   player_id, alias, role, desired_pay, deposit, has_car,
                   reliability, attention, honesty, loyalty, summary, expires_at,
                   campaign_id, source_channel, offered_pay, min_deposit,
                   deposit_contribution_pct, experience_level
               ) VALUES (?, ?, 'courier', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                player_id,
                alias,
                desired,
                deposit,
                has_car,
                reliability,
                attention,
                honesty,
                loyalty,
                summary,
                iso(now + timedelta(hours=10 / self.effective_speed(player_id))),
                campaign["id"],
                channel.code,
                offered_pay,
                min_deposit,
                contribution,
                experience_level,
            ),
        )
