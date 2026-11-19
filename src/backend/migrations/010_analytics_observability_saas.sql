-- ============================================================================
-- MIGRATION 010: GOVERNED ANALYTICS, OBSERVABILITY, TELEMETRY & SAAS ADMINISTRATION
-- Step 11: Analytics Read-Models, Forecasting, Quota Metering, Alerts, System Metrics
-- Invariants: Invariant 2 (Deterministic Commerce), Invariant 4 (Zero-Trust RLS), Invariant 3 (PostgreSQL Truth)
-- ============================================================================

-- Table 1: Tenant Subscriptions & Plans
CREATE TABLE IF NOT EXISTS tenant_subscriptions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    plan_id VARCHAR(32) NOT NULL DEFAULT 'professional',
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    current_period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    current_period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    monthly_token_limit BIGINT NOT NULL DEFAULT 5000000,
    monthly_voice_minutes_limit INTEGER NOT NULL DEFAULT 1000,
    monthly_api_call_limit BIGINT NOT NULL DEFAULT 100000,
    max_seats INTEGER NOT NULL DEFAULT 25,
    features_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_subscriptions_tenant UNIQUE (tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_tenant ON tenant_subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_status ON tenant_subscriptions(tenant_id, status);

ALTER TABLE tenant_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_subscriptions FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_tenant_subscriptions ON tenant_subscriptions;
    CREATE POLICY tenant_isolation_tenant_subscriptions ON tenant_subscriptions
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Table 2: Tenant Usage Meters (Monthly Ledgers)
CREATE TABLE IF NOT EXISTS tenant_usage_meters (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    period_month VARCHAR(7) NOT NULL,
    llm_input_tokens BIGINT NOT NULL DEFAULT 0,
    llm_output_tokens BIGINT NOT NULL DEFAULT 0,
    total_tokens BIGINT NOT NULL DEFAULT 0,
    voice_seconds BIGINT NOT NULL DEFAULT 0,
    api_requests_count BIGINT NOT NULL DEFAULT 0,
    storage_bytes_used BIGINT NOT NULL DEFAULT 0,
    active_users_count INTEGER NOT NULL DEFAULT 0,
    last_updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_usage_meters_tenant_period UNIQUE (tenant_id, period_month)
);

CREATE INDEX IF NOT EXISTS idx_tenant_usage_meters_tenant ON tenant_usage_meters(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_usage_meters_period ON tenant_usage_meters(tenant_id, period_month);

ALTER TABLE tenant_usage_meters ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_usage_meters FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_tenant_usage_meters ON tenant_usage_meters;
    CREATE POLICY tenant_isolation_tenant_usage_meters ON tenant_usage_meters
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Table 3: Tenant Quota Limits & Thresholds
CREATE TABLE IF NOT EXISTS tenant_quota_limits (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    metric_name VARCHAR(64) NOT NULL,
    limit_value BIGINT NOT NULL,
    warning_threshold_pct INTEGER NOT NULL DEFAULT 80,
    enforce_hard_cap BOOLEAN NOT NULL DEFAULT TRUE,
    is_exhausted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_quota_limits_tenant_metric UNIQUE (tenant_id, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_tenant_quota_limits_tenant ON tenant_quota_limits(tenant_id);

ALTER TABLE tenant_quota_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_quota_limits FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_tenant_quota_limits ON tenant_quota_limits;
    CREATE POLICY tenant_isolation_tenant_quota_limits ON tenant_quota_limits
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Table 4: Daily Sales & Revenue Aggregation Read-Model
CREATE TABLE IF NOT EXISTS analytics_daily_sales (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    total_revenue_cents BIGINT NOT NULL DEFAULT 0,
    order_count INTEGER NOT NULL DEFAULT 0,
    paid_order_count INTEGER NOT NULL DEFAULT 0,
    refund_count INTEGER NOT NULL DEFAULT 0,
    refund_total_cents BIGINT NOT NULL DEFAULT 0,
    net_revenue_cents BIGINT NOT NULL DEFAULT 0,
    average_order_value_cents BIGINT NOT NULL DEFAULT 0,
    currency VARCHAR(10) NOT NULL DEFAULT 'MAD',
    last_aggregated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_analytics_daily_sales_tenant_date_curr UNIQUE (tenant_id, date, currency)
);

CREATE INDEX IF NOT EXISTS idx_analytics_daily_sales_tenant ON analytics_daily_sales(tenant_id);
CREATE INDEX IF NOT EXISTS idx_analytics_daily_sales_date ON analytics_daily_sales(tenant_id, date);

ALTER TABLE analytics_daily_sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_daily_sales FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_analytics_daily_sales ON analytics_daily_sales;
    CREATE POLICY tenant_isolation_analytics_daily_sales ON analytics_daily_sales
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Table 5: Pipeline & Deal Stage Snapshots Read-Model
CREATE TABLE IF NOT EXISTS analytics_pipeline_snapshots (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    stage VARCHAR(50) NOT NULL,
    deal_count INTEGER NOT NULL DEFAULT 0,
    total_value_cents BIGINT NOT NULL DEFAULT 0,
    weighted_value_cents BIGINT NOT NULL DEFAULT 0,
    currency VARCHAR(10) NOT NULL DEFAULT 'MAD',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_pipeline_snapshots_tenant_date_stage_curr UNIQUE (tenant_id, snapshot_date, stage, currency)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_snapshots_tenant ON analytics_pipeline_snapshots(tenant_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_snapshots_date ON analytics_pipeline_snapshots(tenant_id, snapshot_date);

ALTER TABLE analytics_pipeline_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_pipeline_snapshots FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_analytics_pipeline_snapshots ON analytics_pipeline_snapshots;
    CREATE POLICY tenant_isolation_analytics_pipeline_snapshots ON analytics_pipeline_snapshots
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Table 6: AI Performance, Latency & Quality Metrics
CREATE TABLE IF NOT EXISTS analytics_ai_performance (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    agent_role VARCHAR(64) NOT NULL,
    total_executions INTEGER NOT NULL DEFAULT 0,
    successful_executions INTEGER NOT NULL DEFAULT 0,
    failed_executions INTEGER NOT NULL DEFAULT 0,
    total_input_tokens BIGINT NOT NULL DEFAULT 0,
    total_output_tokens BIGINT NOT NULL DEFAULT 0,
    avg_latency_ms INTEGER NOT NULL DEFAULT 0,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    human_handoff_count INTEGER NOT NULL DEFAULT 0,
    last_aggregated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_analytics_ai_perf_tenant_date_role UNIQUE (tenant_id, date, agent_role)
);

CREATE INDEX IF NOT EXISTS idx_analytics_ai_perf_tenant ON analytics_ai_performance(tenant_id);
CREATE INDEX IF NOT EXISTS idx_analytics_ai_perf_date ON analytics_ai_performance(tenant_id, date);

ALTER TABLE analytics_ai_performance ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_ai_performance FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_analytics_ai_performance ON analytics_ai_performance;
    CREATE POLICY tenant_isolation_analytics_ai_performance ON analytics_ai_performance
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Table 7: System Alert Events & Reliability Incidents
CREATE TABLE IF NOT EXISTS system_alert_events (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    alert_id VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'WARNING',
    source VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
    acknowledged_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_system_alert_events_tenant ON system_alert_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_system_alert_events_status ON system_alert_events(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_system_alert_events_severity ON system_alert_events(tenant_id, severity);

ALTER TABLE system_alert_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_alert_events FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_system_alert_events ON system_alert_events;
    CREATE POLICY tenant_isolation_system_alert_events ON system_alert_events
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Table 8: System Metric Snapshots & Telemetry
CREATE TABLE IF NOT EXISTS system_metric_snapshots (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    metric_family VARCHAR(64) NOT NULL,
    metric_name VARCHAR(64) NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_system_metric_snapshots_tenant ON system_metric_snapshots(tenant_id);
CREATE INDEX IF NOT EXISTS idx_system_metric_snapshots_family ON system_metric_snapshots(tenant_id, metric_family);
CREATE INDEX IF NOT EXISTS idx_system_metric_snapshots_time ON system_metric_snapshots(tenant_id, recorded_at);

ALTER TABLE system_metric_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_metric_snapshots FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_system_metric_snapshots ON system_metric_snapshots;
    CREATE POLICY tenant_isolation_system_metric_snapshots ON system_metric_snapshots
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Least Privilege Grants to Application User
GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_subscriptions TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_usage_meters TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_quota_limits TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON analytics_daily_sales TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON analytics_pipeline_snapshots TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON analytics_ai_performance TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON system_alert_events TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON system_metric_snapshots TO sales_app_user;
