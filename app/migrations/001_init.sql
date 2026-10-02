-- Migration 001: core tables.
-- Money is stored as INTEGER microdollars (1e-6 USD). Never floats.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    api_calls_quota INTEGER NOT NULL,
    ai_tokens_quota INTEGER NOT NULL,
    monthly_price_cents INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    api_key TEXT NOT NULL UNIQUE,
    plan_id TEXT NOT NULL REFERENCES plans(id),
    subscription_status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    provider TEXT NOT NULL,
    provider_subscription_id TEXT,
    provider_customer_id TEXT,
    status TEXT NOT NULL,
    plan_id TEXT NOT NULL REFERENCES plans(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    period TEXT NOT NULL,                      -- 'YYYY-MM', monthly rollup bucket
    idempotency_key TEXT NOT NULL,
    api_calls INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    cost_microdollars INTEGER NOT NULL,        -- integer money, never float
    response_json TEXT NOT NULL,               -- stored so replays mirror the original
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (tenant_id, idempotency_key)         -- the exactly-once guarantee
);

CREATE TABLE IF NOT EXISTS webhook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL UNIQUE,    -- replayed events are ignored here
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT (datetime('now')),
    result TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
