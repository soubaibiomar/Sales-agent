-- Migration: 002_omnichannel_schema.sql
-- Step 03: Omnichannel conversation gateway, durable ingestion, contact identity, and unified inbox

-- 1. Contacts Table (Tenant Scoped)
CREATE TABLE IF NOT EXISTS contacts (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    display_name VARCHAR(200) NOT NULL,
    primary_email VARCHAR(255),
    primary_phone VARCHAR(50),
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Channel Identities Table (Maps channels to contacts, tracks consent and STOP)
CREATE TABLE IF NOT EXISTS channel_identities (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    contact_id VARCHAR(36) NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    channel_type VARCHAR(30) NOT NULL, -- WEB_CHAT, WHATSAPP, EMAIL, VOICE_SIP
    identifier VARCHAR(255) NOT NULL,  -- Phone number, email address, or web session UUID
    is_opted_out BOOLEAN NOT NULL DEFAULT FALSE,
    opt_out_at TIMESTAMP WITH TIME ZONE,
    opt_out_reason VARCHAR(255),
    consent_given_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_channel_identifier UNIQUE (tenant_id, channel_type, identifier)
);

-- 3. Conversations Table (Tenant Scoped, state machine, monotonic version)
CREATE TABLE IF NOT EXISTS conversations (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    contact_id VARCHAR(36) NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    channel_type VARCHAR(30) NOT NULL,
    channel_identifier VARCHAR(255) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'BOT_ACTIVE', -- BOT_ACTIVE, HUMAN_PENDING, HUMAN_ACTIVE, CLOSED
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 1,
    is_ai_silenced BOOLEAN NOT NULL DEFAULT FALSE,
    unread_count INTEGER NOT NULL DEFAULT 0,
    last_message_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 4. Inbound Raw Events (Durable Ingest buffer before debounce/routing, replay protection)
CREATE TABLE IF NOT EXISTS inbound_raw_events (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    channel_type VARCHAR(30) NOT NULL,
    provider_event_id VARCHAR(255) NOT NULL,
    payload_json TEXT NOT NULL,
    signature_verified BOOLEAN NOT NULL DEFAULT TRUE,
    processing_status VARCHAR(30) NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSED, FAILED, DUPLICATE
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_tenant_channel_provider_event UNIQUE (tenant_id, channel_type, provider_event_id)
);

-- 5. Conversation Messages (Normalized conversation timeline)
CREATE TABLE IF NOT EXISTS conversation_messages (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    sender_type VARCHAR(20) NOT NULL, -- CUSTOMER, AGENT, AI_BOT, SYSTEM
    sender_id VARCHAR(36),            -- user_id if AGENT, bot_name if AI_BOT
    content TEXT NOT NULL,
    content_redacted TEXT,
    event_type VARCHAR(30) NOT NULL DEFAULT 'MESSAGE', -- MESSAGE, STATUS_CHANGE, HANDOFF, CONSENT_STOP, ATTACHMENT
    conversation_version INTEGER NOT NULL DEFAULT 1,
    attachments_json TEXT DEFAULT '[]',
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 6. Message Attachments (Validated media, anti-SSRF & MIME protection)
CREATE TABLE IF NOT EXISTS message_attachments (
    id VARCHAR(36) PRIMARY KEY,
    message_id VARCHAR(36) NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    file_name VARCHAR(255) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    is_safe BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 7. Transactional Outbox Events (Reliable dispatch, retry/backoff, DLQ, safety priority)
CREATE TABLE IF NOT EXISTS outbox_events (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id VARCHAR(36) REFERENCES conversations(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL, -- DISPATCH_MESSAGE, NOTIFICATION, SAFETY_ALERT
    channel_type VARCHAR(30) NOT NULL, -- WHATSAPP, EMAIL, WEB_CHAT, VOICE_SIP
    message_class VARCHAR(30) NOT NULL DEFAULT 'TRANSACTIONAL', -- MARKETING, TRANSACTIONAL, SERVICE, SECURITY
    recipient_identifier VARCHAR(255) NOT NULL,
    payload_json TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING', -- PENDING, PROCESSING, DELIVERED, FAILED, DEAD_LETTER
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    next_retry_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_error TEXT,
    is_high_priority BOOLEAN NOT NULL DEFAULT FALSE,
    claimed_by VARCHAR(100),
    claim_token VARCHAR(100),
    claim_expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT chk_outbox_message_class CHECK (message_class IN ('MARKETING', 'TRANSACTIONAL', 'SERVICE', 'SECURITY'))
);

-- 8. Tenant Channel Integrations Table (Provider Asset binding & verification)
CREATE TABLE IF NOT EXISTS tenant_channel_integrations (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    channel_type VARCHAR(30) NOT NULL,
    provider_account_id VARCHAR(255),
    provider_asset_id VARCHAR(255) NOT NULL,
    webhook_secret VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    config_json TEXT DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_channel_provider_asset UNIQUE (channel_type, provider_asset_id)
);

-- 9. Indexes for Query Performance & Tenant Filtering
CREATE INDEX IF NOT EXISTS idx_contacts_tenant ON contacts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_channel_identities_tenant ON channel_identities(tenant_id, channel_type, identifier);
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_status ON conversations(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_contact ON conversations(tenant_id, contact_id);
CREATE INDEX IF NOT EXISTS idx_raw_events_tenant_status ON inbound_raw_events(tenant_id, processing_status);
CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON conversation_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_attachments_msg ON message_attachments(message_id);
CREATE INDEX IF NOT EXISTS idx_outbox_tenant_status ON outbox_events(tenant_id, status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_outbox_claim ON outbox_events(status, claim_expires_at, message_class);
CREATE INDEX IF NOT EXISTS idx_channel_integrations_tenant ON tenant_channel_integrations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_channel_integrations_asset ON tenant_channel_integrations(channel_type, provider_asset_id);
