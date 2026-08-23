from __future__ import annotations

import json
import math
from datetime import timedelta

from .recruitment import CHANNELS, RecruitmentService
from .runtime import ROLE_MARKET_PAY
from .simulation import clamp, iso, parse_dt, utcnow


ROLE_TITLES = {"courier": "Розничный сотрудник", "warehouse": "Оптовый сотрудник"}


class NightshiftRecruitmentService(RecruitmentService):
    """Recruitment model for configurable retail and wholesale vacancies."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        with self.db.connect() as conn:
            self._ensure_column(conn, "recruitment_drafts", "role", "TEXT NOT NULL DEFAULT 'courier'")
            self._ensure_column(conn, "recruitment_campaigns", "role", "TEXT NOT NULL DEFAULT 'courier'")
            conn.execute(
                "UPDATE recruitment_drafts SET pay_per_job=? WHERE role='courier' AND pay_per_job<500",
                (ROLE_MARKET_PAY["courier"],),
            )
            conn.execute(
                "UPDATE recruitment_campaigns SET pay_per_job=? WHERE role='courier' AND pay_per_job<500 AND status='active'",
                (ROLE_MARKET_PAY["courier"],),
            )

    @staticmethod
    def _ensure_column(conn, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
                remaining_real = max(0.0, (parse_dt(campaign["resolves_at"]) - now).total_seconds())
                remaining_game = remaining_real * old
                new_real = remaining_game / multiplier
                conn.execute(
                    "UPDATE recruitment_campaigns SET resolves_at=? WHERE id=?",
                    (iso(now + timedelta(seconds=new_real)), campaign["id"]),
                )
            conn.execute("UPDATE settings SET time_multiplier=? WHERE player_id=?", (multiplier, player_id))
        return old, multiplier

    def ensure_draft(self, player_id: int, channel: str | None = None):
        draft = super().ensure_draft(player_id, channel)
        role = draft["role"] if "role" in draft.keys() else "courier"
        market = ROLE_MARKET_PAY.get(role, ROLE_MARKET_PAY["courier"])
        if int(draft["pay_per_job"]) < 500:
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE recruitment_drafts SET pay_per_job=? WHERE player_id=?",
                    (market, player_id),
                )
            draft = super().ensure_draft(player_id, channel)
        return draft

    def update_draft(self, player_id: int, field: str, value) -> None:
        if field == "role":
            if value not in ROLE_TITLES:
                raise ValueError("Unsupported role")
            self.ensure_draft(player_id)
            market = ROLE_MARKET_PAY[value]
            default_deposit = 25_000 if value == "courier" else 300_000
            with self.db.connect() as conn:
                conn.execute(
                    """UPDATE recruitment_drafts
                       SET role=?, pay_per_job=?, min_deposit=?, updated_at=CURRENT_TIMESTAMP
                       WHERE player_id=?""",
                    (value, market, default_deposit, player_id),
                )
            return
        super().update_draft(player_id, field, value)

    def adjust_draft(self, player_id: int, field: str, delta: int) -> None:
        draft = self.ensure_draft(player_id)
        current = int(draft[field])
        role = draft["role"]
        if field == "pay_per_job":
            if role == "warehouse":
                value = max(3000, min(15000, current + delta))
                value = int(round(value / 250) * 250)
            else:
                value = max(800, min(8000, current + delta))
                value = int(round(value / 50) * 50)
        elif field == "min_deposit":
            if role == "warehouse":
                value = max(100_000, min(2_000_000, current + delta))
                value = int(round(value / 50_000) * 50_000)
            else:
                value = max(0, min(200_000, current + delta))
                value = int(round(value / 5000) * 5000)
        elif field == "deposit_contribution_pct":
            value = max(0, min(40, current + delta))
            value = int(round(value / 5) * 5)
        else:
            raise ValueError("Unsupported adjustable field")
        super().update_draft(player_id, field, value)

    def quote(self, player_id: int, draft=None) -> dict[str, float | int | str]:
        draft = draft or self.ensure_draft(player_id)
        channel = self.get_channel(draft["channel"])
        role = draft["role"]
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

        market_pay = ROLE_MARKET_PAY[role]
        net_pay = pay * (1.0 - contribution / 100.0)
        market_net = market_pay * 0.90
        pay_factor = clamp((net_pay / market_net) ** 1.55, 0.18, 1.90)

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
            deposit_factor = clamp(math.exp(-(min_deposit - deposit_floor) / deposit_scale), 0.18, 1.0)

        requirement_factor = 1.0
        if int(draft["car_required"]):
            requirement_factor *= 0.58
        if int(draft["experience_required"]):
            requirement_factor *= 0.55

        expected = channel.base_leads * (blocks ** 0.82) * pay_factor * deposit_factor * requirement_factor * role_flow
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
            "role": role,
        }

    def start_campaign(self, player_id: int) -> str:
        self.advance(player_id)
        draft = self.ensure_draft(player_id)
        channel = CHANNELS[draft["channel"]]
        quote = self.quote(player_id, draft)
        now = utcnow()
        with self.db.connect() as conn:
            active = conn.execute(
                """SELECT 1 FROM recruitment_campaigns
                   WHERE player_id=? AND channel=? AND role=? AND status='active'""",
                (player_id, channel.code, draft["role"]),
            ).fetchone()
            if active:
                return f"{channel.title}: размещение для этой роли уже активно."
            shop = conn.execute("SELECT balance FROM shops WHERE player_id=?", (player_id,)).fetchone()
            if not shop:
                return "Сначала начни игру командой /start."
            if int(shop["balance"]) < int(quote["cost"]):
                return f"Недостаточно денег. Нужно {int(quote['cost']):,} ₽."
            duration_hours = int(draft["duration_hours"])
            resolves_at = now + timedelta(hours=duration_hours / self.effective_speed(player_id))
            conn.execute(
                "UPDATE shops SET balance=balance-?, total_profit=total_profit-? WHERE player_id=?",
                (quote["cost"], quote["cost"], player_id),
            )
            conn.execute(
                "INSERT INTO ledger(player_id, amount, kind, note) VALUES (?, ?, 'recruitment', ?)",
                (player_id, -int(quote["cost"]), f"{channel.title} · {ROLE_TITLES[draft['role']]} · x{draft['traffic_multiplier']} · {duration_hours} ч"),
            )
            conn.execute(
                """INSERT INTO recruitment_campaigns(
                       player_id, channel, role, cost, resolves_at,
                       traffic_multiplier, duration_hours, pay_per_job, min_deposit,
                       deposit_contribution_pct, car_required, experience_required,
                       expected_min, expected_max
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    player_id, channel.code, draft["role"], quote["cost"], iso(resolves_at),
                    draft["traffic_multiplier"], duration_hours, draft["pay_per_job"], draft["min_deposit"],
                    draft["deposit_contribution_pct"], draft["car_required"], draft["experience_required"],
                    quote["expected_min"], quote["expected_max"],
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

    def campaign_status_text(self, player_id: int) -> str:
        campaigns = self.active_campaigns(player_id)
        if not campaigns:
            return "Активных размещений нет."
        now = utcnow()
        lines = []
        speed = self.effective_speed(player_id)
        for campaign in campaigns:
            channel = CHANNELS[campaign["channel"]]
            real_hours = max(0.0, (parse_dt(campaign["resolves_at"]) - now).total_seconds() / 3600.0)
            sim_hours = real_hours * speed
            eta = "<1 ч" if sim_hours < 1 else f"~{sim_hours:.1f} ч"
            lines.append(f"{channel.icon} {ROLE_TITLES[campaign['role']]} · x{campaign['traffic_multiplier']} · {eta}")
        return "<b>Активные размещения</b>\n" + "\n".join(lines)

    def _create_candidate(self, conn, player_id: int, campaign, channel, now) -> None:
        role = campaign["role"]
        min_deposit = int(campaign["min_deposit"])
        offered_pay = int(campaign["pay_per_job"])
        contribution = int(campaign["deposit_contribution_pct"])
        car_required = bool(campaign["car_required"])
        experience_required = bool(campaign["experience_required"])

        deposit_reference = 300_000 if role == "warehouse" else 25_000
        quality_scale = 900_000 if role == "warehouse" else 100_000
        deposit_quality_bonus = clamp((min_deposit - deposit_reference) / quality_scale * 0.12, -0.05, 0.10)
        requirement_quality_bonus = (0.02 if car_required else 0.0) + (0.05 if experience_required else 0.0)
        quality_bonus = channel.quality_bonus + deposit_quality_bonus + requirement_quality_bonus

        alias = self.rng.choice(["Гриф", "Луна", "Рысь", "Штрих", "Кедр", "Ноль", "Фаза", "Север", "Ток"]) + str(self.rng.randint(10, 99))
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
            pool = channel.deposit_pool
        available_deposits = [value for value in pool if value >= min_deposit]
        deposit = self.rng.choice(available_deposits) if available_deposits else min_deposit + (100_000 if role == "warehouse" else 25_000)

        market = ROLE_MARKET_PAY[role]
        performance_premium = ((reliability + attention) / 2.0 - 0.70) * 0.45
        experience_premium = experience_level * 0.08
        desired = int(market * (0.92 + performance_premium + experience_premium) * channel.pay_multiplier)
        desired += self.rng.randint(-250 if role == "warehouse" else -100, 400 if role == "warehouse" else 150)
        step = 250 if role == "warehouse" else 50
        desired = max(3000 if role == "warehouse" else 1000, int(round(desired / step) * step))

        experience_text = {0: "без подтверждённого опыта", 1: "есть опыт", 2: "опыт выглядит сильным"}[experience_level]
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
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                player_id, alias, role, desired, deposit, has_car,
                reliability, attention, honesty, loyalty, summary,
                iso(now + timedelta(hours=10 / self.effective_speed(player_id))),
                campaign["id"], channel.code, offered_pay, min_deposit, contribution, experience_level,
            ),
        )
