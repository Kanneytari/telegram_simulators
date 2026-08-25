from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    db_path: str
    simulation_interval_seconds: int
    simulation_speed: float


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and add the token.")

    admin_ids = frozenset(
        int(value.strip())
        for value in os.getenv("ADMIN_IDS", "").split(",")
        if value.strip()
    )
    return Settings(
        bot_token=token,
        admin_ids=admin_ids,
        db_path=os.getenv("DB_PATH", "shadow_market.sqlite3"),
        simulation_interval_seconds=max(10, int(os.getenv("SIMULATION_INTERVAL_SECONDS", "30"))),
        simulation_speed=max(0.1, float(os.getenv("SIMULATION_SPEED", "1.0"))),
    )
