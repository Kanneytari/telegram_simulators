from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: Path
    admin_ids: frozenset[int]


def _load_admin_ids() -> frozenset[int]:
    raw = os.getenv("ADMIN_IDS", "").strip()
    if not raw:
        return frozenset()
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        values.add(int(part))
    return frozenset(values)


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")
    return Config(
        bot_token=token,
        db_path=Path(os.getenv("DB_PATH", "wasteland_rpg.db")),
        admin_ids=_load_admin_ids(),
    )
