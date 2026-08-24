from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = r"""
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS shops (
    player_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT NOT NULL DEFAULT 'NIGHTSHIFT',
    balance INTEGER NOT NULL DEFAULT 150000,
    reserve_target INTEGER NOT NULL DEFAULT 30000,
    rating REAL NOT NULL DEFAULT 4.0,
    employee_reputation REAL NOT NULL DEFAULT 50.0,
    supplier_reputation REAL NOT NULL DEFAULT 50.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_simulated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_revenue INTEGER NOT NULL DEFAULT 0,
    total_profit INTEGER NOT NULL DEFAULT 0,
    total_orders INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    base_market_price INTEGER NOT NULL,
    base_demand REAL NOT NULL,
    complaint_modifier REAL NOT NULL DEFAULT 1.0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    price_modifier REAL NOT NULL,
    quality_mean REAL NOT NULL,
    quality_sigma REAL NOT NULL,
    reliability REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS supplier_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_cost INTEGER NOT NULL,
    quality_hint TEXT NOT NULL,
    offer_quality_mean REAL,
    offer_quality_sigma REAL,
    offer_reliability REAL,
    market_profile TEXT NOT NULL DEFAULT 'normal',
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    role TEXT NOT NULL,
    pay_per_job INTEGER NOT NULL DEFAULT 0,
    deposit INTEGER NOT NULL DEFAULT 0,
    deposit_contribution_pct INTEGER NOT NULL DEFAULT 0,
    wages_accrued INTEGER NOT NULL DEFAULT 0,
    deposit_accrued INTEGER NOT NULL DEFAULT 0,
    total_wages_paid INTEGER NOT NULL DEFAULT 0,
    deposit_from_wages INTEGER NOT NULL DEFAULT 0,
    has_car INTEGER NOT NULL DEFAULT 0,
    reliability REAL NOT NULL,
    attention REAL NOT NULL,
    honesty REAL NOT NULL,
    loyalty REAL NOT NULL,
    stress REAL NOT NULL DEFAULT 10.0,
    active INTEGER NOT NULL DEFAULT 1,
    available INTEGER NOT NULL DEFAULT 1,
    unavailable_until TEXT,
    jobs_done INTEGER NOT NULL DEFAULT 0,
    disputes INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_contact_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    responsible_employee_id INTEGER REFERENCES employees(id),
    quantity INTEGER NOT NULL,
    remaining INTEGER NOT NULL,
    unit_cost INTEGER NOT NULL,
    quality REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'warehouse',
    acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    role TEXT NOT NULL,
    desired_pay INTEGER NOT NULL DEFAULT 0,
    deposit INTEGER NOT NULL,
    has_car INTEGER NOT NULL,
    reliability REAL NOT NULL,
    attention REAL NOT NULL,
    honesty REAL NOT NULL,
    loyalty REAL NOT NULL,
    summary TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    campaign_id INTEGER,
    source_channel TEXT,
    offered_pay INTEGER,
    min_deposit INTEGER,
    deposit_contribution_pct INTEGER NOT NULL DEFAULT 0,
    experience_level INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    account_age_days INTEGER NOT NULL,
    marketplace_orders INTEGER NOT NULL,
    shop_orders INTEGER NOT NULL DEFAULT 0,
    total_spend INTEGER NOT NULL DEFAULT 0,
    disputes_total INTEGER NOT NULL DEFAULT 0,
    disputes_won INTEGER NOT NULL DEFAULT 0,
    fraud_propensity REAL NOT NULL,
    patience REAL NOT NULL,
    loyalty REAL NOT NULL,
    review_tendency REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    pack_size INTEGER NOT NULL,
    price INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(player_id, product_id, pack_size)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    revenue INTEGER NOT NULL,
    cost INTEGER NOT NULL,
    employee_cost INTEGER NOT NULL,
    employee_deposit_contribution INTEGER NOT NULL DEFAULT 0,
    quality REAL NOT NULL,
    customer_purchase_number INTEGER NOT NULL DEFAULT 1,
    customer_was_repeat INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Removed from live UX. Kept temporarily until analytics/event-log migration is
-- completed in this branch, then deleted before merge.
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
    text TEXT NOT NULL,
    quality_sentiment TEXT NOT NULL,
    delivery_sentiment TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS disputes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    true_cause TEXT NOT NULL,
    message TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    courier_reply TEXT,
    courier_reply_pending TEXT,
    courier_reply_due_at TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    decision TEXT,
    refund_amount INTEGER NOT NULL DEFAULT 0,
    refund_source TEXT,
    refund_employee_id INTEGER,
    deadline_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    priority TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open',
    due_at TEXT,
    expires_at TEXT,
    notified_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    kind TEXT NOT NULL,
    reference_type TEXT,
    reference_id INTEGER,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
    auto_refund_limit INTEGER NOT NULL DEFAULT 0,
    auto_partial_limit INTEGER NOT NULL DEFAULT 0,
    notifications_enabled INTEGER NOT NULL DEFAULT 1,
    hardcore INTEGER NOT NULL DEFAULT 0,
    time_multiplier REAL NOT NULL DEFAULT 1.0,
    last_payroll_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payroll_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    gross_wages INTEGER NOT NULL,
    cash_paid INTEGER NOT NULL,
    deposit_added INTEGER NOT NULL,
    employee_count INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'paid',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_inbox_player_status ON inbox(player_id, status, priority);
CREATE INDEX IF NOT EXISTS idx_disputes_player_status ON disputes(player_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_player_created ON orders(player_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_repeat ON orders(player_id, customer_was_repeat, created_at);
CREATE INDEX IF NOT EXISTS idx_batches_player_status ON batches(player_id, status);
CREATE INDEX IF NOT EXISTS idx_batches_responsible ON batches(player_id, responsible_employee_id, status);
CREATE INDEX IF NOT EXISTS idx_reviews_product_created ON reviews(player_id, product_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reviews_employee_created ON reviews(player_id, employee_id, created_at);
CREATE INDEX IF NOT EXISTS idx_employees_player_active ON employees(player_id, active);
CREATE INDEX IF NOT EXISTS idx_payroll_player_created ON payroll_runs(player_id, created_at);
"""


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        """Temporary compatibility helper for lower layers; fresh schema already contains live columns."""
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
