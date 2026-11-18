-- Migration 007: Durable Workflows, Notifications, and Automations
-- Step 07: Durable Workflows, Notifications and Peripheral Integrations
-- (Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)

-- 1. Workflow Executions Table (Durable Sagas)
CREATE TABLE IF NOT EXISTS workflow_executions (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    workflow_type VARCHAR(100) NOT NULL,
    correlation_id VARCHAR(100) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'RUNNING',
    current_step VARCHAR(100),
    payload_json JSONB NOT NULL DEFAULT '{}',
    result_json JSONB DEFAULT '{}',
    error_details TEXT,
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT chk_workflow_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'COMPENSATING', 'COMPENSATED')),
    CONSTRAINT uq_workflow_tenant_idempotency UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_workflow_executions_tenant_status ON workflow_executions(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_correlation ON workflow_executions(tenant_id, correlation_id);

-- 2. Workflow Step Logs (Audit and Compensation Traceability)
CREATE TABLE IF NOT EXISTS workflow_step_logs (
    id VARCHAR(36) PRIMARY KEY,
    workflow_id VARCHAR(36) NOT NULL REFERENCES workflow_executions(id) ON DELETE CASCADE,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    step_name VARCHAR(100) NOT NULL,
    step_type VARCHAR(30) NOT NULL DEFAULT 'ACTION',
    status VARCHAR(30) NOT NULL DEFAULT 'STARTED',
    input_json JSONB DEFAULT '{}',
    output_json JSONB DEFAULT '{}',
    error_message TEXT,
    duration_ms INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT chk_workflow_step_type CHECK (step_type IN ('ACTION', 'COMPENSATION')),
    CONSTRAINT chk_workflow_step_status CHECK (status IN ('STARTED', 'COMPLETED', 'FAILED'))
);

CREATE INDEX IF NOT EXISTS idx_workflow_step_logs_wf ON workflow_step_logs(workflow_id, created_at);

-- 3. Notification Templates Table
CREATE TABLE IF NOT EXISTS notification_templates (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    template_code VARCHAR(100) NOT NULL,
    channel_type VARCHAR(30) NOT NULL,
    message_class VARCHAR(30) NOT NULL DEFAULT 'TRANSACTIONAL',
    language VARCHAR(10) NOT NULL DEFAULT 'fr-FR',
    subject_template VARCHAR(255),
    body_template TEXT NOT NULL,
    variables_json JSONB DEFAULT '[]',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT chk_notif_tmpl_class CHECK (message_class IN ('MARKETING', 'TRANSACTIONAL', 'SERVICE', 'SECURITY')),
    CONSTRAINT uq_notif_tmpl UNIQUE (tenant_id, template_code, channel_type, language)
);

CREATE INDEX IF NOT EXISTS idx_notif_templates_lookup ON notification_templates(tenant_id, template_code, channel_type);

-- 4. Notification Logs Table (Delivery Auditing)
CREATE TABLE IF NOT EXISTS notification_logs (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    template_id VARCHAR(36) REFERENCES notification_templates(id) ON DELETE SET NULL,
    recipient_identifier VARCHAR(255) NOT NULL,
    channel_type VARCHAR(30) NOT NULL,
    message_class VARCHAR(30) NOT NULL DEFAULT 'TRANSACTIONAL',
    subject VARCHAR(255),
    content TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    error_reason TEXT,
    retry_count INT NOT NULL DEFAULT 0,
    metadata_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    sent_at TIMESTAMPTZ,
    CONSTRAINT chk_notif_log_status CHECK (status IN ('PENDING', 'SENT', 'DELIVERED', 'FAILED', 'CANCELLED')),
    CONSTRAINT chk_notif_log_class CHECK (message_class IN ('MARKETING', 'TRANSACTIONAL', 'SERVICE', 'SECURITY'))
);

CREATE INDEX IF NOT EXISTS idx_notif_logs_tenant_status ON notification_logs(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_notif_logs_recipient ON notification_logs(tenant_id, recipient_identifier);

-- 5. Automation Rules Table (Event-Driven Rules)
CREATE TABLE IF NOT EXISTS automation_rules (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(150) NOT NULL,
    trigger_event VARCHAR(100) NOT NULL,
    condition_json JSONB DEFAULT '{}',
    action_type VARCHAR(100) NOT NULL,
    action_config_json JSONB DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_automation_rules_trigger ON automation_rules(tenant_id, trigger_event) WHERE is_active = true;

-- Enable and Force Row-Level Security
ALTER TABLE workflow_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_executions FORCE ROW LEVEL SECURITY;

ALTER TABLE workflow_step_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_step_logs FORCE ROW LEVEL SECURITY;

ALTER TABLE notification_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_templates FORCE ROW LEVEL SECURITY;

ALTER TABLE notification_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_logs FORCE ROW LEVEL SECURITY;

ALTER TABLE automation_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE automation_rules FORCE ROW LEVEL SECURITY;

-- Create Tenant Isolation Policies
DROP POLICY IF EXISTS tenant_isolation_workflow_executions ON workflow_executions;
CREATE POLICY tenant_isolation_workflow_executions ON workflow_executions
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

DROP POLICY IF EXISTS tenant_isolation_workflow_step_logs ON workflow_step_logs;
CREATE POLICY tenant_isolation_workflow_step_logs ON workflow_step_logs
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

DROP POLICY IF EXISTS tenant_isolation_notification_templates ON notification_templates;
CREATE POLICY tenant_isolation_notification_templates ON notification_templates
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

DROP POLICY IF EXISTS tenant_isolation_notification_logs ON notification_logs;
CREATE POLICY tenant_isolation_notification_logs ON notification_logs
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

DROP POLICY IF EXISTS tenant_isolation_automation_rules ON automation_rules;
CREATE POLICY tenant_isolation_automation_rules ON automation_rules
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

-- Grant table permissions to application role
GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_executions TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_step_logs TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON notification_templates TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON notification_logs TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON automation_rules TO sales_app_user;
