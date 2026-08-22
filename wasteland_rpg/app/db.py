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
        conn.execute("PRAGMA foreign_keys = ON")
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
                    hp INTEGER NOT NULL DEFAULT 40,
                    credits INTEGER NOT NULL DEFAULT 70,
                    ammo INTEGER NOT NULL DEFAULT 12,
                    medkits INTEGER NOT NULL DEFAULT 1,
                    xp INTEGER NOT NULL DEFAULT 0,
                    strength INTEGER NOT NULL DEFAULT 1,
                    agility INTEGER NOT NULL DEFAULT 1,
                    perception INTEGER NOT NULL DEFAULT 1,
                    intelligence INTEGER NOT NULL DEFAULT 1,
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

                CREATE TABLE IF NOT EXISTS player_world (
                    telegram_id INTEGER PRIMARY KEY,
                    location_id TEXT NOT NULL DEFAULT 'refuge7',
                    FOREIGN KEY (telegram_id) REFERENCES players(telegram_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS visited_locations (
                    telegram_id INTEGER NOT NULL,
                    location_id TEXT NOT NULL,
                    PRIMARY KEY (telegram_id, location_id),
                    FOREIGN KEY (telegram_id) REFERENCES players(telegram_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS equipment (
                    telegram_id INTEGER PRIMARY KEY,
                    backpack_id TEXT NOT NULL DEFAULT 'canvas_pack',
                    headgear_id TEXT NOT NULL DEFAULT 'cloth_hood',
                    gadget_id TEXT NOT NULL DEFAULT 'none',
                    FOREIGN KEY (telegram_id) REFERENCES players(telegram_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS cargo (
                    telegram_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    qty INTEGER NOT NULL CHECK (qty >= 0),
                    PRIMARY KEY (telegram_id, item_id),
                    FOREIGN KEY (telegram_id) REFERENCES players(telegram_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS travel (
                    telegram_id INTEGER PRIMARY KEY,
                    route_id TEXT NOT NULL,
                    origin_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    step INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (telegram_id) REFERENCES players(telegram_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS combat_state (
                    telegram_id INTEGER PRIMARY KEY,
                    return_state TEXT NOT NULL DEFAULT 'expedition',
                    distance INTEGER NOT NULL DEFAULT 2,
                    cover INTEGER NOT NULL DEFAULT 0,
                    bleeding INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (telegram_id) REFERENCES players(telegram_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS event_weights (
                    telegram_id INTEGER NOT NULL,
                    context TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    current_weight INTEGER NOT NULL CHECK (current_weight >= 0),
                    PRIMARY KEY (telegram_id, context, event_key),
                    FOREIGN KEY (telegram_id) REFERENCES players(telegram_id) ON DELETE CASCADE
                );

                INSERT OR IGNORE INTO player_world (telegram_id, location_id)
                SELECT telegram_id, 'refuge7' FROM players;
                INSERT OR IGNORE INTO visited_locations (telegram_id, location_id)
                SELECT telegram_id, 'refuge7' FROM players;
                INSERT OR IGNORE INTO equipment (telegram_id)
                SELECT telegram_id FROM players;
                """
            )

    def reset_player(self, telegram_id: int) -> None:
        """Delete all persisted game state for one player via foreign-key cascades."""
        with self.connect() as conn:
            conn.execute("DELETE FROM players WHERE telegram_id = ?", (telegram_id,))
