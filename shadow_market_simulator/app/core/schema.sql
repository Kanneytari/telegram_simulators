PRAGMA journal_mode = WAL;

PRAGMA foreign_keys = ON;

CREATE TABLE analytics_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    run_id TEXT,
    event_kind TEXT NOT NULL,
    event_name TEXT NOT NULL,
    source TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    balance INTEGER,
    rating REAL,
    time_multiplier REAL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE batches (
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

CREATE TABLE candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    role TEXT NOT NULL,
    deposit INTEGER NOT NULL,
    has_car INTEGER NOT NULL,
    reliability REAL NOT NULL,
    attention REAL NOT NULL,
    honesty REAL NOT NULL,
    loyalty REAL NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    campaign_id INTEGER,
    source_channel TEXT,
    min_deposit INTEGER,
    experience_level INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE client_relationships (
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    purchases INTEGER NOT NULL DEFAULT 0,
    lifetime_value INTEGER NOT NULL DEFAULT 0,
    trust REAL NOT NULL DEFAULT 0.48,
    last_product_rating INTEGER,
    last_courier_rating INTEGER,
    last_purchase_at TEXT,
    PRIMARY KEY(player_id, client_id)
);

CREATE TABLE clients (
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
    review_tendency REAL NOT NULL
);

CREATE TABLE compensation_policy_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value INTEGER NOT NULL,
    new_value INTEGER NOT NULL,
    loyalty_delta REAL NOT NULL DEFAULT 0,
    stress_delta REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE courier_candidate_profiles (
    candidate_id INTEGER PRIMARY KEY REFERENCES candidates(id) ON DELETE CASCADE,
    pace REAL NOT NULL,
    precision REAL NOT NULL,
    resilience REAL NOT NULL,
    integrity REAL NOT NULL,
    trait TEXT NOT NULL,
    transport_level INTEGER NOT NULL DEFAULT 0 CHECK(transport_level BETWEEN 0 AND 2),
    phone_level INTEGER NOT NULL DEFAULT 0 CHECK(phone_level BETWEEN 0 AND 2)
);

CREATE TABLE courier_management (
    employee_id INTEGER PRIMARY KEY REFERENCES employees(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    deposit_target INTEGER NOT NULL DEFAULT 60000,
    deposit_contribution_pct INTEGER NOT NULL DEFAULT 50,
    transport_level INTEGER NOT NULL DEFAULT 0 CHECK(transport_level BETWEEN 0 AND 2),
    phone_level INTEGER NOT NULL DEFAULT 0 CHECK(phone_level BETWEEN 0 AND 2),
    invested_total INTEGER NOT NULL DEFAULT 0,
    bonuses_given INTEGER NOT NULL DEFAULT 0,
    rests_taken INTEGER NOT NULL DEFAULT 0,
    last_bonus_at TEXT,
    last_rest_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE courier_management_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    loyalty_delta REAL NOT NULL DEFAULT 0,
    stress_delta REAL NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE courier_profiles (
    employee_id INTEGER PRIMARY KEY REFERENCES employees(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    pace REAL NOT NULL,
    precision REAL NOT NULL,
    resilience REAL NOT NULL,
    integrity REAL NOT NULL,
    trait TEXT NOT NULL,
    prep_tasks INTEGER NOT NULL DEFAULT 0,
    prep_units INTEGER NOT NULL DEFAULT 0,
    prep_game_hours REAL NOT NULL DEFAULT 0,
    pace_observation_sum REAL NOT NULL DEFAULT 0,
    pace_observation_count INTEGER NOT NULL DEFAULT 0,
    observed_orders INTEGER NOT NULL DEFAULT 0,
    rating_sum INTEGER NOT NULL DEFAULT 0,
    high_stress_orders INTEGER NOT NULL DEFAULT 0,
    high_stress_rating_sum INTEGER NOT NULL DEFAULT 0,
    negative_events INTEGER NOT NULL DEFAULT 0,
    missed_shifts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE courier_task_metrics (
    task_id INTEGER PRIMARY KEY REFERENCES employee_tasks(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    planned_game_hours REAL NOT NULL,
    effective_pace REAL NOT NULL,
    stress_at_start REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE disputes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    true_cause TEXT NOT NULL,
    message TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    courier_reply TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    decision TEXT,
    refund_amount INTEGER NOT NULL DEFAULT 0,
    refund_source TEXT,
    refund_employee_id INTEGER,
    deadline_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE TABLE employee_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    batch_id INTEGER REFERENCES batches(id),
    allocation_id INTEGER,
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completes_at TEXT NOT NULL,
    note TEXT
);

CREATE TABLE employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    role TEXT NOT NULL,
    deposit INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE game_clock (
    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
    game_hours REAL NOT NULL DEFAULT 0
);

CREATE TABLE inbox (
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

CREATE TABLE ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    kind TEXT NOT NULL,
    reference_type TEXT,
    reference_id INTEGER,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    pack_size INTEGER NOT NULL,
    price INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(player_id, product_id, pack_size)
);

CREATE TABLE order_ratings (
    order_id INTEGER PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_rating INTEGER NOT NULL CHECK(product_rating BETWEEN 1 AND 5),
    courier_rating INTEGER NOT NULL CHECK(courier_rating BETWEEN 1 AND 5),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
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

CREATE TABLE payroll_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    gross_wages INTEGER NOT NULL,
    cash_paid INTEGER NOT NULL,
    deposit_added INTEGER NOT NULL,
    employee_count INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'paid',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE player_tips (
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    shown_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(player_id, code)
);

CREATE TABLE procurement_market_state (
    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
    last_rotation_at TEXT NOT NULL
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    base_market_price INTEGER NOT NULL,
    base_demand REAL NOT NULL,
    complaint_modifier REAL NOT NULL DEFAULT 1.0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE publication_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    allocation_id INTEGER NOT NULL UNIQUE REFERENCES retail_allocations(id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    units INTEGER NOT NULL,
    positions INTEGER NOT NULL,
    game_hour REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE recruitment_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'courier',
    channel TEXT NOT NULL,
    cost INTEGER NOT NULL,
    resolves_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    candidates_created INTEGER NOT NULL DEFAULT 0,
    traffic_multiplier INTEGER NOT NULL DEFAULT 1,
    duration_hours INTEGER NOT NULL DEFAULT 4,
    min_deposit INTEGER NOT NULL DEFAULT 25000,
    transport_required INTEGER NOT NULL DEFAULT 0 CHECK(transport_required BETWEEN 0 AND 2),
    experience_required INTEGER NOT NULL DEFAULT 0,
    expected_min INTEGER NOT NULL DEFAULT 0,
    expected_max INTEGER NOT NULL DEFAULT 0,
    terms_fixed_fee INTEGER NOT NULL DEFAULT 0,
    terms_base_rate_bps INTEGER NOT NULL DEFAULT 0,
    terms_risk_rate_bps INTEGER NOT NULL DEFAULT 0,
    terms_deposit_pct INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE TABLE recruitment_drafts (
    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'courier',
    channel TEXT NOT NULL DEFAULT 'stickers',
    traffic_multiplier INTEGER NOT NULL DEFAULT 1,
    duration_hours INTEGER NOT NULL DEFAULT 4,
    min_deposit INTEGER NOT NULL DEFAULT 25000,
    transport_required INTEGER NOT NULL DEFAULT 0 CHECK(transport_required BETWEEN 0 AND 2),
    experience_required INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE retail_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    wholesale_employee_id INTEGER NOT NULL REFERENCES employees(id),
    retail_employee_id INTEGER NOT NULL REFERENCES employees(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_cost INTEGER NOT NULL,
    quality REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    received_at TEXT,
    completed_at TEXT
);

CREATE TABLE retail_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    allocation_id INTEGER NOT NULL REFERENCES retail_allocations(id) ON DELETE CASCADE,
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    pack_size INTEGER NOT NULL,
    position_count INTEGER NOT NULL,
    unit_cost INTEGER NOT NULL,
    quality REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(allocation_id, pack_size)
);

CREATE TABLE settings (
    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
    auto_refund_limit INTEGER NOT NULL DEFAULT 0,
    auto_partial_limit INTEGER NOT NULL DEFAULT 0,
    notifications_enabled INTEGER NOT NULL DEFAULT 1,
    hardcore INTEGER NOT NULL DEFAULT 0,
    time_multiplier REAL NOT NULL DEFAULT 1.0,
    last_payroll_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE shop_packaging_rules (
    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
    pct_1 INTEGER NOT NULL DEFAULT 60,
    pct_2 INTEGER NOT NULL DEFAULT 30,
    pct_5 INTEGER NOT NULL DEFAULT 10,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE shop_trust_state (
    player_id INTEGER PRIMARY KEY REFERENCES shops(player_id) ON DELETE CASCADE,
    trust_score REAL NOT NULL DEFAULT 64.0,
    availability_ema REAL NOT NULL DEFAULT 0.60,
    fairness_ema REAL NOT NULL DEFAULT 0.65,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE shops (
    player_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT NOT NULL DEFAULT 'NIGHTSHIFT',
    balance INTEGER NOT NULL DEFAULT 150000,
    reserve_target INTEGER NOT NULL DEFAULT 30000,
    employee_reputation REAL NOT NULL DEFAULT 50.0,
    supplier_reputation REAL NOT NULL DEFAULT 50.0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_simulated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_revenue INTEGER NOT NULL DEFAULT 0,
    total_profit INTEGER NOT NULL DEFAULT 0,
    total_orders INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE staff_compensation_policies (
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('courier','warehouse')),
    fixed_fee INTEGER NOT NULL DEFAULT 0,
    base_rate_bps INTEGER NOT NULL DEFAULT 0,
    risk_rate_bps INTEGER NOT NULL DEFAULT 0,
    deposit_contribution_pct INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(player_id, role)
);

CREATE TABLE staff_relationship_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    kind TEXT NOT NULL,
    reference_type TEXT,
    reference_id INTEGER,
    loyalty_delta REAL NOT NULL DEFAULT 0,
    stress_delta REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE supplier_offers (
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

CREATE TABLE suppliers (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    price_modifier REAL NOT NULL,
    quality_mean REAL NOT NULL,
    quality_sigma REAL NOT NULL,
    reliability REAL NOT NULL
);

CREATE TABLE wholesale_delivery_payments (
    allocation_id INTEGER PRIMARY KEY REFERENCES retail_allocations(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES shops(player_id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    goods_value INTEGER NOT NULL,
    uncovered_value INTEGER NOT NULL DEFAULT 0,
    base_amount INTEGER NOT NULL,
    risk_amount INTEGER NOT NULL DEFAULT 0,
    amount INTEGER NOT NULL,
    deposit_contribution INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_allocations_retail_status ON retail_allocations(player_id, retail_employee_id, status);

CREATE INDEX idx_analytics_event_name ON analytics_events(event_name, created_at);

CREATE INDEX idx_analytics_kind ON analytics_events(event_kind, created_at);

CREATE INDEX idx_analytics_player_time ON analytics_events(player_id, created_at, id);

CREATE INDEX idx_analytics_run_time ON analytics_events(run_id, created_at, id);

CREATE INDEX idx_batches_player_status ON batches(player_id, status);

CREATE INDEX idx_batches_responsible ON batches(player_id, responsible_employee_id, status);

CREATE INDEX idx_client_relationships_value ON client_relationships(player_id, purchases, trust);

CREATE INDEX idx_courier_management_events_employee
    ON courier_management_events(player_id, employee_id, created_at);

CREATE INDEX idx_courier_management_player
    ON courier_management(player_id, employee_id);

CREATE INDEX idx_courier_profiles_player
    ON courier_profiles(player_id, employee_id);

CREATE INDEX idx_disputes_player_status ON disputes(player_id, status);

CREATE INDEX idx_employees_player_active ON employees(player_id, active);

CREATE INDEX idx_inbox_player_status ON inbox(player_id, status, priority);

CREATE INDEX idx_order_ratings_client ON order_ratings(player_id, client_id, created_at);

CREATE INDEX idx_order_ratings_employee ON order_ratings(player_id, employee_id, created_at);

CREATE INDEX idx_order_ratings_product ON order_ratings(player_id, product_id, created_at);

CREATE INDEX idx_orders_player_created ON orders(player_id, created_at);

CREATE INDEX idx_orders_repeat ON orders(player_id, customer_was_repeat, created_at);

CREATE INDEX idx_payroll_player_created ON payroll_runs(player_id, created_at);

CREATE INDEX idx_positions_employee ON retail_positions(player_id, employee_id, position_count);

CREATE INDEX idx_positions_product_pack ON retail_positions(player_id, product_id, pack_size, position_count);

CREATE INDEX idx_publication_employee_game_hour
    ON publication_events(player_id, employee_id, game_hour);

CREATE INDEX idx_recruitment_player_status
    ON recruitment_campaigns(player_id, status, resolves_at);

CREATE INDEX idx_staff_relationship_events_employee
    ON staff_relationship_events(player_id, employee_id, created_at);

CREATE INDEX idx_supplier_offers_market
    ON supplier_offers(player_id, product_id, quantity, status);

CREATE INDEX idx_tasks_employee_active ON employee_tasks(employee_id, status);

CREATE INDEX idx_tasks_player_active ON employee_tasks(player_id, status, completes_at);

CREATE INDEX idx_wholesale_delivery_payments_employee
    ON wholesale_delivery_payments(player_id, employee_id, created_at);

CREATE TRIGGER trg_close_empty_recruitment_result_on_insert
AFTER INSERT ON inbox
WHEN NEW.kind='recruitment_result'
BEGIN
    UPDATE inbox
       SET status='closed'
     WHERE id=NEW.id
       AND NOT EXISTS (
           SELECT 1
             FROM candidates c
            WHERE c.player_id=NEW.player_id
              AND c.status='open'
              AND c.campaign_id IS NOT NULL
       );
END;

CREATE TRIGGER trg_close_recruitment_result_after_candidate_delete
AFTER DELETE ON candidates
WHEN OLD.status='open'
BEGIN
    UPDATE inbox
       SET status='closed'
     WHERE player_id=OLD.player_id
       AND kind='recruitment_result'
       AND status='open'
       AND NOT EXISTS (
           SELECT 1
             FROM candidates c
            WHERE c.player_id=OLD.player_id
              AND c.status='open'
              AND c.campaign_id IS NOT NULL
       );
END;

CREATE TRIGGER trg_close_recruitment_result_after_candidate_update
AFTER UPDATE OF status ON candidates
WHEN OLD.status='open' AND NEW.status<>'open'
BEGIN
    UPDATE inbox
       SET status='closed'
     WHERE player_id=NEW.player_id
       AND kind='recruitment_result'
       AND status='open'
       AND NOT EXISTS (
           SELECT 1
             FROM candidates c
            WHERE c.player_id=NEW.player_id
              AND c.status='open'
              AND c.campaign_id IS NOT NULL
       );
END;

CREATE TRIGGER trg_employee_theft_to_staff_inbox
                AFTER INSERT ON inbox
                WHEN NEW.kind='employee_theft'
                BEGIN
                    UPDATE inbox SET kind='employee_exit' WHERE id=NEW.id;
                END;
