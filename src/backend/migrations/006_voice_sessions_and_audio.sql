-- Migration 006: Voice Sessions, Transcripts and Recordings
-- Step 07: Dual-Mode Customer Voice Agent and Manager Voice Copilot
-- (Baseline Controls 04-07, 28, 35, 39-40, 48-49, 55, 63-67, 70; SAI-01 to SAI-05, SAI-09 to SAI-12)

-- 1. Voice Sessions Table
CREATE TABLE IF NOT EXISTS voice_sessions (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_id VARCHAR(100) NOT NULL UNIQUE,
    channel_type VARCHAR(32) NOT NULL DEFAULT 'WEBRTC', -- WEBRTC, SIP_PSTN, WEB_VOICE
    voice_mode VARCHAR(32) NOT NULL DEFAULT 'CUSTOMER',  -- CUSTOMER, MANAGER
    caller_identifier VARCHAR(255),                      -- E.164 phone or client session ID
    customer_account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
    customer_contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    manager_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'INITIATED',     -- INITIATED, ACTIVE, PAUSED, TRANSFERRED, COMPLETED, FAILED
    language VARCHAR(16) NOT NULL DEFAULT 'fr-FR',       -- fr-FR, en-US, ar-MA, ary-Arab, ary-Latn
    is_caller_verified BOOLEAN NOT NULL DEFAULT FALSE,   -- Verified via OTP/PIN or authenticated session
    recording_consent_given BOOLEAN NOT NULL DEFAULT FALSE,
    disclosure_played BOOLEAN NOT NULL DEFAULT FALSE,
    turns_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMPTZ,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Voice Transcripts Table (Stores user and agent utterances with PII redaction)
CREATE TABLE IF NOT EXISTS voice_transcripts (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_id VARCHAR(100) NOT NULL REFERENCES voice_sessions(session_id) ON DELETE CASCADE,
    turn_index INTEGER NOT NULL DEFAULT 0,
    speaker_type VARCHAR(32) NOT NULL,                  -- USER, AGENT, SYSTEM
    raw_text TEXT NOT NULL,
    redacted_text TEXT NOT NULL,                        -- PII / PCI-DSS redacted
    language VARCHAR(16) NOT NULL DEFAULT 'fr-FR',
    latency_ms INTEGER DEFAULT 0,
    is_barge_in BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Voice Recordings Table (Tracks audio recordings stored in MinIO/S3 with 90-day retention)
CREATE TABLE IF NOT EXISTS voice_recordings (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_id VARCHAR(100) NOT NULL REFERENCES voice_sessions(session_id) ON DELETE CASCADE,
    storage_path VARCHAR(512) NOT NULL,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    file_size_bytes INTEGER NOT NULL DEFAULT 0,
    mime_type VARCHAR(64) NOT NULL DEFAULT 'audio/wav',
    encryption_algorithm VARCHAR(32) NOT NULL DEFAULT 'AES-256-GCM',
    expires_at TIMESTAMPTZ NOT NULL,                    -- 90-day retention expiration
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance & tenant filtering
CREATE INDEX IF NOT EXISTS idx_voice_sessions_tenant ON voice_sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_voice_sessions_session_id ON voice_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_voice_sessions_caller ON voice_sessions(caller_identifier);
CREATE INDEX IF NOT EXISTS idx_voice_transcripts_tenant ON voice_transcripts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_voice_transcripts_session ON voice_transcripts(session_id);
CREATE INDEX IF NOT EXISTS idx_voice_recordings_tenant ON voice_recordings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_voice_recordings_session ON voice_recordings(session_id);
CREATE INDEX IF NOT EXISTS idx_voice_recordings_expires ON voice_recordings(expires_at);

-- Row-Level Security: ENABLE & FORCE on all 3 tables
ALTER TABLE voice_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_sessions FORCE ROW LEVEL SECURITY;

ALTER TABLE voice_transcripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_transcripts FORCE ROW LEVEL SECURITY;

ALTER TABLE voice_recordings ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_recordings FORCE ROW LEVEL SECURITY;

-- Tenant Isolation Policies
DROP POLICY IF EXISTS tenant_isolation_voice_sessions ON voice_sessions;
CREATE POLICY tenant_isolation_voice_sessions ON voice_sessions
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

DROP POLICY IF EXISTS tenant_isolation_voice_transcripts ON voice_transcripts;
CREATE POLICY tenant_isolation_voice_transcripts ON voice_transcripts
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

DROP POLICY IF EXISTS tenant_isolation_voice_recordings ON voice_recordings;
CREATE POLICY tenant_isolation_voice_recordings ON voice_recordings
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

-- Grant table privileges to application user
GRANT SELECT, INSERT, UPDATE, DELETE ON voice_sessions TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON voice_transcripts TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON voice_recordings TO sales_app_user;
