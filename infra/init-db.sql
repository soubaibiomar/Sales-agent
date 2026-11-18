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
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    tier VARCHAR(50) NOT NULL DEFAULT 'standard',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Organization Sites / Facilities
CREATE TABLE IF NOT EXISTS organization_sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
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
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
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
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    is_privileged BOOLEAN NOT NULL DEFAULT false
);

-- Granular Permissions Catalog
CREATE TABLE IF NOT EXISTS permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    domain VARCHAR(50) NOT NULL
);

-- Role-Permission Mapping
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

-- User-Role Tenant Scoped Assignment
CREATE TABLE IF NOT EXISTS user_roles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id, tenant_id)
);

-- Session Revocation Blacklist (JTI tracking)
CREATE TABLE IF NOT EXISTS session_revocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_jti VARCHAR(255) UNIQUE NOT NULL,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    reason VARCHAR(255) NOT NULL DEFAULT 'logout'
);

-- Immutable Security & Operational Audit Log (Controls 42, ADR-010)
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    actor_id UUID,
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
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key VARCHAR(100) NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT false,
    rules JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_tenant_feature_key UNIQUE (tenant_id, key)
);

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

-- 5. Define RLS Isolation Policies
-- Rule: Access is permitted IF AND ONLY IF row.tenant_id matches the session variable app.current_tenant_id.
-- If the session variable is unset or empty, NULLIF returns NULL and comparison fails closed (0 rows).

CREATE POLICY tenant_isolation_sites ON organization_sites
    FOR ALL USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

CREATE POLICY tenant_isolation_users ON users
    FOR ALL USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

CREATE POLICY tenant_isolation_user_roles ON user_roles
    FOR ALL USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

CREATE POLICY tenant_isolation_session_revocations ON session_revocations
    FOR ALL USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

CREATE POLICY tenant_isolation_audit_logs ON audit_logs
    FOR ALL USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

CREATE POLICY tenant_isolation_feature_flags ON feature_flags
    FOR ALL USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);

-- 6. Grant least-privilege DML permissions to sales_app_user
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sales_app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sales_app_user;

-- Prevent sales_app_user from truncating or altering tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sales_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO sales_app_user;

-- 7. Seed System Roles & Initial Baseline Permissions
INSERT INTO roles (name, description, is_privileged) VALUES
    ('platform_admin', 'Global platform infrastructure superuser', true),
    ('tenant_admin', 'Tenant administrator with account and policy authority', true),
    ('sales_manager', 'Sales director with quotation approval and voice copilot authority', true),
    ('sales_rep', 'Internal sales executive managing leads, opportunities and quotes', false),
    ('support_agent', 'Operations and customer support specialist', false),
    ('customer', 'External commercial customer or prospect', false)
ON CONFLICT (name) DO NOTHING;

INSERT INTO permissions (code, description, domain) VALUES
    ('tenants:manage', 'Provision and configure tenant settings', 'IAM'),
    ('users:manage', 'Create, update and disable tenant users', 'IAM'),
    ('roles:assign', 'Assign and revoke user roles', 'IAM'),
    ('quotes:approve', 'Approve quotations exceeding policy discount thresholds', 'COMMERCE'),
    ('quotes:create', 'Create and send commercial quotations', 'COMMERCE'),
    ('orders:read', 'View customer order and shipment status', 'COMMERCE'),
    ('voice:copilot', 'Access privileged Manager Voice Copilot interface', 'VOICE'),
    ('audit:read', 'View compliance and security audit logs', 'SECURITY')
ON CONFLICT (code) DO NOTHING;
