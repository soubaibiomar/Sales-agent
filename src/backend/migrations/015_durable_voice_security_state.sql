-- =============================================================================
-- 015: Durable, tenant-isolated voice security state (inspection finding F-29)
-- =============================================================================
-- OTP challenges, manager action previews and telephony replay nonces were kept in
-- per-process Python dictionaries: lost on restart, and an OTP issued by one API
-- worker could not be verified by another. They now live in PostgreSQL under RLS.

BEGIN;

CREATE TABLE IF NOT EXISTS voice_otp_challenges (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_id VARCHAR(100) NOT NULL,
    code_hash VARCHAR(64) NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_voice_otp_tenant_session UNIQUE (tenant_id, session_id)
);
CREATE INDEX IF NOT EXISTS ix_voice_otp_challenges_tenant ON voice_otp_challenges (tenant_id);

CREATE TABLE IF NOT EXISTS manager_action_previews (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL,
    action_type VARCHAR(100) NOT NULL,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary TEXT,
    risk_level VARCHAR(20) NOT NULL DEFAULT 'HIGH',
    requires_step_up_mfa BOOLEAN NOT NULL DEFAULT true,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS ix_manager_action_previews_tenant ON manager_action_previews (tenant_id);

CREATE TABLE IF NOT EXISTS telephony_replay_nonces (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nonce VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_telephony_nonce_tenant UNIQUE (tenant_id, nonce)
);
CREATE INDEX IF NOT EXISTS ix_telephony_replay_nonces_tenant ON telephony_replay_nonces (tenant_id);

ALTER TABLE voice_otp_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_otp_challenges FORCE ROW LEVEL SECURITY;
ALTER TABLE manager_action_previews ENABLE ROW LEVEL SECURITY;
ALTER TABLE manager_action_previews FORCE ROW LEVEL SECURITY;
ALTER TABLE telephony_replay_nonces ENABLE ROW LEVEL SECURITY;
ALTER TABLE telephony_replay_nonces FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_voice_otp_challenges ON voice_otp_challenges;
CREATE POLICY tenant_isolation_voice_otp_challenges ON voice_otp_challenges AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
DROP POLICY IF EXISTS tenant_isolation_manager_action_previews ON manager_action_previews;
CREATE POLICY tenant_isolation_manager_action_previews ON manager_action_previews AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
DROP POLICY IF EXISTS tenant_isolation_telephony_replay_nonces ON telephony_replay_nonces;
CREATE POLICY tenant_isolation_telephony_replay_nonces ON telephony_replay_nonces AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

GRANT SELECT, INSERT, UPDATE, DELETE ON voice_otp_challenges, manager_action_previews, telephony_replay_nonces TO sales_app_user;

COMMIT;
