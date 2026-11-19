-- ============================================================================
-- MIGRATION 009: COMPLETE 18-ROLE AGENT ECOSYSTEM AND SALES COPILOT
-- Step 09: Agent Catalog, Interactive Specialists, Background Agents, Copilot
-- Invariants: Invariant 2 (Deterministic Commerce), Invariant 4 (Zero-Trust RLS), Invariant 9 (VRAM Envelope)
-- ============================================================================

-- Table 1: Agent Role Definitions & Capability Metadata
CREATE TABLE IF NOT EXISTS agent_definitions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    role_id VARCHAR(32) NOT NULL,
    role_code VARCHAR(16) NOT NULL,
    role_group VARCHAR(32) NOT NULL,
    display_name VARCHAR(128) NOT NULL,
    description TEXT NOT NULL,
    model_tier VARCHAR(32) NOT NULL DEFAULT 'PRIMARY_4B',
    context_token_cap INTEGER NOT NULL DEFAULT 4096,
    allowed_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
    retrieval_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt_version VARCHAR(32) NOT NULL DEFAULT 'v1.0',
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_definitions_tenant_role UNIQUE (tenant_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_definitions_tenant ON agent_definitions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_definitions_group ON agent_definitions(tenant_id, role_group);

ALTER TABLE agent_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_definitions FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_agent_definitions ON agent_definitions;
    CREATE POLICY tenant_isolation_agent_definitions ON agent_definitions
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Table 2: Agent Execution Traces & Activity Logs
CREATE TABLE IF NOT EXISTS agent_execution_logs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id VARCHAR(36) REFERENCES conversations(id) ON DELETE SET NULL,
    agent_role VARCHAR(64) NOT NULL,
    execution_class VARCHAR(32) NOT NULL DEFAULT 'BOUNDED_REASONING_TURN',
    turn_id VARCHAR(64),
    trace_id VARCHAR(64) NOT NULL,
    input_summary TEXT,
    output_summary TEXT,
    tools_called JSONB NOT NULL DEFAULT '[]'::jsonb,
    model_name VARCHAR(64) NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'SUCCESS',
    error_details TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_tenant ON agent_execution_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_conv ON agent_execution_logs(tenant_id, conversation_id);
CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_role ON agent_execution_logs(tenant_id, agent_role);
CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_status ON agent_execution_logs(tenant_id, status);

ALTER TABLE agent_execution_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_execution_logs FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_agent_execution_logs ON agent_execution_logs;
    CREATE POLICY tenant_isolation_agent_execution_logs ON agent_execution_logs
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Table 3: Representative Copilot Briefs & Action Proposals
CREATE TABLE IF NOT EXISTS copilot_briefs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    representative_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    brief_type VARCHAR(32) NOT NULL,
    customer_summary TEXT NOT NULL,
    suggested_replies JSONB NOT NULL DEFAULT '[]'::jsonb,
    proposed_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    requires_human_approval BOOLEAN NOT NULL DEFAULT FALSE,
    is_approved BOOLEAN,
    approved_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_copilot_briefs_tenant ON copilot_briefs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_copilot_briefs_conv ON copilot_briefs(tenant_id, conversation_id);
CREATE INDEX IF NOT EXISTS idx_copilot_briefs_rep ON copilot_briefs(tenant_id, representative_id);

ALTER TABLE copilot_briefs ENABLE ROW LEVEL SECURITY;
ALTER TABLE copilot_briefs FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_copilot_briefs ON copilot_briefs;
    CREATE POLICY tenant_isolation_copilot_briefs ON copilot_briefs
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Table 4: Agent Offline Evaluations & Benchmarks
CREATE TABLE IF NOT EXISTS agent_evaluations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    suite_name VARCHAR(64) NOT NULL,
    total_cases INTEGER NOT NULL,
    passed_cases INTEGER NOT NULL,
    failed_cases INTEGER NOT NULL,
    accuracy_score NUMERIC(5, 2) NOT NULL,
    category_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    details JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_evaluations_tenant ON agent_evaluations(tenant_id);

ALTER TABLE agent_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_evaluations FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_agent_evaluations ON agent_evaluations;
    CREATE POLICY tenant_isolation_agent_evaluations ON agent_evaluations
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


-- Least Privilege Grants to Application User
GRANT SELECT, INSERT, UPDATE, DELETE ON agent_definitions TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON agent_execution_logs TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON copilot_briefs TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON agent_evaluations TO sales_app_user;
