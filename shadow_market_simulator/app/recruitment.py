from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from datetime import timedelta

from .db import Database
from .simulation import clamp, iso, parse_dt, utcnow


MARKET_PAY_PER_JOB = 220
STANDARD_CONTRIBUTION_PCT = 10
VOLUME_OPTIONS = (1, 2, 4)
DURATION_OPTIONS = (4, 12, 24)


@dataclass(frozen=True)
class RecruitmentChannel:
    code: str
    title: str
    icon: str
    base_cost: int
    base_leads: float
    quality_bonus: float
    pay_multiplier: float
    car_probability: float
    deposit_pool: tuple[int, ...]
    description: str


CHANNELS: dict[str, RecruitmentChannel] = {
    "stickers": RecruitmentChannel(
        code="stickers",
        title="Расклейщики стикеров",
        icon="🟨",
        base_cost=3000,
        base_leads=2.5,
        quality_bonus=-0.03,
        pay_multiplier=0.96,
        car_probability=0.32,
        deposit_pool=(10000, 15000, 25000, 40000, 60000),
        description="Массовый канал: много случайных откликов и большой разброс качества.",
    ),
    "graffiti": RecruitmentChannel(
        code="graffiti",
        title="Граффити-команда",
        icon="🧱",
        base_cost=6200,
        base_leads=1.8,
        quality_bonus=0.02,
        pay_multiplier=1.00,
        car_probability=0.44,
        deposit_pool=(15000, 25000, 40000, 60000, 90000),
        description="Средний по цене и качеству поток. Откликов меньше, чем со стикеров.",
    ),
    "forums": RecruitmentChannel(
        code="forums",
        title="Реклама на форумах",
        icon="🕸",
        base_cost=9000,
        base_leads=1.15,
        quality_bonus=0.10,
        pay_multiplier=1.10,
        car_probability=0.50,
        deposit_pool=(25000, 40000, 60000, 90000, 120000),
        description="Тематический канал: меньше откликов, но кандидаты в среднем сильнее и дороже.",
    ),
}




class RecruitmentService:
    """Asynchronous recruitment with configurable ads and employment terms."""

    def __init__(
        self,
        db: Database,
        speed: float = 1.0,
        rng: random.Random | None = None,
    ) -> None:
        self.db = db
        self.speed = max(0.1, float(speed))
        self.rng = rng or random.Random()
        self.init_schema()

    def init_schema(self) -> None:
        with self.db.connect() as conn:
            pass

    def get_channel(self, code: str) -> RecruitmentChannel | None:
        return CHANNELS.get(code)

    def player_multiplier(self, player_id: int) -> float:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT time_multiplier FROM settings WHERE player_id=?",
                (player_id,),
            ).fetchone()
        return max(0.1, float(row[0])) if row else 1.0

    def effective_speed(self, player_id: int) -> float:
        return max(0.1, self.speed * self.player_multiplier(player_id))

    def ensure_draft(self, player_id: int, channel: str | None = None):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO recruitment_drafts(player_id) VALUES (?)",
                (player_id,),
            )
            if channel in CHANNELS:
                conn.execute(
                    "UPDATE recruitment_drafts SET channel=?, updated_at=CURRENT_TIMESTAMP WHERE player_id=?",
                    (channel, player_id),
                )
            return conn.execute(
                "SELECT * FROM recruitment_drafts WHERE player_id=?",
                (player_id,),
            ).fetchone()

    def update_draft(self, player_id: int, field: str, value) -> None:
        allowed = {
            "channel",
            "traffic_multiplier",
            "duration_hours",
            "pay_per_job",
            "min_deposit",
            "deposit_contribution_pct",
            "car_required",
            "experience_required",
        }
        if field not in allowed:
            raise ValueError("Unsupported draft field")
        self.ensure_draft(player_id)
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE recruitment_drafts SET {field}=?, updated_at=CURRENT_TIMESTAMP WHERE player_id=?",
                (value, player_id),
            )

    def adjust_draft(self, player_id: int, field: str, delta: int) -> None:
        draft = self.ensure_draft(player_id)
        current = int(draft[field])
        if field == "pay_per_job":
            value = max(100, min(600, current + delta))
            value = int(round(value / 10) * 10)
        elif field == "min_deposit":
            value = max(0, min(200000, current + delta))
            value = int(round(value / 5000) * 5000)
        elif field == "deposit_contribution_pct":
            value = max(0, min(40, current + delta))
            value = int(round(value / 5) * 5)
        else:
            raise ValueError("Unsupported adjustable field")
        self.update_draft(player_id, field, value)

    def quote(self, player_id: int, draft=None) -> dict[str, float | int]:
        draft = draft or self.ensure_draft(player_id)
        channel = CHANNELS[draft["channel"]]
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

        net_pay = pay * (1.0 - contribution / 100.0)
        market_net = MARKET_PAY_PER_JOB * (1.0 - STANDARD_CONTRIBUTION_PCT / 100.0)
        pay_factor = clamp((net_pay / market_net) ** 1.6, 0.22, 1.85)

        if min_deposit <= 15000:
            deposit_factor = 1.12
        else:
            deposit_factor = clamp(math.exp(-(min_deposit - 15000) / 85000.0), 0.24, 1.0)

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
                   WHERE player_id=? AND channel=? AND status='active'""",
                (player_id, channel.code),
            ).fetchone()
            if active:
                return f"{channel.title}: размещение уже активно. Дождись завершения или выбери другой канал."

            shop = conn.execute(
                "SELECT balance FROM shops WHERE player_id=?",
                (player_id,),
            ).fetchone()
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
                """INSERT INTO ledger(player_id, amount, kind, note)
                   VALUES (?, ?, 'recruitment', ?)""",
                (
                    player_id,
                    -int(quote["cost"]),
                    f"{channel.title} · x{draft['traffic_multiplier']} · {duration_hours} ч",
                ),
            )
            conn.execute(
                """INSERT INTO recruitment_campaigns(
                       player_id, channel, cost, resolves_at,
                       traffic_multiplier, duration_hours, pay_per_job, min_deposit,
                       deposit_contribution_pct, car_required, experience_required,
                       expected_min, expected_max
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    player_id,
                    channel.code,
                    quote["cost"],
                    iso(resolves_at),
                    draft["traffic_multiplier"],
                    duration_hours,
                    draft["pay_per_job"],
                    draft["min_deposit"],
                    draft["deposit_contribution_pct"],
                    draft["car_required"],
                    draft["experience_required"],
                    quote["expected_min"],
                    quote["expected_max"],
                ),
            )

        return (
            f"<b>{channel.icon} Размещение запущено</b>\n\n"
            f"Охват: x{draft['traffic_multiplier']}\n"
            f"Срок: {draft['duration_hours']} игровых ч\n"
            f"Стоимость: <b>{int(quote['cost']):,} ₽</b>\n\n"
            f"Ожидаемые отклики: {quote['expected_min']}-{quote['expected_max']}"
        )

    def active_campaigns(self, player_id: int):
        self.advance(player_id)
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT * FROM recruitment_campaigns
                   WHERE player_id=? AND status='active'
                   ORDER BY resolves_at""",
                (player_id,),
            ).fetchall()

    def candidates(self, player_id: int):
        self.advance(player_id)
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT * FROM candidates
                   WHERE player_id=? AND status='open' AND campaign_id IS NOT NULL
                   ORDER BY id""",
                (player_id,),
            ).fetchall()

    def advance(self, player_id: int, now=None) -> int:
        now = now or utcnow()
        created = 0
        with self.db.connect() as conn:
            conn.execute(
                """UPDATE candidates SET status='expired'
                   WHERE player_id=? AND status='open' AND campaign_id IS NULL""",
                (player_id,),
            )
            campaigns = conn.execute(
                """SELECT * FROM recruitment_campaigns
                   WHERE player_id=? AND status='active' AND resolves_at<=?""",
                (player_id, iso(now)),
            ).fetchall()

            for campaign in campaigns:
                channel = CHANNELS.get(campaign["channel"])
                if not channel:
                    conn.execute(
                        "UPDATE recruitment_campaigns SET status='cancelled' WHERE id=?",
                        (campaign["id"],),
                    )
                    continue

                low = int(campaign["expected_min"] or 0)
                high = int(campaign["expected_max"] or max(1, low))
                count = self.rng.randint(low, high)
                for _ in range(count):
                    self._create_candidate(conn, player_id, campaign, channel, now)
                created += count

                conn.execute(
                    """UPDATE recruitment_campaigns
                       SET status='completed', candidates_created=?, completed_at=?
                       WHERE id=?""",
                    (count, iso(now), campaign["id"]),
                )
                body = (
                    f"Канал: {channel.title}\n"
                    f"Получено анкет: {count}\n\n"
                    "Открой раздел «Кандидаты», чтобы посмотреть отклики."
                )
                conn.execute(
                    """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
                       VALUES (?, 'recruitment_result', ?, 'Новые кандидаты', ?, ?, ?)""",
                    (
                        player_id,
                        "important" if count else "normal",
                        body,
                        json.dumps({"campaign_id": campaign["id"]}, ensure_ascii=False),
                        iso(now + timedelta(hours=10 / self.effective_speed(player_id))),
                    ),
                )
        return created

    def advance_all(self, now=None) -> int:
        now = now or utcnow()
        with self.db.connect() as conn:
            player_ids = [row[0] for row in conn.execute("SELECT player_id FROM shops").fetchall()]
        return sum(self.advance(player_id, now) for player_id in player_ids)

    def fast_forward(self, player_id: int, simulated_hours: float) -> int:
        shift = timedelta(hours=max(0.0, simulated_hours) / self.effective_speed(player_id))
        with self.db.connect() as conn:
            campaigns = conn.execute(
                """SELECT id, resolves_at FROM recruitment_campaigns
                   WHERE player_id=? AND status='active'""",
                (player_id,),
            ).fetchall()
            for campaign in campaigns:
                shifted = parse_dt(campaign["resolves_at"]) - shift
                conn.execute(
                    "UPDATE recruitment_campaigns SET resolves_at=? WHERE id=?",
                    (iso(shifted), campaign["id"]),
                )
        return self.advance(player_id)

    def set_player_multiplier(self, player_id: int, multiplier: float) -> tuple[float, float]:
        multiplier = max(0.1, min(240.0, float(multiplier)))
        now = utcnow()
        old = self.player_multiplier(player_id)
        old_speed = max(0.1, self.speed * old)
        new_speed = max(0.1, self.speed * multiplier)

        with self.db.connect() as conn:
            campaigns = conn.execute(
                """SELECT id, resolves_at FROM recruitment_campaigns
                   WHERE player_id=? AND status='active'""",
                (player_id,),
            ).fetchall()
            for campaign in campaigns:
                remaining_real = max(0.0, (parse_dt(campaign["resolves_at"]) - now).total_seconds())
                remaining_sim = remaining_real * old_speed
                new_real = remaining_sim / new_speed
                conn.execute(
                    "UPDATE recruitment_campaigns SET resolves_at=? WHERE id=?",
                    (iso(now + timedelta(seconds=new_real)), campaign["id"]),
                )
            conn.execute(
                "UPDATE settings SET time_multiplier=? WHERE player_id=?",
                (multiplier, player_id),
            )
        return old, multiplier

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
            lines.append(
                f"{channel.icon} {channel.title} · x{campaign['traffic_multiplier']} · {eta}"
            )
        return "<b>Активные размещения</b>\n" + "\n".join(lines)

    def _create_candidate(self, conn, player_id: int, campaign, channel: RecruitmentChannel, now) -> None:
        min_deposit = int(campaign["min_deposit"])
        offered_pay = int(campaign["pay_per_job"])
        contribution = int(campaign["deposit_contribution_pct"])
        car_required = bool(campaign["car_required"])
        experience_required = bool(campaign["experience_required"])

        deposit_quality_bonus = clamp((min_deposit - 25000) / 100000.0 * 0.12, -0.04, 0.08)
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
        if available_deposits:
            deposit = self.rng.choice(available_deposits)
        else:
            deposit = min_deposit + self.rng.choice([0, 10000, 25000])

        desired = int(
            (135 + (reliability + attention) * 65 + experience_level * 18 + self.rng.randint(-15, 25))
            * channel.pay_multiplier
        )
        desired = max(120, int(round(desired / 10) * 10))
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
