from __future__ import annotations

from datetime import timedelta

from app.staff.recruitment import RecruitmentService
from app.engine.simulation import clamp, iso
from .model import generate_courier_blueprint


COURIER_ALIASES = (
    "Гриф", "Луна", "Рысь", "Штрих", "Кедр", "Ноль", "Фаза", "Север", "Ток", "Сова", "Мята",
    "Ворон", "Лис", "Барс", "Ястреб", "Крот", "Шмель", "Жук", "Скат", "Волк", "Шакал", "Кобра", "Уж",
    "Блик", "Дым", "Тень", "Иней", "Гром", "Шум", "Пыль", "Пепел", "Кварц", "Кремень", "Гранит", "Графит",
    "Неон", "Хром", "Оникс", "Янтарь", "Ртуть", "Азот", "Вольт", "Импульс", "Контур", "Пиксель", "Код",
    "Байт", "Порт", "Кэш", "Слот", "Радар", "Реле", "Маяк", "Риф", "Штиль", "Прибой", "Ветер", "Бриз",
    "Снег", "Лёд", "Туман", "Облако", "Дождь", "Град", "Сумрак", "Закат", "Рассвет", "Полночь", "Марс",
    "Комета", "Спутник", "Орбита", "Вега", "Атлас", "Омега", "Зенит", "Азимут", "Вектор", "Модуль", "Спектр",
    "Призма", "Фокус", "Кадр", "Дубль", "Трек", "Бит", "Бас", "Ритм", "Эхо", "Шёпот", "Гул", "Звон", "Клик",
    "Пульс", "Нерв", "Шрам", "Клык", "Коготь", "Шип", "Игла", "Стриж", "Чиж", "Филин", "Сыч", "Коршун",
    "Беркут", "Енот", "Хорёк", "Барсук", "Куница", "Норка", "Тритон", "Геккон", "Бобр", "Выдра", "Сом",
    "Окунь", "Щука", "Краб", "Скорпион", "Паук",
)


class CourierRecruitmentService(RecruitmentService):
    """Recruitment with deliberately distinct hidden courier personalities."""

    def _courier_alias(self, conn, player_id: int) -> str:
        seen = {
            str(row[0])
            for row in conn.execute(
                """SELECT alias FROM candidates WHERE player_id=? AND role='courier'
                   UNION
                   SELECT alias FROM employees WHERE player_id=? AND role='courier'""",
                (player_id, player_id),
            ).fetchall()
        }
        available = [alias for alias in COURIER_ALIASES if alias not in seen]
        if available:
            return self.rng.choice(available)

        # Numeric suffixes are only a last-resort fallback after the full pool
        # has already been seen by this player.
        for _ in range(100):
            alias = f"{self.rng.choice(COURIER_ALIASES)}{self.rng.randint(10, 99)}"
            if alias not in seen:
                return alias
        return f"{self.rng.choice(COURIER_ALIASES)}{self.rng.randint(100, 999)}"

    def _create_candidate(self, conn, player_id: int, campaign, channel, now) -> None:
        if campaign["role"] != "courier":
            super()._create_candidate(conn, player_id, campaign, channel, now)
            return

        min_deposit = int(campaign["min_deposit"])
        transport_required = int(campaign["transport_required"])
        experience_required = bool(campaign["experience_required"])
        deposit_quality_bonus = clamp(
            (min_deposit - 25_000) / 100_000.0 * 0.10,
            -0.05,
            0.08,
        )
        requirement_quality_bonus = (
            0.02
            if transport_required >= 2
            else 0.01
            if transport_required == 1
            else 0.0
        ) + (0.05 if experience_required else 0.0)
        quality_bonus = (
            channel.quality_bonus
            + deposit_quality_bonus
            + requirement_quality_bonus
        )

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
        alias = self._courier_alias(conn, player_id)

        if transport_required >= 2:
            transport_level = 2
        elif transport_required == 1:
            transport_level = (
                2 if self.rng.random() < channel.car_probability else 1
            )
        else:
            roll = self.rng.random()
            if roll < channel.car_probability:
                transport_level = 2
            elif roll < min(0.92, channel.car_probability + 0.42):
                transport_level = 1
            else:
                transport_level = 0
        has_car = int(transport_level == 2)

        phone_roll = self.rng.random()
        if experience_level >= 2:
            phone_level = 0 if phone_roll < 0.15 else 1 if phone_roll < 0.78 else 2
        elif experience_level == 1:
            phone_level = 0 if phone_roll < 0.35 else 1 if phone_roll < 0.90 else 2
        else:
            phone_level = 0 if phone_roll < 0.55 else 1 if phone_roll < 0.95 else 2

        deposit_pool = (
            5_000,
            10_000,
            15_000,
            25_000,
            40_000,
            60_000,
            90_000,
            100_000,
        )
        available = [value for value in deposit_pool if value >= min_deposit]
        deposit = (
            self.rng.choice(available)
            if available
            else min(100_000, max(min_deposit, 25_000))
        )
        starting_loyalty = clamp(
            self.rng.uniform(0.48, 0.66)
            + experience_level * 0.015
            + quality_bonus * 0.15,
            0.38,
            0.78,
        )

        cur = conn.execute(
            """INSERT INTO candidates(
                   player_id, alias, role, deposit, has_car, reliability, attention, honesty,
                   loyalty, expires_at, campaign_id, source_channel, min_deposit, experience_level
               ) VALUES (?, ?, 'courier', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                player_id,
                alias,
                deposit,
                has_car,
                blueprint.pace,
                blueprint.precision,
                blueprint.integrity,
                starting_loyalty,
                iso(now + timedelta(hours=10 / self.effective_speed(player_id))),
                campaign["id"],
                channel.code,
                min_deposit,
                experience_level,
            ),
        )
        candidate_id = int(cur.lastrowid)
        conn.execute(
            """INSERT INTO courier_candidate_profiles(
                   candidate_id, pace, precision, resilience, integrity, trait, transport_level, phone_level
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                candidate_id,
                blueprint.pace,
                blueprint.precision,
                blueprint.resilience,
                blueprint.integrity,
                blueprint.trait,
                transport_level,
                phone_level,
            ),
        )


__all__ = ["CourierRecruitmentService", "COURIER_ALIASES"]
