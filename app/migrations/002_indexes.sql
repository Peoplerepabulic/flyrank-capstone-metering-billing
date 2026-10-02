-- Migration 002: indexes for the hot paths.
-- Metering reads: per-tenant, per-period rollups.
-- Idempotency + webhook dedupe are enforced by UNIQUE constraints in 001;
-- these indexes keep the lookups fast.

CREATE INDEX IF NOT EXISTS idx_usage_tenant_period
    ON usage_events (tenant_id, period);
CREATE INDEX IF NOT EXISTS idx_usage_tenant_key
    ON usage_events (tenant_id, idempotency_key);
CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant
    ON subscriptions (tenant_id);
CREATE INDEX IF NOT EXISTS idx_alerts_created
    ON alerts (created_at);
