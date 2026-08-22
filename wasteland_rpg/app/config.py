from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: Path


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")
    return Config(
        bot_token=token,
        db_path=Path(os.getenv("DB_PATH", "wasteland_rpg.db")),
    )
