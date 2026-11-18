-- =============================================================================
-- SALES AI MANAGEMENT PLATFORM - DATABASE INITIALIZATION & RLS FOUNDATION
-- =============================================================================

-- 1. Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. Create least-privileged application role (Baseline Controls 07, 41)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sales_app_user') THEN
        CREATE ROLE sales_app_user WITH LOGIN PASSWORD 'sales_app_dev_password';
    END IF;
END
$$;

-- Revoke all default public privileges
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO sales_app_user;

-- 3. Schema Tables (Tenant Core, Memberships, Security & Audit)

-- Tenants Table
CREATE TABLE IF NOT EXISTS tenants (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    tier VARCHAR(50) NOT NULL DEFAULT 'standard',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Organization Sites / Facilities
CREATE TABLE IF NOT EXISTS organization_sites (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    timezone VARCHAR(50) NOT NULL DEFAULT 'Africa/Casablanca',
    currency VARCHAR(10) NOT NULL DEFAULT 'MAD',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_site_tenant_code UNIQUE (tenant_id, code)
);

-- Users Table
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    is_verified BOOLEAN NOT NULL DEFAULT false,
    mfa_enabled BOOLEAN NOT NULL DEFAULT false,
    mfa_secret VARCHAR(255),
    failed_login_attempts INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_user_tenant_email UNIQUE (tenant_id, email)
);

-- System Roles Catalog
CREATE TABLE IF NOT EXISTS roles (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    is_privileged BOOLEAN NOT NULL DEFAULT false
);

-- Granular Permissions Catalog
CREATE TABLE IF NOT EXISTS permissions (
    id VARCHAR(36) PRIMARY KEY,
    code VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    domain VARCHAR(50) NOT NULL
);

-- Role-Permission Mapping
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id VARCHAR(36) NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id VARCHAR(36) NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

-- User-Role Tenant Scoped Assignment
CREATE TABLE IF NOT EXISTS user_roles (
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id VARCHAR(36) NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id, tenant_id)
);

-- Session Revocation Blacklist (JTI tracking)
CREATE TABLE IF NOT EXISTS session_revocations (
    id VARCHAR(36) PRIMARY KEY,
    token_jti VARCHAR(255) UNIQUE NOT NULL,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    reason VARCHAR(255) NOT NULL DEFAULT 'logout'
);

-- Immutable Security & Operational Audit Log (Controls 42, ADR-010)
CREATE TABLE IF NOT EXISTS audit_logs (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    actor_id VARCHAR(36),
    event_type VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_id VARCHAR(255),
    action VARCHAR(50) NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    payload JSONB DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'SUCCESS',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Feature Flags Table
CREATE TABLE IF NOT EXISTS feature_flags (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key VARCHAR(100) NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT false,
    rules JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_tenant_feature_key UNIQUE (tenant_id, key)
);

-- =============================================================================
-- STEP 03 OMNICHANNEL CONVERSATIONS & EVENT INGESTION SCHEMA
-- =============================================================================

-- Contacts Table
CREATE TABLE IF NOT EXISTS contacts (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    display_name VARCHAR(200) NOT NULL,
    primary_email VARCHAR(255),
    primary_phone VARCHAR(50),
    is_verified BOOLEAN NOT NULL DEFAULT false,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Channel Identities Table
CREATE TABLE IF NOT EXISTS channel_identities (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    contact_id VARCHAR(36) NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    channel_type VARCHAR(30) NOT NULL,
    identifier VARCHAR(255) NOT NULL,
    is_opted_out BOOLEAN NOT NULL DEFAULT false,
    opt_out_at TIMESTAMPTZ,
    opt_out_reason VARCHAR(255),
    consent_given_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_tenant_channel_identifier UNIQUE (tenant_id, channel_type, identifier)
);

-- Conversations Table
CREATE TABLE IF NOT EXISTS conversations (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    contact_id VARCHAR(36) NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    channel_type VARCHAR(30) NOT NULL,
    channel_identifier VARCHAR(255) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'BOT_ACTIVE',
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    version INT NOT NULL DEFAULT 1,
    is_ai_silenced BOOLEAN NOT NULL DEFAULT false,
    unread_count INT NOT NULL DEFAULT 0,
    last_message_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Inbound Raw Events (Durable Ingest Buffer)
CREATE TABLE IF NOT EXISTS inbound_raw_events (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    channel_type VARCHAR(30) NOT NULL,
    provider_event_id VARCHAR(255) NOT NULL,
    payload_json TEXT NOT NULL,
    signature_verified BOOLEAN NOT NULL DEFAULT true,
    processing_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    processed_at TIMESTAMPTZ,
    CONSTRAINT uq_tenant_channel_provider_event UNIQUE (tenant_id, channel_type, provider_event_id)
);

-- Conversation Messages Table
CREATE TABLE IF NOT EXISTS conversation_messages (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    sender_type VARCHAR(20) NOT NULL,
    sender_id VARCHAR(36),
    content TEXT NOT NULL,
    content_redacted TEXT,
    event_type VARCHAR(30) NOT NULL DEFAULT 'MESSAGE',
    conversation_version INT NOT NULL DEFAULT 1,
    attachments_json TEXT DEFAULT '[]',
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Message Attachments Table
CREATE TABLE IF NOT EXISTS message_attachments (
    id VARCHAR(36) PRIMARY KEY,
    message_id VARCHAR(36) NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    file_size_bytes INT NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    is_safe BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Transactional Outbox Events Table
CREATE TABLE IF NOT EXISTS outbox_events (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id VARCHAR(36) REFERENCES conversations(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    channel_type VARCHAR(30) NOT NULL,
    recipient_identifier VARCHAR(255) NOT NULL,
    payload_json TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_error TEXT,
    is_high_priority BOOLEAN NOT NULL DEFAULT false,
    claimed_by VARCHAR(100),
    claim_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    processed_at TIMESTAMPTZ
);

-- Indexes for Omnichannel Performance
CREATE INDEX IF NOT EXISTS idx_contacts_tenant ON contacts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_channel_identities_tenant ON channel_identities(tenant_id, channel_type, identifier);
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_status ON conversations(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_contact ON conversations(tenant_id, contact_id);
CREATE INDEX IF NOT EXISTS idx_raw_events_tenant_status ON inbound_raw_events(tenant_id, processing_status);
CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON conversation_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_attachments_msg ON message_attachments(message_id);
CREATE INDEX IF NOT EXISTS idx_outbox_tenant_status ON outbox_events(tenant_id, status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_outbox_claim ON outbox_events(status, claim_expires_at);

-- 4. Enable Row-Level Security (RLS) on all tenant-partitioned tables
ALTER TABLE organization_sites ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_sites FORCE ROW LEVEL SECURITY;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_roles FORCE ROW LEVEL SECURITY;

ALTER TABLE session_revocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_revocations FORCE ROW LEVEL SECURITY;

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;

ALTER TABLE feature_flags ENABLE ROW LEVEL SECURITY;
ALTER TABLE feature_flags FORCE ROW LEVEL SECURITY;

ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts FORCE ROW LEVEL SECURITY;

ALTER TABLE channel_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_identities FORCE ROW LEVEL SECURITY;

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;

ALTER TABLE inbound_raw_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbound_raw_events FORCE ROW LEVEL SECURITY;

ALTER TABLE conversation_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_messages FORCE ROW LEVEL SECURITY;

ALTER TABLE message_attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_attachments FORCE ROW LEVEL SECURITY;

ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox_events FORCE ROW LEVEL SECURITY;

-- 5. Define RLS Isolation Policies
CREATE POLICY tenant_isolation_sites ON organization_sites
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_users ON users
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_user_roles ON user_roles
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_session_revocations ON session_revocations
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_audit_logs ON audit_logs
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_feature_flags ON feature_flags
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_contacts ON contacts
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_channel_identities ON channel_identities
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_conversations ON conversations
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_inbound_raw_events ON inbound_raw_events
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_conversation_messages ON conversation_messages
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_message_attachments ON message_attachments
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_outbox_events ON outbox_events
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

-- 6. Grant least-privilege DML permissions to sales_app_user
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sales_app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sales_app_user;

-- Prevent sales_app_user from truncating or altering tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sales_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO sales_app_user;

-- 7. Seed System Roles & Initial Baseline Permissions
INSERT INTO roles (id, name, description, is_privileged) VALUES
    ('role_platform_admin', 'platform_admin', 'Global platform infrastructure superuser', true),
    ('role_tenant_admin', 'tenant_admin', 'Tenant administrator with account and policy authority', true),
    ('role_sales_manager', 'sales_manager', 'Sales director with quotation approval and voice copilot authority', true),
    ('role_sales_rep', 'sales_rep', 'Internal sales executive managing leads, opportunities and quotes', false),
    ('role_support_agent', 'support_agent', 'Operations and customer support specialist', false),
    ('role_customer', 'customer', 'External commercial customer or prospect', false)
ON CONFLICT (name) DO NOTHING;

INSERT INTO permissions (id, code, description, domain) VALUES
    ('perm_tenants_manage', 'tenants:manage', 'Provision and configure tenant settings', 'IAM'),
    ('perm_users_manage', 'users:manage', 'Create, update and disable tenant users', 'IAM'),
    ('perm_roles_assign', 'roles:assign', 'Assign and revoke user roles', 'IAM'),
    ('perm_quotes_approve', 'quotes:approve', 'Approve quotations exceeding policy discount thresholds', 'COMMERCE'),
    ('perm_quotes_create', 'quotes:create', 'Create and send commercial quotations', 'COMMERCE'),
    ('perm_orders_read', 'orders:read', 'View customer order and shipment status', 'COMMERCE'),
    ('perm_voice_copilot', 'voice:copilot', 'Access privileged Manager Voice Copilot interface', 'VOICE'),
    ('perm_audit_read', 'audit:read', 'View compliance and security audit logs', 'SECURITY')
ON CONFLICT (code) DO NOTHING;
