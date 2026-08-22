from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS players (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    hp INTEGER NOT NULL DEFAULT 100,
                    credits INTEGER NOT NULL DEFAULT 70,
                    ammo INTEGER NOT NULL DEFAULT 12,
                    medkits INTEGER NOT NULL DEFAULT 1,
                    xp INTEGER NOT NULL DEFAULT 0,
                    combat INTEGER NOT NULL DEFAULT 1,
                    scavenging INTEGER NOT NULL DEFAULT 1,
                    survival INTEGER NOT NULL DEFAULT 1,
                    successful_runs INTEGER NOT NULL DEFAULT 0,
                    deaths INTEGER NOT NULL DEFAULT 0,
                    weapon_id TEXT NOT NULL DEFAULT 'pipe_pistol',
                    armor_id TEXT NOT NULL DEFAULT 'old_coat',
                    state TEXT NOT NULL DEFAULT 'base',
                    sector_id TEXT,
                    threat INTEGER NOT NULL DEFAULT 0,
                    steps INTEGER NOT NULL DEFAULT 0,
                    pending_event TEXT,
                    enemy_id TEXT,
                    enemy_hp INTEGER,
                    aimed INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    telegram_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    secured INTEGER NOT NULL CHECK (secured IN (0, 1)),
                    qty INTEGER NOT NULL CHECK (qty >= 0),
                    PRIMARY KEY (telegram_id, item_id, secured),
                    FOREIGN KEY (telegram_id) REFERENCES players(telegram_id) ON DELETE CASCADE
                );
                """
            )
