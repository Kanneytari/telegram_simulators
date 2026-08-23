from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import timedelta

from .db import Database
from .simulation import clamp, iso, parse_dt, utcnow


@dataclass(frozen=True)
class RecruitmentChannel:
    code: str
    title: str
    icon: str
    cost: int
    min_hours: float
    max_hours: float
    min_candidates: int
    max_candidates: int
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
        cost=3500,
        min_hours=3.0,
        max_hours=6.0,
        min_candidates=2,
        max_candidates=5,
        quality_bonus=-0.03,
        pay_multiplier=0.95,
        car_probability=0.32,
        deposit_pool=(10000, 15000, 25000, 40000),
        description="Дешёвый массовый канал: откликов обычно больше, но качество сильнее плавает.",
    ),
    "graffiti": RecruitmentChannel(
        code="graffiti",
        title="Граффити-команда",
        icon="🧱",
        cost=7500,
        min_hours=4.0,
        max_hours=8.0,
        min_candidates=2,
        max_candidates=4,
        quality_bonus=0.02,
        pay_multiplier=1.00,
        car_probability=0.44,
        deposit_pool=(15000, 25000, 40000, 60000),
        description="Более дорогой офлайн-канал: поток меньше, зато случайных анкет немного меньше.",
    ),
    "forums": RecruitmentChannel(
        code="forums",
        title="Реклама на форумах",
        icon="🕸",
        cost=12000,
        min_hours=1.5,
        max_hours=4.0,
        min_candidates=1,
        max_candidates=3,
        quality_bonus=0.10,
        pay_multiplier=1.12,
        car_probability=0.50,
        deposit_pool=(25000, 40000, 60000, 90000),
        description="Тематический канал: откликов меньше, кандидаты в среднем опытнее и дороже.",
    ),
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS recruitment_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    cost INTEGER NOT NULL,
    resolves_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    candidates_created INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_recruitment_player_status
    ON recruitment_campaigns(player_id, status, resolves_at);
"""


class RecruitmentService:
    """Asynchronous recruitment campaigns with source-specific applicant pools."""

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
            conn.executescript(SCHEMA)

    def get_channel(self, code: str) -> RecruitmentChannel | None:
        return CHANNELS.get(code)

    def start_campaign(self, player_id: int, code: str) -> str:
        channel = self.get_channel(code)
        if not channel:
            raise ValueError("Unknown recruitment channel")

        self.advance(player_id)
        now = utcnow()
        with self.db.connect() as conn:
            active = conn.execute(
                """SELECT 1 FROM recruitment_campaigns
                   WHERE player_id=? AND channel=? AND status='active'""",
                (player_id, code),
            ).fetchone()
            if active:
                return f"{channel.title}: кампания уже запущена. Дождись откликов."

            shop = conn.execute(
                "SELECT balance FROM shops WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if not shop:
                return "Сначала начни игру командой /start."
            if int(shop["balance"]) < channel.cost:
                return f"Недостаточно денег. Нужно {channel.cost:,} ₽."

            simulated_hours = self.rng.uniform(channel.min_hours, channel.max_hours)
            real_hours = simulated_hours / self.speed
            resolves_at = now + timedelta(hours=real_hours)

            conn.execute(
                "UPDATE shops SET balance=balance-?, total_profit=total_profit-? WHERE player_id=?",
                (channel.cost, channel.cost, player_id),
            )
            conn.execute(
                """INSERT INTO ledger(player_id, amount, kind, note)
                   VALUES (?, ?, 'recruitment', ?)""",
                (player_id, -channel.cost, channel.title),
            )
            conn.execute(
                """INSERT INTO recruitment_campaigns(player_id, channel, cost, resolves_at)
                   VALUES (?, ?, ?, ?)""",
                (player_id, code, channel.cost, iso(resolves_at)),
            )

        return (
            f"{channel.title}: кампания запущена за {channel.cost:,} ₽.\n"
            f"Ожидаемый поток: {channel.min_candidates}-{channel.max_candidates} анкет.\n"
            f"Первые результаты — примерно через {channel.min_hours:g}-{channel.max_hours:g} игровых часов."
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
                   WHERE player_id=? AND status='open'
                     AND summary LIKE 'Источник:%'
                   ORDER BY desired_pay, id""",
                (player_id,),
            ).fetchall()

    def advance(self, player_id: int, now=None) -> int:
        now = now or utcnow()
        created = 0
        with self.db.connect() as conn:
            # Старый MVP генерировал кандидатов автоматически. Такие строки скрываются,
            # чтобы найм в текущей версии шёл через реальные игровые кампании.
            conn.execute(
                """UPDATE candidates SET status='expired'
                   WHERE player_id=? AND status='open'
                     AND summary NOT LIKE 'Источник:%'""",
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
                count = self.rng.randint(channel.min_candidates, channel.max_candidates)
                for _ in range(count):
                    self._create_candidate(conn, player_id, channel, now)
                created += count
                conn.execute(
                    """UPDATE recruitment_campaigns
                       SET status='completed', candidates_created=?, completed_at=?
                       WHERE id=?""",
                    (count, iso(now), campaign["id"]),
                )
                conn.execute(
                    """INSERT INTO inbox(player_id, kind, priority, title, body, payload_json, expires_at)
                       VALUES (?, 'recruitment_result', 'important', ?, ?, ?, ?)""",
                    (
                        player_id,
                        "Новые кандидаты",
                        f"Кампания «{channel.title}» завершилась. Получено анкет: {count}. Кандидаты ждут решения.",
                        json.dumps({"campaign_id": campaign["id"]}, ensure_ascii=False),
                        iso(now + timedelta(hours=10 / self.speed)),
                    ),
                )
        return created

    def advance_all(self, now=None) -> int:
        now = now or utcnow()
        with self.db.connect() as conn:
            player_ids = [row[0] for row in conn.execute("SELECT player_id FROM shops").fetchall()]
        return sum(self.advance(player_id, now) for player_id in player_ids)

    def fast_forward(self, player_id: int, simulated_hours: float) -> int:
        shift = timedelta(hours=max(0.0, simulated_hours) / self.speed)
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

    def campaign_status_text(self, player_id: int) -> str:
        campaigns = self.active_campaigns(player_id)
        if not campaigns:
            return "Активных кампаний нет."
        now = utcnow()
        lines = []
        for campaign in campaigns:
            channel = CHANNELS[campaign["channel"]]
            real_hours = max(0.0, (parse_dt(campaign["resolves_at"]) - now).total_seconds() / 3600)
            sim_hours = real_hours * self.speed
            eta = "меньше часа" if sim_hours < 1 else f"~{sim_hours:.1f} ч"
            lines.append(f"{channel.icon} {channel.title} · {eta}")
        return "Активные кампании:\n" + "\n".join(lines)

    def _create_candidate(self, conn, player_id: int, channel: RecruitmentChannel, now) -> None:
        alias = self.rng.choice(["Гриф", "Луна", "Рысь", "Штрих", "Кедр", "Ноль", "Фаза", "Север", "Ток"]) + str(
            self.rng.randint(10, 99)
        )
        reliability = clamp(self.rng.uniform(0.52, 0.90) + channel.quality_bonus, 0.38, 0.99)
        attention = clamp(self.rng.uniform(0.52, 0.92) + channel.quality_bonus * 0.9, 0.38, 0.99)
        honesty = clamp(self.rng.uniform(0.48, 0.94) + channel.quality_bonus * 0.4, 0.35, 0.99)
        loyalty = clamp(self.rng.uniform(0.42, 0.86) + channel.quality_bonus * 0.25, 0.30, 0.96)
        desired = int((140 + (reliability + attention) * 65 + self.rng.randint(-20, 30)) * channel.pay_multiplier)
        desired = max(120, int(round(desired / 5) * 5))
        deposit = self.rng.choice(channel.deposit_pool)
        has_car = int(self.rng.random() < channel.car_probability)

        if channel.code == "stickers":
            experience = self.rng.choice(["без опыта", "небольшой опыт", "опыт не подтверждён"])
        elif channel.code == "graffiti":
            experience = self.rng.choice(["небольшой опыт", "работал раньше", "опыт не подтверждён"])
        else:
            experience = self.rng.choice(["говорит, что работал раньше", "есть опыт", "опыт выглядит убедительно"])

        summary = (
            f"Источник: {channel.title}; {experience}; "
            f"{'есть автомобиль' if has_car else 'без автомобиля'}; "
            f"готовое обеспечение {deposit:,} ₽"
        )
        conn.execute(
            """INSERT INTO candidates(player_id, alias, role, desired_pay, deposit, has_car,
               reliability, attention, honesty, loyalty, summary, expires_at)
               VALUES (?, ?, 'courier', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                iso(now + timedelta(hours=10 / self.speed)),
            ),
        )
