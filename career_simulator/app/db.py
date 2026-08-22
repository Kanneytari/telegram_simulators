from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS players (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    career_day INTEGER NOT NULL DEFAULT 1,
    day_key TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT 0,
    track TEXT NOT NULL DEFAULT 'general',
    money INTEGER NOT NULL DEFAULT 2500,
    skill INTEGER NOT NULL DEFAULT 5,
    reputation INTEGER NOT NULL DEFAULT 5,
    visibility INTEGER NOT NULL DEFAULT 0,
    network INTEGER NOT NULL DEFAULT 0,
    stress INTEGER NOT NULL DEFAULT 10,
    actions_left INTEGER NOT NULL DEFAULT 5,
    projects_done INTEGER NOT NULL DEFAULT 0,
    projects_failed INTEGER NOT NULL DEFAULT 0,
    promotion_ready INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    target INTEGER NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    deadline_day INTEGER NOT NULL,
    reward_money INTEGER NOT NULL,
    reward_rep INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_day INTEGER NOT NULL,
    completed_day INTEGER
);

CREATE INDEX IF NOT EXISTS idx_projects_player_status
    ON projects(player_id, status);

CREATE TABLE IF NOT EXISTS daily_events (
    player_id INTEGER NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    day_key TEXT NOT NULL,
    event_id TEXT NOT NULL,
    choice_index INTEGER,
    PRIMARY KEY(player_id, day_key)
);

CREATE TABLE IF NOT EXISTS purchases (
    player_id INTEGER NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    day_key TEXT NOT NULL,
    investment_id TEXT NOT NULL,
    price INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(player_id, day_key)
);

CREATE TABLE IF NOT EXISTS action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    career_day INTEGER NOT NULL,
    day_key TEXT NOT NULL,
    action_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(telegram_id) ON DELETE CASCADE,
    career_day INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        parent = Path(path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
