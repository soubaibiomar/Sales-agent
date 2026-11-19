-- Migration 008: RAG Knowledge Base and Model Gateway Ledger
-- Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
-- Controls: 39-40, 49, 63, 65-67; SAI-06 to SAI-10, SAI-12; ADR-008

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    source_type VARCHAR(50) NOT NULL DEFAULT 'TEXT', -- TEXT, FILE, CATALOG, POLICY, FAQ
    document_hash VARCHAR(64) NOT NULL,
    acl_roles TEXT[] NOT NULL DEFAULT ARRAY['public'], -- Roles permitted to retrieve this doc
    status VARCHAR(50) NOT NULL DEFAULT 'INDEXED', -- INDEXED, TOMBSTONED, POISON_DETECTED
    poison_reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_knowledge_documents_tenant_status ON knowledge_documents(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_hash ON knowledge_documents(tenant_id, document_hash);

-- Enable & Force RLS
ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_documents FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_policy ON knowledge_documents;
    DROP POLICY IF EXISTS tenant_isolation_knowledge_documents ON knowledge_documents;
    CREATE POLICY tenant_isolation_knowledge_documents ON knowledge_documents
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    document_id VARCHAR(36) NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    sanitized_content TEXT NOT NULL,
    token_count INT NOT NULL DEFAULT 0,
    embedding_vector DOUBLE PRECISION[] NOT NULL DEFAULT ARRAY[]::DOUBLE PRECISION[],
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_tenant_doc ON knowledge_chunks(tenant_id, document_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_doc_index ON knowledge_chunks(document_id, chunk_index);

-- Enable & Force RLS
ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_chunks FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_policy ON knowledge_chunks;
    DROP POLICY IF EXISTS tenant_isolation_knowledge_chunks ON knowledge_chunks;
    CREATE POLICY tenant_isolation_knowledge_chunks ON knowledge_chunks
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;


CREATE TABLE IF NOT EXISTS model_execution_logs (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    turn_id VARCHAR(64),
    conversation_id VARCHAR(36) REFERENCES conversations(id) ON DELETE SET NULL,
    provider VARCHAR(50) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    prompt_template_id VARCHAR(100),
    prompt_hash VARCHAR(64),
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL DEFAULT 0,
    estimated_cost_usd NUMERIC(10, 6) NOT NULL DEFAULT 0.0,
    latency_ms NUMERIC(10, 2) NOT NULL DEFAULT 0.0,
    ttft_ms NUMERIC(10, 2) NOT NULL DEFAULT 0.0,
    pii_redacted_count INT NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'SUCCESS', -- SUCCESS, FALLBACK, TIMEOUT, ERROR, BLOCKED
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_model_execution_logs_tenant ON model_execution_logs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_execution_logs_turn ON model_execution_logs(turn_id);

-- Enable & Force RLS
ALTER TABLE model_execution_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_execution_logs FORCE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS tenant_isolation_policy ON model_execution_logs;
    DROP POLICY IF EXISTS tenant_isolation_model_execution_logs ON model_execution_logs;
    CREATE POLICY tenant_isolation_model_execution_logs ON model_execution_logs
        AS PERMISSIVE FOR ALL TO PUBLIC
        USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
END $$;

-- Grants
GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_documents TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_chunks TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON model_execution_logs TO sales_app_user;
