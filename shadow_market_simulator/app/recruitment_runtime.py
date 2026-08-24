from __future__ import annotations

import math
from datetime import timedelta

from .compensation import DEFAULT_POLICIES, _ensure_policy_conn
from .recruitment import CHANNELS, RecruitmentService
from .simulation import clamp, iso, parse_dt, utcnow


ROLE_TITLES = {
    "courier": "Розничный сотрудник",
    "warehouse": "Оптовый сотрудник",
}
RETAIL_STARTING_DEPOSIT_CAP = 100_000


class NightshiftRecruitmentService(RecruitmentService):
    """Recruitment driven by the shop-wide compensation policy.

    Compensation is never negotiated inside a vacancy. A campaign advertises the
    current terms for the selected role, and candidate volume reacts to how attractive
    those terms are.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            pass
            for row in conn.execute("SELECT player_id FROM shops").fetchall():
                for role in DEFAULT_POLICIES:
                    _ensure_policy_conn(conn, int(row["player_id"]), role)

    def effective_speed(self, player_id: int) -> float:
        return self.player_multiplier(player_id)

    def set_player_multiplier(self, player_id: int, multiplier: float) -> tuple[float, float]:
        multiplier = max(0.1, min(240.0, float(multiplier)))
        now = utcnow()
        old = self.player_multiplier(player_id)
        with self.db.connect() as conn:
            campaigns = conn.execute(
                "SELECT id, resolves_at FROM recruitment_campaigns WHERE player_id=? AND status='active'",
                (player_id,),
            ).fetchall()
            for campaign in campaigns:
                remaining_real = max(
                    0.0,
                    (parse_dt(campaign["resolves_at"]) - now).total_seconds(),
                )
                remaining_game = remaining_real * old
                new_real = remaining_game / multiplier
                conn.execute(
                    "UPDATE recruitment_campaigns SET resolves_at=? WHERE id=?",
                    (iso(now + timedelta(seconds=new_real)), campaign["id"]),
                )
            conn.execute(
                "UPDATE settings SET time_multiplier=? WHERE player_id=?",
                (multiplier, player_id),
            )
        return old, multiplier

    def _policy(self, player_id: int, role: str) -> dict[str, int]:
        defaults = DEFAULT_POLICIES[role]
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT fixed_fee, base_rate_bps, risk_rate_bps,
                          deposit_contribution_pct
                   FROM staff_compensation_policies
                   WHERE player_id=? AND role=?""",
                (player_id, role),
            ).fetchone()
        if not row:
            return dict(defaults)
        return {
            "fixed_fee": int(row["fixed_fee"]),
            "base_rate_bps": int(row["base_rate_bps"]),
            "risk_rate_bps": int(row["risk_rate_bps"]),
            "deposit_contribution_pct": int(row["deposit_contribution_pct"]),
        }

    @staticmethod
    def _policy_score(role: str, policy: dict[str, int]) -> float:
        if role == "courier":
            gross = int(policy["fixed_fee"]) + 10_000 * int(policy["base_rate_bps"]) / 10_000.0
        else:
            gross = (
                500_000 * int(policy["base_rate_bps"]) / 10_000.0
                + 150_000 * int(policy["risk_rate_bps"]) / 10_000.0
            )
        return gross * (1.0 - int(policy["deposit_contribution_pct"]) / 200.0)

    def ensure_draft(self, player_id: int, channel: str | None = None):
        draft = super().ensure_draft(player_id, channel)
        role = draft["role"]
        min_deposit = int(draft["min_deposit"])
        if role == "courier":
            min_deposit = min(RETAIL_STARTING_DEPOSIT_CAP, min_deposit)
        if int(draft["min_deposit"]) != min_deposit:
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE recruitment_drafts SET min_deposit=? WHERE player_id=?",
                    (min_deposit, player_id),
                )
            draft = super().ensure_draft(player_id, channel)
        return draft

    def update_draft(self, player_id: int, field: str, value) -> None:
        if field == "role":
            if value not in ROLE_TITLES:
                raise ValueError("Unsupported role")
            self.ensure_draft(player_id)
            default_deposit = 25_000 if value == "courier" else 300_000
            with self.db.connect() as conn:
                conn.execute(
                    """UPDATE recruitment_drafts
                       SET role=?, min_deposit=?, updated_at=CURRENT_TIMESTAMP
                       WHERE player_id=?""",
                    (value, default_deposit, player_id),
                )
            return
        if field not in {
            "channel",
            "traffic_multiplier",
            "duration_hours",
            "min_deposit",
            "car_required",
            "experience_required",
        }:
            raise ValueError("Unsupported draft field")
        if field == "min_deposit":
            role = self.ensure_draft(player_id)["role"]
            if role == "courier":
                value = min(RETAIL_STARTING_DEPOSIT_CAP, int(value))
        super().update_draft(player_id, field, value)

    def adjust_draft(self, player_id: int, field: str, delta: int) -> None:
        if field != "min_deposit":
            raise ValueError("Unsupported adjustable field")
        draft = self.ensure_draft(player_id)
        current = int(draft["min_deposit"])
        if draft["role"] == "warehouse":
            value = max(100_000, min(2_000_000, current + delta))
            value = int(round(value / 50_000) * 50_000)
        else:
            value = max(0, min(RETAIL_STARTING_DEPOSIT_CAP, current + delta))
            value = int(round(value / 5_000) * 5_000)
        super().update_draft(player_id, "min_deposit", value)

    def quote(self, player_id: int, draft=None) -> dict[str, float | int | str]:
        draft = draft or self.ensure_draft(player_id)
        channel = self.get_channel(draft["channel"])
        role = draft["role"]
        volume = int(draft["traffic_multiplier"])
        duration = int(draft["duration_hours"])
        min_deposit = int(draft["min_deposit"])
        policy = self._policy(player_id, role)

        blocks = volume * duration / 4.0
        volume_discount = {1: 1.00, 2: 0.92, 4: 0.82}.get(volume, 1.0)
        duration_discount = {4: 1.00, 12: 0.90, 24: 0.82}.get(duration, 1.0)
        undiscounted = channel.base_cost * blocks
        cost = int(round(undiscounted * volume_discount * duration_discount / 100.0) * 100)
        discount_pct = max(0.0, (1.0 - cost / undiscounted) * 100.0) if undiscounted else 0.0

        score = self._policy_score(role, policy)
        benchmark = self._policy_score(role, DEFAULT_POLICIES[role])
        pay_factor = clamp((score / max(benchmark, 1.0)) ** 1.45, 0.25, 1.90)

        if role == "warehouse":
            deposit_floor = 250_000
            deposit_scale = 700_000.0
            role_flow = 0.48
        else:
            deposit_floor = 15_000
            deposit_scale = 85_000.0
            role_flow = 1.0
        if min_deposit <= deposit_floor:
            deposit_factor = 1.10
        else:
            deposit_factor = clamp(
                math.exp(-(min_deposit - deposit_floor) / deposit_scale),
                0.18,
                1.0,
            )

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
            * role_flow
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
            "unit_cost": int(round(cost / max(blocks, 1.0))),
            "role": role,
            "policy": policy,
        }

    def start_campaign(self, player_id: int) -> str:
        self.advance(player_id)
        draft = self.ensure_draft(player_id)
        channel = CHANNELS[draft["channel"]]
        quote = self.quote(player_id, draft)
        policy = quote["policy"]
        now = utcnow()
        with self.db.connect() as conn:
            active = conn.execute(
                """SELECT 1 FROM recruitment_campaigns
                   WHERE player_id=? AND channel=? AND role=? AND status='active'""",
                (player_id, channel.code, draft["role"]),
            ).fetchone()
            if active:
                return f"{channel.title}: размещение для этой роли уже активно."
            shop = conn.execute(
                "SELECT balance FROM shops WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if not shop:
                return "Сначала начни игру командой /start."
            if int(shop["balance"]) < int(quote["cost"]):
                return f"Недостаточно денег. Нужно {int(quote['cost']):,} ₽."

            duration_hours = int(draft["duration_hours"])
            resolves_at = now + timedelta(
                hours=duration_hours / self.effective_speed(player_id)
            )
            conn.execute(
                "UPDATE shops SET balance=balance-?, total_profit=total_profit-? WHERE player_id=?",
                (quote["cost"], quote["cost"], player_id),
            )
            conn.execute(
                "INSERT INTO ledger(player_id, amount, kind, note) VALUES (?, ?, 'recruitment', ?)",
                (
                    player_id,
                    -int(quote["cost"]),
                    f"{channel.title} · {ROLE_TITLES[draft['role']]} · "
                    f"x{draft['traffic_multiplier']} · {duration_hours} ч",
                ),
            )
            conn.execute(
                """INSERT INTO recruitment_campaigns(
                       player_id, channel, role, cost, resolves_at,
                       traffic_multiplier, duration_hours, pay_per_job, min_deposit,
                       deposit_contribution_pct, car_required, experience_required,
                       expected_min, expected_max, terms_fixed_fee,
                       terms_base_rate_bps, terms_risk_rate_bps, terms_deposit_pct
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    player_id,
                    channel.code,
                    draft["role"],
                    quote["cost"],
                    iso(resolves_at),
                    draft["traffic_multiplier"],
                    duration_hours,
                    draft["min_deposit"],
                    draft["car_required"],
                    draft["experience_required"],
                    quote["expected_min"],
                    quote["expected_max"],
                    policy["fixed_fee"],
                    policy["base_rate_bps"],
                    policy["risk_rate_bps"],
                    policy["deposit_contribution_pct"],
                ),
            )
        return (
            f"<b>{channel.icon} Размещение запущено</b>\n\n"
            f"Роль: {ROLE_TITLES[draft['role']]}\n"
            f"Охват: x{draft['traffic_multiplier']}\n"
            f"Срок: {draft['duration_hours']} игровых ч\n"
            f"Стоимость: <b>{int(quote['cost']):,} ₽</b>\n\n"
            f"Ожидаемые отклики: {quote['expected_min']}-{quote['expected_max']}"
        )

    def advance(self, player_id: int, now=None) -> int:
        created = super().advance(player_id, now)
        if created >= 0:
            with self.db.connect() as conn:
                rows = conn.execute(
                    """SELECT id, body FROM inbox
                       WHERE player_id=? AND status='open' AND kind='recruitment_result'
                       ORDER BY id DESC LIMIT 10""",
                    (player_id,),
                ).fetchall()
                for row in rows:
                    body = str(row["body"] or "")
                    old = "Открой раздел «Кандидаты», чтобы посмотреть отклики."
                    if old in body:
                        conn.execute(
                            "UPDATE inbox SET body=? WHERE id=?",
                            (
                                body.replace(
                                    old,
                                    "Открой это сообщение и нажми «Смотреть кандидатов».",
                                ),
                                row["id"],
                            ),
                        )
        return created

    def campaign_status_text(self, player_id: int) -> str:
        campaigns = self.active_campaigns(player_id)
        if not campaigns:
            return "Активных размещений нет."
        now = utcnow()
        lines = []
        speed = self.effective_speed(player_id)
        for campaign in campaigns:
            channel = CHANNELS[campaign["channel"]]
            real_hours = max(
                0.0,
                (parse_dt(campaign["resolves_at"]) - now).total_seconds() / 3600.0,
            )
            sim_hours = real_hours * speed
            eta = "менее 1 ч" if sim_hours < 1 else f"~{sim_hours:.1f} ч"
            lines.append(
                f"{channel.icon} {ROLE_TITLES[campaign['role']]} · "
                f"x{campaign['traffic_multiplier']} · {eta}"
            )
        return "<b>Активные размещения</b>\n" + "\n".join(lines)

    def _create_candidate(self, conn, player_id: int, campaign, channel, now) -> None:
        role = campaign["role"]
        min_deposit = int(campaign["min_deposit"])
        car_required = bool(campaign["car_required"])
        experience_required = bool(campaign["experience_required"])

        deposit_reference = 300_000 if role == "warehouse" else 25_000
        quality_scale = 900_000 if role == "warehouse" else 100_000
        deposit_quality_bonus = clamp(
            (min_deposit - deposit_reference) / quality_scale * 0.12,
            -0.05,
            0.10,
        )
        requirement_quality_bonus = (
            (0.02 if car_required else 0.0)
            + (0.05 if experience_required else 0.0)
        )
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
        if role == "warehouse":
            pool = (200_000, 300_000, 450_000, 650_000, 900_000, 1_200_000, 1_600_000)
        else:
            pool = tuple(
                value
                for value in channel.deposit_pool
                if value <= RETAIL_STARTING_DEPOSIT_CAP
            )
        available = [value for value in pool if value >= min_deposit]
        if available:
            deposit = self.rng.choice(available)
        elif role == "warehouse":
            deposit = min_deposit + 100_000
        else:
            deposit = min(RETAIL_STARTING_DEPOSIT_CAP, max(min_deposit, 25_000))

        experience_text = {
            0: "без подтверждённого опыта",
            1: "есть опыт",
            2: "опыт выглядит сильным",
        }[experience_level]
        summary = (
            f"Источник: {channel.title}\n"
            f"Роль: {ROLE_TITLES[role]}\n"
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
               ) VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0, ?)""",
            (
                player_id,
                alias,
                role,
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
                min_deposit,
                experience_level,
            ),
        )
