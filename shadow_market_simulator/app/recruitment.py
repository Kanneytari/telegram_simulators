from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from datetime import timedelta

from .compensation import DEFAULT_POLICIES, _ensure_policy_conn
from .db import Database
from .simulation import clamp, iso, parse_dt, utcnow


VOLUME_OPTIONS = (1, 2, 4)
DURATION_OPTIONS = (4, 12, 24)
RETAIL_STARTING_DEPOSIT_CAP = 100_000
ROLE_TITLES = {
    "courier": "Розничный сотрудник",
    "warehouse": "Оптовый сотрудник",
}


@dataclass(frozen=True)
class RecruitmentChannel:
    code: str
    title: str
    icon: str
    base_cost: int
    base_leads: float
    quality_bonus: float
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
        car_probability=0.32,
        deposit_pool=(10_000, 15_000, 25_000, 40_000, 60_000),
        description="Массовый канал: много случайных откликов и большой разброс качества.",
    ),
    "graffiti": RecruitmentChannel(
        code="graffiti",
        title="Граффити-команда",
        icon="🧱",
        base_cost=6200,
        base_leads=1.8,
        quality_bonus=0.02,
        car_probability=0.44,
        deposit_pool=(15_000, 25_000, 40_000, 60_000, 90_000),
        description="Средний по цене и качеству поток. Откликов меньше, чем со стикеров.",
    ),
    "forums": RecruitmentChannel(
        code="forums",
        title="Реклама на форумах",
        icon="🕸",
        base_cost=9000,
        base_leads=1.15,
        quality_bonus=0.10,
        car_probability=0.50,
        deposit_pool=(25_000, 40_000, 60_000, 90_000, 100_000),
        description="Тематический канал: меньше откликов, но кандидаты в среднем сильнее.",
    ),
}


class RecruitmentService:
    def __init__(
        self,
        db: Database,
        speed: float = 1.0,
        rng: random.Random | None = None,
    ) -> None:
        self.db = db
        self.speed = max(0.1, float(speed))
        self.rng = rng or random.Random()
        with self.db.connect() as conn:
            for row in conn.execute("SELECT player_id FROM shops").fetchall():
                for role in DEFAULT_POLICIES:
                    _ensure_policy_conn(conn, int(row["player_id"]), role)

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
                conn.execute(
                    "UPDATE recruitment_campaigns SET resolves_at=? WHERE id=?",
                    (iso(now + timedelta(seconds=remaining_game / multiplier)), campaign["id"]),
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
                """SELECT fixed_fee, base_rate_bps, risk_rate_bps, deposit_contribution_pct
                   FROM staff_compensation_policies WHERE player_id=? AND role=?""",
                (player_id, role),
            ).fetchone()
        if not row:
            return dict(defaults)
        return {key: int(row[key]) for key in defaults}

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
            row = conn.execute(
                "SELECT * FROM recruitment_drafts WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if row["role"] == "courier" and int(row["min_deposit"]) > RETAIL_STARTING_DEPOSIT_CAP:
                conn.execute(
                    "UPDATE recruitment_drafts SET min_deposit=? WHERE player_id=?",
                    (RETAIL_STARTING_DEPOSIT_CAP, player_id),
                )
                row = conn.execute(
                    "SELECT * FROM recruitment_drafts WHERE player_id=?",
                    (player_id,),
                ).fetchone()
        return row

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
            "channel", "traffic_multiplier", "duration_hours", "min_deposit",
            "car_required", "experience_required",
        }:
            raise ValueError("Unsupported draft field")
        if field == "min_deposit" and self.ensure_draft(player_id)["role"] == "courier":
            value = min(RETAIL_STARTING_DEPOSIT_CAP, int(value))
        self.ensure_draft(player_id)
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE recruitment_drafts SET {field}=?, updated_at=CURRENT_TIMESTAMP WHERE player_id=?",
                (value, player_id),
            )

    def adjust_draft(self, player_id: int, field: str, delta: int) -> None:
        if field != "min_deposit":
            raise ValueError("Unsupported adjustable field")
        draft = self.ensure_draft(player_id)
        current = int(draft["min_deposit"])
        if draft["role"] == "warehouse":
            value = int(round(max(100_000, min(2_000_000, current + delta)) / 50_000) * 50_000)
        else:
            value = int(round(max(0, min(RETAIL_STARTING_DEPOSIT_CAP, current + delta)) / 5_000) * 5_000)
        self.update_draft(player_id, "min_deposit", value)

    def quote(self, player_id: int, draft=None) -> dict[str, float | int | str]:
        draft = draft or self.ensure_draft(player_id)
        channel = CHANNELS[draft["channel"]]
        role = str(draft["role"])
        volume = int(draft["traffic_multiplier"])
        duration = int(draft["duration_hours"])
        min_deposit = int(draft["min_deposit"])
        policy = self._policy(player_id, role)

        blocks = volume * duration / 4.0
        undiscounted = channel.base_cost * blocks
        cost = int(round(
            undiscounted
            * {1: 1.00, 2: 0.92, 4: 0.82}.get(volume, 1.0)
            * {4: 1.00, 12: 0.90, 24: 0.82}.get(duration, 1.0)
            / 100.0
        ) * 100)
        discount_pct = max(0.0, (1.0 - cost / undiscounted) * 100.0) if undiscounted else 0.0

        score = self._policy_score(role, policy)
        benchmark = self._policy_score(role, DEFAULT_POLICIES[role])
        pay_factor = clamp((score / max(benchmark, 1.0)) ** 1.45, 0.25, 1.90)
        if role == "warehouse":
            deposit_floor, deposit_scale, role_flow = 250_000, 700_000.0, 0.48
        else:
            deposit_floor, deposit_scale, role_flow = 15_000, 85_000.0, 1.0
        deposit_factor = 1.10 if min_deposit <= deposit_floor else clamp(
            math.exp(-(min_deposit - deposit_floor) / deposit_scale), 0.18, 1.0
        )
        requirement_factor = 1.0
        if int(draft["car_required"]):
            requirement_factor *= 0.58
        if int(draft["experience_required"]):
            requirement_factor *= 0.55
        expected = (
            channel.base_leads * (blocks ** 0.82) * pay_factor
            * deposit_factor * requirement_factor * role_flow
        )
        low = max(0, int(math.floor(expected * 0.65)))
        high = max(low + 1, int(math.ceil(expected * 1.35)))
        return {
            "cost": cost, "undiscounted": int(round(undiscounted)),
            "discount_pct": discount_pct, "expected": expected,
            "expected_min": low, "expected_max": high,
            "unit_cost": int(round(cost / max(blocks, 1.0))),
            "role": role, "policy": policy,
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
                (player_id, -int(quote["cost"]),
                 f"{channel.title} · {ROLE_TITLES[draft['role']]} · x{draft['traffic_multiplier']} · {duration_hours} ч"),
            )
            conn.execute(
                """INSERT INTO recruitment_campaigns(
                       player_id, channel, role, cost, resolves_at,
                       traffic_multiplier, duration_hours, min_deposit,
                       car_required, experience_required, expected_min, expected_max,
                       terms_fixed_fee, terms_base_rate_bps, terms_risk_rate_bps, terms_deposit_pct
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    player_id, channel.code, draft["role"], quote["cost"], iso(resolves_at),
                    draft["traffic_multiplier"], duration_hours, draft["min_deposit"],
                    draft["car_required"], draft["experience_required"],
                    quote["expected_min"], quote["expected_max"],
                    policy["fixed_fee"], policy["base_rate_bps"],
                    policy["risk_rate_bps"], policy["deposit_contribution_pct"],
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

    def active_campaigns(self, player_id: int):
        self.advance(player_id)
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT * FROM recruitment_campaigns WHERE player_id=? AND status='active' ORDER BY resolves_at",
                (player_id,),
            ).fetchall()

    def candidates(self, player_id: int):
        self.advance(player_id)
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT * FROM candidates WHERE player_id=? AND status='open' ORDER BY id",
                (player_id,),
            ).fetchall()

    def advance(self, player_id: int, now=None) -> int:
        now = now or utcnow()
        created = 0
        with self.db.connect() as conn:
            campaigns = conn.execute(
                """SELECT * FROM recruitment_campaigns
                   WHERE player_id=? AND status='active' AND resolves_at<=?""",
                (player_id, iso(now)),
            ).fetchall()
            for campaign in campaigns:
                channel = CHANNELS.get(campaign["channel"])
                if not channel:
                    conn.execute("UPDATE recruitment_campaigns SET status='cancelled' WHERE id=?", (campaign["id"],))
                    continue
                low = int(campaign["expected_min"] or 0)
                high = int(campaign["expected_max"] or max(1, low))
                count = self.rng.randint(low, high)
                for _ in range(count):
                    self._create_candidate(conn, player_id, campaign, channel, now)
                created += count
                conn.execute(
                    """UPDATE recruitment_campaigns
                       SET status='completed', candidates_created=?, completed_at=? WHERE id=?""",
                    (count, iso(now), campaign["id"]),
                )
                conn.execute(
                    """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
                       VALUES (?, 'recruitment_result', ?, 'Новые кандидаты', ?, ?, ?)""",
                    (
                        player_id, "important" if count else "normal",
                        f"Канал: {channel.title}\nПолучено анкет: {count}\n\nОткрой это сообщение и нажми «Смотреть кандидатов».",
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
                "SELECT id, resolves_at FROM recruitment_campaigns WHERE player_id=? AND status='active'",
                (player_id,),
            ).fetchall()
            for campaign in campaigns:
                conn.execute(
                    "UPDATE recruitment_campaigns SET resolves_at=? WHERE id=?",
                    (iso(parse_dt(campaign["resolves_at"]) - shift), campaign["id"]),
                )
        return self.advance(player_id)

    def campaign_status_text(self, player_id: int) -> str:
        campaigns = self.active_campaigns(player_id)
        if not campaigns:
            return "Активных размещений нет."
        now = utcnow()
        speed = self.effective_speed(player_id)
        lines = []
        for campaign in campaigns:
            channel = CHANNELS[campaign["channel"]]
            real_hours = max(0.0, (parse_dt(campaign["resolves_at"]) - now).total_seconds() / 3600.0)
            game_hours = real_hours * speed
            eta = "менее 1 ч" if game_hours < 1 else f"~{game_hours:.1f} ч"
            lines.append(f"{channel.icon} {ROLE_TITLES[campaign['role']]} · x{campaign['traffic_multiplier']} · {eta}")
        return "<b>Активные размещения</b>\n" + "\n".join(lines)

    def _create_candidate(self, conn, player_id: int, campaign, channel: RecruitmentChannel, now) -> None:
        role = str(campaign["role"])
        min_deposit = int(campaign["min_deposit"])
        car_required = bool(campaign["car_required"])
        experience_required = bool(campaign["experience_required"])
        deposit_reference = 300_000 if role == "warehouse" else 25_000
        quality_scale = 900_000 if role == "warehouse" else 100_000
        quality_bonus = (
            channel.quality_bonus
            + clamp((min_deposit - deposit_reference) / quality_scale * 0.12, -0.05, 0.10)
            + (0.02 if car_required else 0.0)
            + (0.05 if experience_required else 0.0)
        )
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
            pool = tuple(value for value in channel.deposit_pool if value <= RETAIL_STARTING_DEPOSIT_CAP)
        available = [value for value in pool if value >= min_deposit]
        if available:
            deposit = self.rng.choice(available)
        elif role == "warehouse":
            deposit = min_deposit + 100_000
        else:
            deposit = min(RETAIL_STARTING_DEPOSIT_CAP, max(min_deposit, 25_000))
        conn.execute(
            """INSERT INTO candidates(
                   player_id, alias, role, deposit, has_car, reliability, attention, honesty,
                   loyalty, expires_at, campaign_id, source_channel, min_deposit, experience_level
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                player_id, alias, role, deposit, has_car, reliability, attention, honesty, loyalty,
                iso(now + timedelta(hours=10 / self.effective_speed(player_id))),
                campaign["id"], channel.code, min_deposit, experience_level,
            ),
        )
