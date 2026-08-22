from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: str = "career_simulator.sqlite3"
    admin_ids: frozenset[int] = frozenset()


def _parse_admin_ids(raw: str) -> frozenset[int]:
    if not raw.strip():
        return frozenset()

    result: set[int] = set()
    for value in raw.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            result.add(int(value))
        except ValueError as exc:
            raise RuntimeError(
                f"Некорректный ADMIN_IDS: {value!r}. Используй Telegram ID через запятую."
            ) from exc
    return frozenset(result)


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")
    return Config(
        bot_token=token,
        db_path=os.getenv("DB_PATH", "career_simulator.sqlite3"),
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
    )
