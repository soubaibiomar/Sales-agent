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

-- Accounts Table (B2B/B2C Organization or Client Account)
CREATE TABLE IF NOT EXISTS accounts (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    account_type VARCHAR(50) NOT NULL DEFAULT 'CUSTOMER',
    tax_identifier VARCHAR(100),
    industry VARCHAR(100),
    website VARCHAR(255),
    phone VARCHAR(50),
    billing_address TEXT,
    shipping_address TEXT,
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_tenant_account_name UNIQUE (tenant_id, name)
);

-- Contacts Table
CREATE TABLE IF NOT EXISTS contacts (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
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
    message_class VARCHAR(30) NOT NULL DEFAULT 'TRANSACTIONAL',
    recipient_identifier VARCHAR(255) NOT NULL,
    payload_json TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_error TEXT,
    is_high_priority BOOLEAN NOT NULL DEFAULT false,
    claimed_by VARCHAR(100),
    claim_token VARCHAR(100),
    claim_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    processed_at TIMESTAMPTZ,
    CONSTRAINT chk_outbox_message_class CHECK (message_class IN ('MARKETING', 'TRANSACTIONAL', 'SERVICE', 'SECURITY'))
);

-- Tenant Channel Integrations Table (Provider Asset binding & verification)
CREATE TABLE IF NOT EXISTS tenant_channel_integrations (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    channel_type VARCHAR(30) NOT NULL,
    provider_account_id VARCHAR(255),
    provider_asset_id VARCHAR(255) NOT NULL,
    webhook_secret VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT true,
    config_json TEXT DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_channel_provider_asset UNIQUE (channel_type, provider_asset_id)
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
CREATE INDEX IF NOT EXISTS idx_outbox_claim ON outbox_events(status, claim_expires_at, message_class);
CREATE INDEX IF NOT EXISTS idx_channel_integrations_tenant ON tenant_channel_integrations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_channel_integrations_asset ON tenant_channel_integrations(channel_type, provider_asset_id);

-- =============================================================================
-- STEP 04 CRM, CATALOG, PRICING, QUOTATIONS & APPROVALS SCHEMA
-- =============================================================================

-- Leads Table
CREATE TABLE IF NOT EXISTS leads (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    company_name VARCHAR(200),
    email VARCHAR(255),
    phone VARCHAR(50),
    status VARCHAR(50) NOT NULL DEFAULT 'NEW',
    source VARCHAR(50) NOT NULL DEFAULT 'MANUAL',
    score INT NOT NULL DEFAULT 0,
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    converted_account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
    converted_contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    converted_opportunity_id VARCHAR(36),
    notes TEXT,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Opportunities Table
CREATE TABLE IF NOT EXISTS opportunities (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE CASCADE,
    contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    lead_id VARCHAR(36) REFERENCES leads(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    stage VARCHAR(50) NOT NULL DEFAULT 'DISCOVERY',
    amount_cents BIGINT NOT NULL DEFAULT 0,
    currency VARCHAR(10) NOT NULL DEFAULT 'MAD',
    probability_percent INT NOT NULL DEFAULT 20,
    expected_close_date TIMESTAMPTZ,
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    lost_reason VARCHAR(255),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Add foreign key constraint on leads for converted_opportunity_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'fk_lead_converted_opportunity'
    ) THEN
        ALTER TABLE leads ADD CONSTRAINT fk_lead_converted_opportunity 
        FOREIGN KEY (converted_opportunity_id) REFERENCES opportunities(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Activities Table (CRM Tasks, Calls, Notes, Meetings)
CREATE TABLE IF NOT EXISTS activities (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL,
    subject VARCHAR(255) NOT NULL,
    description TEXT,
    due_date TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    lead_id VARCHAR(36) REFERENCES leads(id) ON DELETE CASCADE,
    opportunity_id VARCHAR(36) REFERENCES opportunities(id) ON DELETE CASCADE,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE CASCADE,
    contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Products Table (Catalog Products & Services)
CREATE TABLE IF NOT EXISTS products (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    sku VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    product_type VARCHAR(50) NOT NULL DEFAULT 'PHYSICAL',
    uom VARCHAR(50) NOT NULL DEFAULT 'UNIT',
    category VARCHAR(100),
    base_price_cents BIGINT NOT NULL DEFAULT 0,
    cost_cents BIGINT NOT NULL DEFAULT 0,
    currency VARCHAR(10) NOT NULL DEFAULT 'MAD',
    tax_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 20.00,
    min_margin_percent NUMERIC(5,2) NOT NULL DEFAULT 15.00,
    is_active BOOLEAN NOT NULL DEFAULT true,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_tenant_product_sku UNIQUE (tenant_id, sku)
);

-- Product SKU Variants Table
CREATE TABLE IF NOT EXISTS product_variants (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    product_id VARCHAR(36) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    sku_variant VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    price_adjustment_cents BIGINT NOT NULL DEFAULT 0,
    cost_adjustment_cents BIGINT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_tenant_variant_sku UNIQUE (tenant_id, sku_variant)
);

-- Price Lists Table
CREATE TABLE IF NOT EXISTS price_lists (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'MAD',
    description TEXT,
    is_default BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT true,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_tenant_pricelist_code UNIQUE (tenant_id, code)
);

-- Price List Items Table
CREATE TABLE IF NOT EXISTS price_list_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    price_list_id VARCHAR(36) NOT NULL REFERENCES price_lists(id) ON DELETE CASCADE,
    product_id VARCHAR(36) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    variant_id VARCHAR(36) REFERENCES product_variants(id) ON DELETE CASCADE,
    unit_price_cents BIGINT NOT NULL,
    min_quantity INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Quotes Table (Commercial Quotations & State Machine)
CREATE TABLE IF NOT EXISTS quotes (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    quote_number VARCHAR(100) NOT NULL,
    opportunity_id VARCHAR(36) REFERENCES opportunities(id) ON DELETE SET NULL,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
    contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    price_list_id VARCHAR(36) REFERENCES price_lists(id) ON DELETE SET NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'MAD',
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
    version INT NOT NULL DEFAULT 1,
    subtotal_cents BIGINT NOT NULL DEFAULT 0,
    discount_total_cents BIGINT NOT NULL DEFAULT 0,
    tax_total_cents BIGINT NOT NULL DEFAULT 0,
    grand_total_cents BIGINT NOT NULL DEFAULT 0,
    margin_percent NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    requires_approval BOOLEAN NOT NULL DEFAULT false,
    approval_reason VARCHAR(255),
    terms_hash VARCHAR(64) NOT NULL,
    valid_until TIMESTAMPTZ NOT NULL,
    payment_terms VARCHAR(100) DEFAULT 'NET_30',
    notes TEXT,
    issued_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ,
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_tenant_quote_number UNIQUE (tenant_id, quote_number)
);

-- Quote Items Table (Line Items Snapshot)
CREATE TABLE IF NOT EXISTS quote_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    quote_id VARCHAR(36) NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    product_id VARCHAR(36) REFERENCES products(id) ON DELETE SET NULL,
    variant_id VARCHAR(36) REFERENCES product_variants(id) ON DELETE SET NULL,
    sku_snapshot VARCHAR(100) NOT NULL,
    name_snapshot VARCHAR(255) NOT NULL,
    quantity INT NOT NULL,
    uom_snapshot VARCHAR(50) NOT NULL,
    unit_price_cents BIGINT NOT NULL,
    unit_cost_cents BIGINT NOT NULL DEFAULT 0,
    discount_percent NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    discount_cents BIGINT NOT NULL DEFAULT 0,
    tax_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 20.00,
    subtotal_cents BIGINT NOT NULL,
    tax_cents BIGINT NOT NULL,
    total_cents BIGINT NOT NULL,
    margin_percent NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT chk_quote_item_quantity_positive CHECK (quantity > 0)
);

-- Quote Approvals Table (Canonical Approval Queue with Exact Terms Hash)
CREATE TABLE IF NOT EXISTS quote_approvals (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    quote_id VARCHAR(36) NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    quote_version INT NOT NULL,
    terms_hash VARCHAR(64) NOT NULL,
    requested_by_user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    decided_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ,
    decision_reason VARCHAR(255),
    mfa_verified BOOLEAN NOT NULL DEFAULT false,
    decision_signature VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Quote Documents Table (Hash-addressed generated pro-forma/quote documents)
CREATE TABLE IF NOT EXISTS quote_documents (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    quote_id VARCHAR(36) NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    quote_version INT NOT NULL,
    document_type VARCHAR(50) NOT NULL DEFAULT 'PRO_FORMA',
    document_hash VARCHAR(64) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    content_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- ============================================================================
-- STEP 05 TABLES: Orders, Payments, Invoicing and Stock Reservations
-- ============================================================================

-- 1. Warehouses Table
CREATE TABLE IF NOT EXISTS warehouses (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(255) NOT NULL,
    address_json TEXT NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_warehouse_code UNIQUE (tenant_id, code)
);

-- 2. Inventory Items Table (Warehouse-Aware Available-To-Promise)
CREATE TABLE IF NOT EXISTS inventory_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    warehouse_id VARCHAR(36) NOT NULL REFERENCES warehouses(id) ON DELETE CASCADE,
    product_id VARCHAR(36) REFERENCES products(id) ON DELETE SET NULL,
    variant_id VARCHAR(36) REFERENCES product_variants(id) ON DELETE SET NULL,
    sku VARCHAR(100) NOT NULL,
    on_hand_quantity INTEGER NOT NULL DEFAULT 0,
    reserved_quantity INTEGER NOT NULL DEFAULT 0,
    allocated_quantity INTEGER NOT NULL DEFAULT 0,
    backorder_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_warehouse_sku UNIQUE (tenant_id, warehouse_id, sku)
);

-- 3. Stock Reservations Table (Atomic Holds & Expiry)
CREATE TABLE IF NOT EXISTS stock_reservations (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    inventory_item_id VARCHAR(36) NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
    order_id VARCHAR(36),
    quote_id VARCHAR(36) REFERENCES quotes(id) ON DELETE SET NULL,
    sku VARCHAR(100) NOT NULL,
    quantity INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, COMMITTED, RELEASED, EXPIRED
    reserved_until TIMESTAMP WITH TIME ZONE NOT NULL,
    idempotency_key VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 4. Stock Movements Table (Append-Only Inventory Ledger)
CREATE TABLE IF NOT EXISTS stock_movements (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    inventory_item_id VARCHAR(36) NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
    movement_type VARCHAR(50) NOT NULL, -- INBOUND_RECEIPT, SALE_DEDUCTION, ADJUSTMENT, RETURN_RESTOCK, TRANSFER
    quantity_delta INTEGER NOT NULL,
    previous_on_hand INTEGER NOT NULL,
    new_on_hand INTEGER NOT NULL,
    reference_type VARCHAR(50) NOT NULL, -- ORDER, SHIPMENT, ADJUSTMENT, RETURN
    reference_id VARCHAR(255) NOT NULL,
    notes TEXT,
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 5. Sales Orders Table
CREATE TABLE IF NOT EXISTS sales_orders (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    order_number VARCHAR(100) NOT NULL,
    quote_id VARCHAR(36) REFERENCES quotes(id) ON DELETE SET NULL,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
    contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT', -- DRAFT, PENDING_PAYMENT, PAYMENT_AUTHORIZED, PAID, PROCESSING, PARTIALLY_FULFILLED, FULFILLED, CANCELLED, REFUNDED
    version INTEGER NOT NULL DEFAULT 1,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    subtotal_cents BIGINT NOT NULL DEFAULT 0,
    discount_total_cents BIGINT NOT NULL DEFAULT 0,
    tax_total_cents BIGINT NOT NULL DEFAULT 0,
    grand_total_cents BIGINT NOT NULL DEFAULT 0,
    terms_hash VARCHAR(64) NOT NULL,
    payment_status VARCHAR(50) NOT NULL DEFAULT 'UNPAID', -- UNPAID, PARTIALLY_PAID, PAID, REFUNDED
    fulfillment_status VARCHAR(50) NOT NULL DEFAULT 'UNFULFILLED', -- UNFULFILLED, PARTIALLY_FULFILLED, FULFILLED
    shipping_address_json TEXT NOT NULL DEFAULT '{}',
    billing_address_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key VARCHAR(255),
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_order_number UNIQUE (tenant_id, order_number)
);

-- 6. Order Items Table
CREATE TABLE IF NOT EXISTS order_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    product_id VARCHAR(36) REFERENCES products(id) ON DELETE SET NULL,
    variant_id VARCHAR(36) REFERENCES product_variants(id) ON DELETE SET NULL,
    sku VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    quantity INTEGER NOT NULL,
    uom VARCHAR(50) NOT NULL DEFAULT 'UNIT',
    unit_price_cents BIGINT NOT NULL,
    unit_cost_cents BIGINT NOT NULL DEFAULT 0,
    discount_percent NUMERIC(5, 2) NOT NULL DEFAULT 0.00,
    discount_cents BIGINT NOT NULL DEFAULT 0,
    tax_rate_percent NUMERIC(5, 2) NOT NULL DEFAULT 20.00,
    tax_cents BIGINT NOT NULL DEFAULT 0,
    subtotal_cents BIGINT NOT NULL,
    total_cents BIGINT NOT NULL,
    fulfillment_status VARCHAR(50) NOT NULL DEFAULT 'UNFULFILLED',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 7. Payment Intents Table
CREATE TABLE IF NOT EXISTS payment_intents (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL DEFAULT 'STRIPE_SANDBOX', -- STRIPE_SANDBOX, CMI_SANDBOX, BANK_TRANSFER
    provider_intent_id VARCHAR(255) NOT NULL,
    client_secret VARCHAR(255),
    amount_cents BIGINT NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    status VARCHAR(50) NOT NULL DEFAULT 'REQUIRES_PAYMENT_METHOD', -- REQUIRES_PAYMENT_METHOD, REQUIRES_CONFIRMATION, PROCESSING, SUCCEEDED, REQUIRES_CAPTURE, CANCELLED, FAILED
    idempotency_key VARCHAR(255),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_provider_intent UNIQUE (tenant_id, provider, provider_intent_id)
);

-- 8. Payment Transactions Table
CREATE TABLE IF NOT EXISTS payment_transactions (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    payment_intent_id VARCHAR(36) NOT NULL REFERENCES payment_intents(id) ON DELETE CASCADE,
    order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    transaction_type VARCHAR(50) NOT NULL DEFAULT 'CAPTURE', -- AUTHORIZATION, CAPTURE, REFUND, VOID
    amount_cents BIGINT NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    provider_transaction_id VARCHAR(255) NOT NULL,
    payment_method_type VARCHAR(50) NOT NULL DEFAULT 'CARD',
    status VARCHAR(50) NOT NULL DEFAULT 'SUCCESS',
    receipt_url VARCHAR(500),
    raw_response_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 9. Refund Requests Table
CREATE TABLE IF NOT EXISTS refund_requests (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    payment_intent_id VARCHAR(36) REFERENCES payment_intents(id) ON DELETE SET NULL,
    amount_cents BIGINT NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    reason VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'REQUESTED', -- REQUESTED, APPROVED, PROCESSING, COMPLETED, REJECTED
    requested_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    approved_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    provider_refund_id VARCHAR(255),
    idempotency_key VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 10. Invoices Table
CREATE TABLE IF NOT EXISTS invoices (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    invoice_number VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'ISSUED', -- DRAFT, ISSUED, PAID, CANCELLED, REFUNDED
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    subtotal_cents BIGINT NOT NULL,
    discount_total_cents BIGINT NOT NULL DEFAULT 0,
    tax_total_cents BIGINT NOT NULL,
    grand_total_cents BIGINT NOT NULL,
    terms_hash VARCHAR(64) NOT NULL,
    invoice_hash VARCHAR(64) NOT NULL,
    correction_of_invoice_id VARCHAR(36) REFERENCES invoices(id) ON DELETE SET NULL,
    issued_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    due_date TIMESTAMP WITH TIME ZONE NOT NULL,
    paid_at TIMESTAMP WITH TIME ZONE,
    pdf_storage_path VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_invoice_number UNIQUE (tenant_id, invoice_number)
);

-- 11. Invoice Items Table
CREATE TABLE IF NOT EXISTS invoice_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    invoice_id VARCHAR(36) NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    sku VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_cents BIGINT NOT NULL,
    discount_cents BIGINT NOT NULL DEFAULT 0,
    tax_rate_percent NUMERIC(5, 2) NOT NULL DEFAULT 20.00,
    tax_cents BIGINT NOT NULL,
    subtotal_cents BIGINT NOT NULL,
    total_cents BIGINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- STEP 06: Procurement, Multi-Warehouse Operations, Logistics, Support & Scheduling
-- =============================================================================

-- 12. Suppliers Registry
CREATE TABLE IF NOT EXISTS suppliers (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    supplier_code VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    contact_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    payment_terms VARCHAR(100) DEFAULT 'NET_30',
    currency VARCHAR(10) DEFAULT 'MAD',
    address_json JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_suppliers_tenant_code UNIQUE (tenant_id, supplier_code)
);

-- 13. Supplier Product Catalog & Pricing
CREATE TABLE IF NOT EXISTS supplier_products (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    supplier_id VARCHAR(36) NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    product_id VARCHAR(36) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    sku VARCHAR(100) NOT NULL,
    supplier_sku VARCHAR(100),
    unit_cost_cents BIGINT NOT NULL,
    currency VARCHAR(10) DEFAULT 'MAD' NOT NULL,
    lead_time_days INTEGER DEFAULT 7 NOT NULL,
    min_order_quantity INTEGER DEFAULT 1 NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_supplier_products_sku UNIQUE (tenant_id, supplier_id, sku)
);

-- 14. Request For Quotation (RFQ)
CREATE TABLE IF NOT EXISTS rfqs (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    rfq_number VARCHAR(64) NOT NULL,
    supplier_id VARCHAR(36) NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    status VARCHAR(30) DEFAULT 'DRAFT' NOT NULL,
    deadline_date TIMESTAMPTZ,
    notes TEXT,
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_rfqs_tenant_number UNIQUE (tenant_id, rfq_number)
);

-- 15. RFQ Line Items
CREATE TABLE IF NOT EXISTS rfq_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    rfq_id VARCHAR(36) NOT NULL REFERENCES rfqs(id) ON DELETE CASCADE,
    product_id VARCHAR(36) REFERENCES products(id) ON DELETE SET NULL,
    sku VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    quantity INTEGER NOT NULL,
    target_unit_cost_cents BIGINT,
    quoted_unit_cost_cents BIGINT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 16. Purchase Orders (PO)
CREATE TABLE IF NOT EXISTS purchase_orders (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    po_number VARCHAR(64) NOT NULL,
    supplier_id VARCHAR(36) NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    warehouse_id VARCHAR(36) NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    rfq_id VARCHAR(36) REFERENCES rfqs(id) ON DELETE SET NULL,
    status VARCHAR(30) DEFAULT 'DRAFT' NOT NULL,
    version INTEGER DEFAULT 1 NOT NULL,
    currency VARCHAR(10) DEFAULT 'MAD' NOT NULL,
    subtotal_cents BIGINT DEFAULT 0 NOT NULL,
    tax_cents BIGINT DEFAULT 0 NOT NULL,
    grand_total_cents BIGINT DEFAULT 0 NOT NULL,
    payment_terms VARCHAR(100) DEFAULT 'NET_30',
    notes TEXT,
    approved_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ,
    issued_at TIMESTAMPTZ,
    expected_delivery_date TIMESTAMPTZ,
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_purchase_orders_tenant_number UNIQUE (tenant_id, po_number)
);

-- 17. Purchase Order Items
CREATE TABLE IF NOT EXISTS purchase_order_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    purchase_order_id VARCHAR(36) NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    product_id VARCHAR(36) REFERENCES products(id) ON DELETE SET NULL,
    sku VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    quantity_ordered INTEGER NOT NULL,
    quantity_received INTEGER DEFAULT 0 NOT NULL,
    unit_cost_cents BIGINT NOT NULL,
    subtotal_cents BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_po_qty_positive CHECK (quantity_ordered > 0),
    CONSTRAINT chk_po_qty_received_non_negative CHECK (quantity_received >= 0)
);

-- 18. Goods Receipts (GRN)
CREATE TABLE IF NOT EXISTS goods_receipts (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    receipt_number VARCHAR(64) NOT NULL,
    purchase_order_id VARCHAR(36) NOT NULL REFERENCES purchase_orders(id) ON DELETE RESTRICT,
    warehouse_id VARCHAR(36) NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    received_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    carrier_name VARCHAR(100),
    tracking_reference VARCHAR(100),
    notes TEXT,
    received_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_goods_receipts_tenant_number UNIQUE (tenant_id, receipt_number)
);

-- 19. Goods Receipt Line Items
CREATE TABLE IF NOT EXISTS goods_receipt_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    goods_receipt_id VARCHAR(36) NOT NULL REFERENCES goods_receipts(id) ON DELETE CASCADE,
    po_item_id VARCHAR(36) NOT NULL REFERENCES purchase_order_items(id) ON DELETE RESTRICT,
    sku VARCHAR(100) NOT NULL,
    quantity_received INTEGER NOT NULL,
    quantity_rejected INTEGER DEFAULT 0 NOT NULL,
    rejection_reason VARCHAR(255),
    lot_number VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_gr_qty_received CHECK (quantity_received >= 0),
    CONSTRAINT chk_gr_qty_rejected CHECK (quantity_rejected >= 0)
);

-- 20. Inter-Warehouse Stock Transfers
CREATE TABLE IF NOT EXISTS stock_transfers (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    transfer_number VARCHAR(64) NOT NULL,
    source_warehouse_id VARCHAR(36) NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    destination_warehouse_id VARCHAR(36) NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    status VARCHAR(30) DEFAULT 'DRAFT' NOT NULL,
    notes TEXT,
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    shipped_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_stock_transfers_tenant_number UNIQUE (tenant_id, transfer_number),
    CONSTRAINT chk_transfer_diff_warehouses CHECK (source_warehouse_id <> destination_warehouse_id)
);

-- 21. Stock Transfer Items
CREATE TABLE IF NOT EXISTS stock_transfer_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    transfer_id VARCHAR(36) NOT NULL REFERENCES stock_transfers(id) ON DELETE CASCADE,
    sku VARCHAR(100) NOT NULL,
    quantity_requested INTEGER NOT NULL,
    quantity_shipped INTEGER DEFAULT 0 NOT NULL,
    quantity_received INTEGER DEFAULT 0 NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_transfer_req_pos CHECK (quantity_requested > 0),
    CONSTRAINT chk_transfer_ship_non_neg CHECK (quantity_shipped >= 0),
    CONSTRAINT chk_transfer_rec_non_neg CHECK (quantity_received >= 0)
);

-- 22. Shipments (Fulfillment & Logistics)
CREATE TABLE IF NOT EXISTS shipments (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    shipment_number VARCHAR(64) NOT NULL,
    order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id) ON DELETE RESTRICT,
    warehouse_id VARCHAR(36) NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    carrier_code VARCHAR(50) NOT NULL,
    carrier_service VARCHAR(100),
    tracking_number VARCHAR(100),
    status VARCHAR(30) DEFAULT 'CREATED' NOT NULL,
    shipping_address_json JSONB DEFAULT '{}'::jsonb NOT NULL,
    delivery_contact_json JSONB DEFAULT '{}'::jsonb NOT NULL,
    shipping_label_url VARCHAR(500),
    estimated_delivery_at TIMESTAMPTZ,
    shipped_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    failure_reason TEXT,
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_shipments_tenant_number UNIQUE (tenant_id, shipment_number)
);

-- 23. Shipment Items
CREATE TABLE IF NOT EXISTS shipment_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    shipment_id VARCHAR(36) NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    order_item_id VARCHAR(36) NOT NULL REFERENCES order_items(id) ON DELETE RESTRICT,
    sku VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    quantity INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_shipment_qty_pos CHECK (quantity > 0)
);

-- 24. Shipment Tracking Events (Normalized Event Timeline)
CREATE TABLE IF NOT EXISTS shipment_tracking_events (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    shipment_id VARCHAR(36) NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL,
    location VARCHAR(255),
    description TEXT,
    raw_payload_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 25. Delivery Proofs
CREATE TABLE IF NOT EXISTS delivery_proofs (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    shipment_id VARCHAR(36) NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    recipient_name VARCHAR(255) NOT NULL,
    signature_image_url VARCHAR(500),
    photo_url VARCHAR(500),
    signed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    location_coordinates VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_delivery_proof_shipment UNIQUE (tenant_id, shipment_id)
);

-- 26. Customer Support Tickets
CREATE TABLE IF NOT EXISTS support_tickets (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    ticket_number VARCHAR(64) NOT NULL,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
    contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    order_id VARCHAR(36) REFERENCES sales_orders(id) ON DELETE SET NULL,
    priority VARCHAR(20) DEFAULT 'MEDIUM' NOT NULL,
    category VARCHAR(50) DEFAULT 'GENERAL' NOT NULL,
    status VARCHAR(30) DEFAULT 'OPEN' NOT NULL,
    subject VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_support_tickets_tenant_number UNIQUE (tenant_id, ticket_number)
);

-- 27. Support Ticket Messages
CREATE TABLE IF NOT EXISTS ticket_messages (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    ticket_id VARCHAR(36) NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
    sender_type VARCHAR(20) NOT NULL,
    sender_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    message_text TEXT NOT NULL,
    attachments_json JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 28. Warranty Claims
CREATE TABLE IF NOT EXISTS warranty_claims (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    claim_number VARCHAR(64) NOT NULL,
    order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id) ON DELETE RESTRICT,
    order_item_id VARCHAR(36) NOT NULL REFERENCES order_items(id) ON DELETE RESTRICT,
    ticket_id VARCHAR(36) REFERENCES support_tickets(id) ON DELETE SET NULL,
    sku VARCHAR(100) NOT NULL,
    serial_number VARCHAR(100),
    status VARCHAR(30) DEFAULT 'SUBMITTED' NOT NULL,
    warranty_valid_until TIMESTAMPTZ NOT NULL,
    claim_reason TEXT NOT NULL,
    inspection_notes TEXT,
    resolved_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_warranty_claims_tenant_number UNIQUE (tenant_id, claim_number)
);

-- 29. Return Authorizations (RMA)
CREATE TABLE IF NOT EXISTS return_authorizations (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    rma_number VARCHAR(64) NOT NULL,
    order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id) ON DELETE RESTRICT,
    ticket_id VARCHAR(36) REFERENCES support_tickets(id) ON DELETE SET NULL,
    status VARCHAR(30) DEFAULT 'REQUESTED' NOT NULL,
    reason TEXT NOT NULL,
    requested_action VARCHAR(30) DEFAULT 'REFUND' NOT NULL,
    inspection_outcome VARCHAR(30),
    inspection_notes TEXT,
    refund_amount_cents BIGINT DEFAULT 0 NOT NULL,
    destination_warehouse_id VARCHAR(36) REFERENCES warehouses(id) ON DELETE RESTRICT,
    authorized_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    inspected_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    authorized_at TIMESTAMPTZ,
    inspected_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_rma_tenant_number UNIQUE (tenant_id, rma_number)
);

-- 30. Return Authorization Items
CREATE TABLE IF NOT EXISTS return_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    rma_id VARCHAR(36) NOT NULL REFERENCES return_authorizations(id) ON DELETE CASCADE,
    order_item_id VARCHAR(36) NOT NULL REFERENCES order_items(id) ON DELETE RESTRICT,
    sku VARCHAR(100) NOT NULL,
    quantity_requested INTEGER NOT NULL,
    quantity_received INTEGER DEFAULT 0 NOT NULL,
    condition VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_return_qty_requested CHECK (quantity_requested > 0),
    CONSTRAINT chk_return_qty_received CHECK (quantity_received >= 0)
);

-- 31. Appointments & Bookings
CREATE TABLE IF NOT EXISTS appointments (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    booking_number VARCHAR(64) NOT NULL,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
    contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    order_id VARCHAR(36) REFERENCES sales_orders(id) ON DELETE SET NULL,
    service_type VARCHAR(50) NOT NULL,
    status VARCHAR(30) DEFAULT 'REQUESTED' NOT NULL,
    staff_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    location_type VARCHAR(30) DEFAULT 'VIDEO_CALL' NOT NULL,
    location_details VARCHAR(255),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_appointments_tenant_number UNIQUE (tenant_id, booking_number),
    CONSTRAINT chk_appointment_times CHECK (end_time > start_time)
);

-- 32. Voice Sessions Table
CREATE TABLE IF NOT EXISTS voice_sessions (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_id VARCHAR(100) NOT NULL UNIQUE,
    channel_type VARCHAR(32) NOT NULL DEFAULT 'WEBRTC',
    voice_mode VARCHAR(32) NOT NULL DEFAULT 'CUSTOMER',
    caller_identifier VARCHAR(255),
    customer_account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
    customer_contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    manager_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'INITIATED',
    language VARCHAR(16) NOT NULL DEFAULT 'fr-FR',
    is_caller_verified BOOLEAN NOT NULL DEFAULT FALSE,
    recording_consent_given BOOLEAN NOT NULL DEFAULT FALSE,
    disclosure_played BOOLEAN NOT NULL DEFAULT FALSE,
    turns_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMPTZ,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 33. Voice Transcripts Table
CREATE TABLE IF NOT EXISTS voice_transcripts (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_id VARCHAR(100) NOT NULL REFERENCES voice_sessions(session_id) ON DELETE CASCADE,
    turn_index INTEGER NOT NULL DEFAULT 0,
    speaker_type VARCHAR(32) NOT NULL,
    raw_text TEXT NOT NULL,
    redacted_text TEXT NOT NULL,
    language VARCHAR(16) NOT NULL DEFAULT 'fr-FR',
    latency_ms INTEGER DEFAULT 0,
    is_barge_in BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 34. Voice Recordings Table
CREATE TABLE IF NOT EXISTS voice_recordings (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_id VARCHAR(100) NOT NULL REFERENCES voice_sessions(session_id) ON DELETE CASCADE,
    storage_path VARCHAR(512) NOT NULL,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    file_size_bytes INTEGER NOT NULL DEFAULT 0,
    mime_type VARCHAR(64) NOT NULL DEFAULT 'audio/wav',
    encryption_algorithm VARCHAR(32) NOT NULL DEFAULT 'AES-256-GCM',
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 35. Workflow Executions Table (Durable Sagas)
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

-- 36. Workflow Step Logs (Audit and Compensation Traceability)
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

-- 37. Notification Templates Table
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

-- 38. Notification Logs Table (Delivery Auditing)
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

-- 39. Automation Rules Table (Event-Driven Rules)
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

-- 40. Knowledge Documents Table (Approved Ingestion & Provenance)
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    source_type VARCHAR(50) NOT NULL DEFAULT 'TEXT',
    document_hash VARCHAR(64) NOT NULL,
    acl_roles TEXT[] NOT NULL DEFAULT ARRAY['public'],
    status VARCHAR(50) NOT NULL DEFAULT 'INDEXED',
    poison_reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 41. Knowledge Chunks Table (Permission-Filtered RAG Chunks)
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

-- 42. Model Execution Logs Table (Model Gateway Auditing & Budgets)
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
    status VARCHAR(50) NOT NULL DEFAULT 'SUCCESS',
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 43. Agent Definitions Table (Agent Catalog & Capability Metadata)
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

-- 44. Agent Execution Logs Table (Multi-Agent Traces & Token Consumption)
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

-- 45. Copilot Briefs Table (Sales Representative Copilot Actions & Approvals)
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

-- 46. Agent Evaluations Table (Offline Evaluation Corpus & Trace Benchmarks)
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

-- 47. Tenant Subscriptions & Plans
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

-- 48. Tenant Usage Meters
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

-- 49. Tenant Quota Limits
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

-- 50. Analytics Daily Sales
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

-- 51. Analytics Pipeline Snapshots
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

-- 52. Analytics AI Performance
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

-- 53. System Alert Events
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

-- 54. System Metric Snapshots
CREATE TABLE IF NOT EXISTS system_metric_snapshots (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    metric_family VARCHAR(64) NOT NULL,
    metric_name VARCHAR(64) NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for Step 11 Performance
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_tenant ON tenant_subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_status ON tenant_subscriptions(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_tenant_usage_meters_tenant ON tenant_usage_meters(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_usage_meters_period ON tenant_usage_meters(tenant_id, period_month);
CREATE INDEX IF NOT EXISTS idx_tenant_quota_limits_tenant ON tenant_quota_limits(tenant_id);
CREATE INDEX IF NOT EXISTS idx_analytics_daily_sales_tenant ON analytics_daily_sales(tenant_id);
CREATE INDEX IF NOT EXISTS idx_analytics_daily_sales_date ON analytics_daily_sales(tenant_id, date);
CREATE INDEX IF NOT EXISTS idx_pipeline_snapshots_tenant ON analytics_pipeline_snapshots(tenant_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_snapshots_date ON analytics_pipeline_snapshots(tenant_id, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_analytics_ai_perf_tenant ON analytics_ai_performance(tenant_id);
CREATE INDEX IF NOT EXISTS idx_analytics_ai_perf_date ON analytics_ai_performance(tenant_id, date);
CREATE INDEX IF NOT EXISTS idx_system_alert_events_tenant ON system_alert_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_system_alert_events_status ON system_alert_events(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_system_alert_events_severity ON system_alert_events(tenant_id, severity);
CREATE INDEX IF NOT EXISTS idx_system_metric_snapshots_tenant ON system_metric_snapshots(tenant_id);
CREATE INDEX IF NOT EXISTS idx_system_metric_snapshots_family ON system_metric_snapshots(tenant_id, metric_family);
CREATE INDEX IF NOT EXISTS idx_system_metric_snapshots_time ON system_metric_snapshots(tenant_id, recorded_at);

-- Indexes for Step 04 Performance
CREATE INDEX IF NOT EXISTS idx_accounts_tenant ON accounts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_contacts_account ON contacts(account_id);
CREATE INDEX IF NOT EXISTS idx_leads_tenant_status ON leads(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_opportunities_tenant_stage ON opportunities(tenant_id, stage);
CREATE INDEX IF NOT EXISTS idx_activities_tenant ON activities(tenant_id);
CREATE INDEX IF NOT EXISTS idx_products_tenant ON products(tenant_id, is_active);
CREATE INDEX IF NOT EXISTS idx_price_lists_tenant ON price_lists(tenant_id, is_active);
CREATE INDEX IF NOT EXISTS idx_quotes_tenant_status ON quotes(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_quote_items_quote ON quote_items(quote_id);
CREATE INDEX IF NOT EXISTS idx_quote_approvals_quote ON quote_approvals(quote_id, status);
CREATE INDEX IF NOT EXISTS idx_quote_documents_quote ON quote_documents(quote_id);

-- Indexes for Step 05 Performance
CREATE INDEX IF NOT EXISTS idx_warehouses_tenant ON warehouses(tenant_id);
CREATE INDEX IF NOT EXISTS idx_inventory_items_tenant ON inventory_items(tenant_id);
CREATE INDEX IF NOT EXISTS idx_inventory_items_sku ON inventory_items(tenant_id, sku);
CREATE INDEX IF NOT EXISTS idx_stock_reservations_tenant ON stock_reservations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_stock_reservations_status_expiry ON stock_reservations(status, reserved_until);
CREATE INDEX IF NOT EXISTS idx_stock_movements_tenant ON stock_movements(tenant_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_item ON stock_movements(inventory_item_id);
CREATE INDEX IF NOT EXISTS idx_sales_orders_tenant ON sales_orders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_sales_orders_quote ON sales_orders(quote_id);
CREATE INDEX IF NOT EXISTS idx_order_items_tenant ON order_items(tenant_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_payment_intents_tenant ON payment_intents(tenant_id);
CREATE INDEX IF NOT EXISTS idx_payment_intents_order ON payment_intents(order_id);
CREATE INDEX IF NOT EXISTS idx_payment_transactions_tenant ON payment_transactions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_payment_transactions_order ON payment_transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_refund_requests_tenant ON refund_requests(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invoices_tenant ON invoices(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invoices_order ON invoices(order_id);
CREATE INDEX IF NOT EXISTS idx_invoice_items_tenant ON invoice_items(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);

-- Indexes for Step 06 Performance
CREATE INDEX IF NOT EXISTS idx_suppliers_tenant ON suppliers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_supplier_products_tenant ON supplier_products(tenant_id);
CREATE INDEX IF NOT EXISTS idx_supplier_products_supplier ON supplier_products(tenant_id, supplier_id);
CREATE INDEX IF NOT EXISTS idx_rfqs_tenant ON rfqs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rfq_items_tenant ON rfq_items(tenant_id, rfq_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_tenant ON purchase_orders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_po_items_tenant ON purchase_order_items(tenant_id, purchase_order_id);
CREATE INDEX IF NOT EXISTS idx_goods_receipts_tenant ON goods_receipts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_goods_receipts_po ON goods_receipts(tenant_id, purchase_order_id);
CREATE INDEX IF NOT EXISTS idx_gr_items_tenant ON goods_receipt_items(tenant_id, goods_receipt_id);
CREATE INDEX IF NOT EXISTS idx_stock_transfers_tenant ON stock_transfers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_stock_transfer_items_tenant ON stock_transfer_items(tenant_id, transfer_id);
CREATE INDEX IF NOT EXISTS idx_shipments_tenant ON shipments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_shipments_order ON shipments(tenant_id, order_id);
CREATE INDEX IF NOT EXISTS idx_shipments_tracking ON shipments(tenant_id, carrier_code, tracking_number);
CREATE INDEX IF NOT EXISTS idx_shipment_items_tenant ON shipment_items(tenant_id, shipment_id);
CREATE INDEX IF NOT EXISTS idx_tracking_events_tenant ON shipment_tracking_events(tenant_id, shipment_id, event_timestamp);
CREATE INDEX IF NOT EXISTS idx_delivery_proofs_tenant ON delivery_proofs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_support_tickets_tenant ON support_tickets(tenant_id);
CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_ticket_messages_tenant ON ticket_messages(tenant_id, ticket_id);
CREATE INDEX IF NOT EXISTS idx_warranty_claims_tenant ON warranty_claims(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rma_tenant ON return_authorizations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rma_order ON return_authorizations(tenant_id, order_id);
CREATE INDEX IF NOT EXISTS idx_return_items_tenant ON return_items(tenant_id, rma_id);
CREATE INDEX IF NOT EXISTS idx_appointments_tenant ON appointments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_appointments_staff_schedule ON appointments(tenant_id, staff_user_id, start_time, end_time);

-- Indexes for Step 07 Performance
CREATE INDEX IF NOT EXISTS idx_voice_sessions_tenant ON voice_sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_voice_sessions_session_id ON voice_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_voice_sessions_caller ON voice_sessions(caller_identifier);
CREATE INDEX IF NOT EXISTS idx_voice_transcripts_tenant ON voice_transcripts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_voice_transcripts_session ON voice_transcripts(session_id);
CREATE INDEX IF NOT EXISTS idx_voice_recordings_tenant ON voice_recordings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_voice_recordings_session ON voice_recordings(session_id);
CREATE INDEX IF NOT EXISTS idx_voice_recordings_expires ON voice_recordings(expires_at);

-- Indexes for Step 07 Workflows, Notifications & Automations
CREATE INDEX IF NOT EXISTS idx_workflow_executions_tenant_status ON workflow_executions(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_correlation ON workflow_executions(tenant_id, correlation_id);
CREATE INDEX IF NOT EXISTS idx_workflow_step_logs_wf ON workflow_step_logs(workflow_id, created_at);
CREATE INDEX IF NOT EXISTS idx_notif_templates_lookup ON notification_templates(tenant_id, template_code, channel_type);
CREATE INDEX IF NOT EXISTS idx_notif_logs_tenant_status ON notification_logs(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_notif_logs_recipient ON notification_logs(tenant_id, recipient_identifier);
CREATE INDEX IF NOT EXISTS idx_automation_rules_trigger ON automation_rules(tenant_id, trigger_event) WHERE is_active = true;

-- Indexes for Step 08 RAG, Knowledge & Model Gateway
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_tenant_status ON knowledge_documents(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_hash ON knowledge_documents(tenant_id, document_hash);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_tenant_doc ON knowledge_chunks(tenant_id, document_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_doc_index ON knowledge_chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_model_execution_logs_tenant ON model_execution_logs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_execution_logs_turn ON model_execution_logs(turn_id);

-- Indexes for Step 09 Performance
CREATE INDEX IF NOT EXISTS idx_agent_definitions_tenant ON agent_definitions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_definitions_group ON agent_definitions(tenant_id, role_group);
CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_tenant ON agent_execution_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_conv ON agent_execution_logs(tenant_id, conversation_id);
CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_role ON agent_execution_logs(tenant_id, agent_role);
CREATE INDEX IF NOT EXISTS idx_agent_execution_logs_status ON agent_execution_logs(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_copilot_briefs_tenant ON copilot_briefs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_copilot_briefs_conv ON copilot_briefs(tenant_id, conversation_id);
CREATE INDEX IF NOT EXISTS idx_copilot_briefs_rep ON copilot_briefs(tenant_id, representative_id);
CREATE INDEX IF NOT EXISTS idx_agent_evaluations_tenant ON agent_evaluations(tenant_id);

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

ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounts FORCE ROW LEVEL SECURITY;

ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads FORCE ROW LEVEL SECURITY;

ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunities FORCE ROW LEVEL SECURITY;

ALTER TABLE activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE activities FORCE ROW LEVEL SECURITY;

ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE products FORCE ROW LEVEL SECURITY;

ALTER TABLE product_variants ENABLE ROW LEVEL SECURITY;
ALTER TABLE product_variants FORCE ROW LEVEL SECURITY;

ALTER TABLE price_lists ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_lists FORCE ROW LEVEL SECURITY;

ALTER TABLE price_list_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_list_items FORCE ROW LEVEL SECURITY;

ALTER TABLE quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE quotes FORCE ROW LEVEL SECURITY;

ALTER TABLE quote_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE quote_items FORCE ROW LEVEL SECURITY;

ALTER TABLE quote_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE quote_approvals FORCE ROW LEVEL SECURITY;

ALTER TABLE quote_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE quote_documents FORCE ROW LEVEL SECURITY;

ALTER TABLE warehouses ENABLE ROW LEVEL SECURITY;
ALTER TABLE warehouses FORCE ROW LEVEL SECURITY;

ALTER TABLE inventory_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_items FORCE ROW LEVEL SECURITY;

ALTER TABLE stock_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_reservations FORCE ROW LEVEL SECURITY;

ALTER TABLE stock_movements ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_movements FORCE ROW LEVEL SECURITY;

ALTER TABLE sales_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE sales_orders FORCE ROW LEVEL SECURITY;

ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_items FORCE ROW LEVEL SECURITY;

ALTER TABLE payment_intents ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_intents FORCE ROW LEVEL SECURITY;

ALTER TABLE payment_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_transactions FORCE ROW LEVEL SECURITY;

ALTER TABLE refund_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE refund_requests FORCE ROW LEVEL SECURITY;

ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices FORCE ROW LEVEL SECURITY;

ALTER TABLE invoice_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_items FORCE ROW LEVEL SECURITY;

ALTER TABLE suppliers ENABLE ROW LEVEL SECURITY;
ALTER TABLE suppliers FORCE ROW LEVEL SECURITY;

ALTER TABLE supplier_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE supplier_products FORCE ROW LEVEL SECURITY;

ALTER TABLE rfqs ENABLE ROW LEVEL SECURITY;
ALTER TABLE rfqs FORCE ROW LEVEL SECURITY;

ALTER TABLE rfq_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE rfq_items FORCE ROW LEVEL SECURITY;

ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_orders FORCE ROW LEVEL SECURITY;

ALTER TABLE purchase_order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_order_items FORCE ROW LEVEL SECURITY;

ALTER TABLE goods_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE goods_receipts FORCE ROW LEVEL SECURITY;

ALTER TABLE goods_receipt_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE goods_receipt_items FORCE ROW LEVEL SECURITY;

ALTER TABLE stock_transfers ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_transfers FORCE ROW LEVEL SECURITY;

ALTER TABLE stock_transfer_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_transfer_items FORCE ROW LEVEL SECURITY;

ALTER TABLE shipments ENABLE ROW LEVEL SECURITY;
ALTER TABLE shipments FORCE ROW LEVEL SECURITY;

ALTER TABLE shipment_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE shipment_items FORCE ROW LEVEL SECURITY;

ALTER TABLE shipment_tracking_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE shipment_tracking_events FORCE ROW LEVEL SECURITY;

ALTER TABLE delivery_proofs ENABLE ROW LEVEL SECURITY;
ALTER TABLE delivery_proofs FORCE ROW LEVEL SECURITY;

ALTER TABLE support_tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE support_tickets FORCE ROW LEVEL SECURITY;

ALTER TABLE ticket_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE ticket_messages FORCE ROW LEVEL SECURITY;

ALTER TABLE warranty_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE warranty_claims FORCE ROW LEVEL SECURITY;

ALTER TABLE return_authorizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE return_authorizations FORCE ROW LEVEL SECURITY;

ALTER TABLE return_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE return_items FORCE ROW LEVEL SECURITY;

ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments FORCE ROW LEVEL SECURITY;

ALTER TABLE voice_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_sessions FORCE ROW LEVEL SECURITY;

ALTER TABLE voice_transcripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_transcripts FORCE ROW LEVEL SECURITY;

ALTER TABLE voice_recordings ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_recordings FORCE ROW LEVEL SECURITY;

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

ALTER TABLE knowledge_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_documents FORCE ROW LEVEL SECURITY;

ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_chunks FORCE ROW LEVEL SECURITY;

ALTER TABLE model_execution_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_execution_logs FORCE ROW LEVEL SECURITY;

ALTER TABLE agent_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_definitions FORCE ROW LEVEL SECURITY;

ALTER TABLE agent_execution_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_execution_logs FORCE ROW LEVEL SECURITY;

ALTER TABLE copilot_briefs ENABLE ROW LEVEL SECURITY;
ALTER TABLE copilot_briefs FORCE ROW LEVEL SECURITY;

ALTER TABLE agent_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_evaluations FORCE ROW LEVEL SECURITY;

ALTER TABLE tenant_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_subscriptions FORCE ROW LEVEL SECURITY;

ALTER TABLE tenant_usage_meters ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_usage_meters FORCE ROW LEVEL SECURITY;

ALTER TABLE tenant_quota_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_quota_limits FORCE ROW LEVEL SECURITY;

ALTER TABLE analytics_daily_sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_daily_sales FORCE ROW LEVEL SECURITY;

ALTER TABLE analytics_pipeline_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_pipeline_snapshots FORCE ROW LEVEL SECURITY;

ALTER TABLE analytics_ai_performance ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_ai_performance FORCE ROW LEVEL SECURITY;

ALTER TABLE system_alert_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_alert_events FORCE ROW LEVEL SECURITY;

ALTER TABLE system_metric_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_metric_snapshots FORCE ROW LEVEL SECURITY;

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

CREATE POLICY tenant_isolation_accounts ON accounts
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_leads ON leads
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_opportunities ON opportunities
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_activities ON activities
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_products ON products
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_product_variants ON product_variants
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_price_lists ON price_lists
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_price_list_items ON price_list_items
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_quotes ON quotes
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_quote_items ON quote_items
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_quote_approvals ON quote_approvals
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_quote_documents ON quote_documents
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_warehouses ON warehouses
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_inventory_items ON inventory_items
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_stock_reservations ON stock_reservations
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_stock_movements ON stock_movements
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_sales_orders ON sales_orders
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_order_items ON order_items
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_payment_intents ON payment_intents
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_payment_transactions ON payment_transactions
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_refund_requests ON refund_requests
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_invoices ON invoices
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_invoice_items ON invoice_items
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_suppliers ON suppliers
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_supplier_products ON supplier_products
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_rfqs ON rfqs
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_rfq_items ON rfq_items
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_purchase_orders ON purchase_orders
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_purchase_order_items ON purchase_order_items
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_goods_receipts ON goods_receipts
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_goods_receipt_items ON goods_receipt_items
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_stock_transfers ON stock_transfers
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_stock_transfer_items ON stock_transfer_items
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_shipments ON shipments
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_shipment_items ON shipment_items
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_shipment_tracking_events ON shipment_tracking_events
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_delivery_proofs ON delivery_proofs
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_support_tickets ON support_tickets
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_ticket_messages ON ticket_messages
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_warranty_claims ON warranty_claims
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_return_authorizations ON return_authorizations
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_return_items ON return_items
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_appointments ON appointments
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_voice_sessions ON voice_sessions
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_voice_transcripts ON voice_transcripts
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_voice_recordings ON voice_recordings
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_workflow_executions ON workflow_executions
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_workflow_step_logs ON workflow_step_logs
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_notification_templates ON notification_templates
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_notification_logs ON notification_logs
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_automation_rules ON automation_rules
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_knowledge_documents ON knowledge_documents
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_knowledge_chunks ON knowledge_chunks
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_model_execution_logs ON model_execution_logs
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_agent_definitions ON agent_definitions
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_agent_execution_logs ON agent_execution_logs
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_copilot_briefs ON copilot_briefs
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_agent_evaluations ON agent_evaluations
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_tenant_subscriptions ON tenant_subscriptions
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_tenant_usage_meters ON tenant_usage_meters
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_tenant_quota_limits ON tenant_quota_limits
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_analytics_daily_sales ON analytics_daily_sales
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_analytics_pipeline_snapshots ON analytics_pipeline_snapshots
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_analytics_ai_performance ON analytics_ai_performance
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_system_alert_events ON system_alert_events
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

CREATE POLICY tenant_isolation_system_metric_snapshots ON system_metric_snapshots
    AS PERMISSIVE FOR ALL TO PUBLIC
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
    ('perm_voice_agent', 'voice:agent', 'Initiate and manage customer voice sessions', 'VOICE'),
    ('perm_audit_read', 'audit:read', 'View compliance and security audit logs', 'SECURITY'),
    ('perm_crm_read', 'crm:read', 'View CRM leads, accounts and opportunities', 'CRM'),
    ('perm_crm_write', 'crm:write', 'Create and modify CRM leads, accounts and opportunities', 'CRM'),
    ('perm_catalog_read', 'catalog:read', 'View catalog products and price lists', 'COMMERCE'),
    ('perm_catalog_write', 'catalog:write', 'Manage products and price lists', 'COMMERCE'),
    ('perm_quotes_read', 'quotes:read', 'View commercial quotations and proposals', 'COMMERCE'),
    ('perm_quotes_write', 'quotes:write', 'Create and update quotations', 'COMMERCE'),
    ('perm_procurement_manage', 'procurement:manage', 'Manage suppliers, RFQs, purchase orders and goods receipt', 'OPERATIONS'),
    ('perm_procurement_read', 'procurement:read', 'View suppliers and purchase orders', 'OPERATIONS'),
    ('perm_logistics_manage', 'logistics:manage', 'Manage shipments, carrier dispatch and delivery proofs', 'OPERATIONS'),
    ('perm_logistics_read', 'logistics:read', 'View shipments and tracking events', 'OPERATIONS'),
    ('perm_support_manage', 'support:manage', 'Manage support tickets, warranties and return authorizations', 'SUPPORT'),
    ('perm_support_read', 'support:read', 'View support tickets and return authorizations', 'SUPPORT'),
    ('perm_scheduling_manage', 'scheduling:manage', 'Manage appointment slots and staff calendars', 'SCHEDULING'),
    ('perm_scheduling_read', 'scheduling:read', 'View appointments and booking availability', 'SCHEDULING'),
    ('perm_workflows_manage', 'workflows:manage', 'Manage, trigger and retry durable workflows', 'WORKFLOWS'),
    ('perm_workflows_read', 'workflows:read', 'View workflow executions and step logs', 'WORKFLOWS'),
    ('perm_notifications_manage', 'notifications:manage', 'Manage notification templates and send broadcasts', 'NOTIFICATIONS'),
    ('perm_integrations_manage', 'integrations:manage', 'Configure external integrations and n8n webhooks', 'INTEGRATIONS'),
    ('perm_ai_manage', 'ai:manage', 'Manage Model Gateway configuration, prompt templates and budgets', 'AI'),
    ('perm_ai_rag', 'ai:rag', 'Query and manage knowledge documents and embeddings', 'AI'),
    ('perm_ai_tools', 'ai:tools', 'Execute bounded AI tool contracts', 'AI'),
    ('perm_ai_agents', 'ai:agents', 'Manage agent definitions, handoffs and supervisor state', 'AI'),
    ('perm_ai_copilot', 'ai:copilot', 'Access Sales Representative Copilot workspace and action proposals', 'AI'),
    ('perm_analytics_read', 'analytics:read', 'View executive and operational business analytics', 'ANALYTICS'),
    ('perm_analytics_manage', 'analytics:manage', 'Manage analytics aggregation, data exports and forecasting', 'ANALYTICS'),
    ('perm_observability_read', 'observability:read', 'View system telemetry, traces, AI model metrics and alerts', 'OBSERVABILITY'),
    ('perm_saas_manage', 'saas:manage', 'Manage tenant subscription plans, quotas and usage metering', 'SAAS')
ON CONFLICT (code) DO NOTHING;


-- =============================================================================
-- 011: RLS-compatible pre-authentication lookups (inspection finding F-09)
-- =============================================================================
-- Under FORCE ROW LEVEL SECURITY the least-privileged application role
-- (sales_app_user) cannot read `users` before a tenant is known, so login could
-- only work when the API connected as a superuser (which bypasses RLS).
-- This function exposes the minimum needed for login: the tenant ids of ACTIVE
-- users with a given email. It returns no password hashes, MFA secrets or PII.
-- It is SECURITY DEFINER (runs as the table owner) with a pinned search_path.

CREATE OR REPLACE FUNCTION auth_resolve_login_tenants(p_email TEXT, p_tenant_id TEXT DEFAULT NULL)
RETURNS TABLE (tenant_id VARCHAR)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT u.tenant_id
    FROM users u
    JOIN tenants t ON t.id = u.tenant_id
    WHERE lower(u.email) = lower(p_email)
      AND u.is_active = true
      AND t.is_active = true
      AND (p_tenant_id IS NULL OR u.tenant_id = p_tenant_id)
    LIMIT 2;
$$;

REVOKE ALL ON FUNCTION auth_resolve_login_tenants(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_resolve_login_tenants(TEXT, TEXT) TO sales_app_user;


-- =============================================================================
-- 012: Same-tenant referential integrity and commerce invariants
--      (inspection findings F-11 and F-28)
-- =============================================================================
-- Generated from the live catalog of migration 011: every single-column foreign key
-- between two tenant-scoped tables gets a composite (tenant_id, fk) -> (tenant_id, id)
-- twin, so a row can never reference another tenant's row. PostgreSQL RI checks bypass
-- RLS, which is why RLS alone did not prevent this (cross_tenant_fk_probe.json).
-- The original single-column FKs are kept for their ON DELETE behaviour; with MATCH
-- SIMPLE a NULL reference is not checked, so SET NULL actions keep working.

BEGIN;

-- 1. Parent keys
ALTER TABLE accounts ADD CONSTRAINT uq_accounts_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE contacts ADD CONSTRAINT uq_contacts_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE conversation_messages ADD CONSTRAINT uq_conversation_messages_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE conversations ADD CONSTRAINT uq_conversations_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE goods_receipts ADD CONSTRAINT uq_goods_receipts_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE inventory_items ADD CONSTRAINT uq_inventory_items_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE invoices ADD CONSTRAINT uq_invoices_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE knowledge_documents ADD CONSTRAINT uq_knowledge_documents_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE leads ADD CONSTRAINT uq_leads_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE notification_templates ADD CONSTRAINT uq_notification_templates_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE opportunities ADD CONSTRAINT uq_opportunities_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE order_items ADD CONSTRAINT uq_order_items_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE payment_intents ADD CONSTRAINT uq_payment_intents_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE price_lists ADD CONSTRAINT uq_price_lists_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE product_variants ADD CONSTRAINT uq_product_variants_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE products ADD CONSTRAINT uq_products_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE purchase_order_items ADD CONSTRAINT uq_purchase_order_items_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE purchase_orders ADD CONSTRAINT uq_purchase_orders_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE quotes ADD CONSTRAINT uq_quotes_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE return_authorizations ADD CONSTRAINT uq_return_authorizations_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE rfqs ADD CONSTRAINT uq_rfqs_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE sales_orders ADD CONSTRAINT uq_sales_orders_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE shipments ADD CONSTRAINT uq_shipments_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE stock_transfers ADD CONSTRAINT uq_stock_transfers_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE suppliers ADD CONSTRAINT uq_suppliers_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE support_tickets ADD CONSTRAINT uq_support_tickets_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE users ADD CONSTRAINT uq_users_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE warehouses ADD CONSTRAINT uq_warehouses_tenant_id_id UNIQUE (tenant_id, id);
ALTER TABLE workflow_executions ADD CONSTRAINT uq_workflow_executions_tenant_id_id UNIQUE (tenant_id, id);

-- 2. Same-tenant composite foreign keys
ALTER TABLE user_roles ADD CONSTRAINT fk_same_tenant_user_roles_user_id FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id);
ALTER TABLE session_revocations ADD CONSTRAINT fk_same_tenant_session_revocations_user_id FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id);
ALTER TABLE contacts ADD CONSTRAINT fk_same_tenant_contacts_account_id FOREIGN KEY (tenant_id, account_id) REFERENCES accounts (tenant_id, id);
ALTER TABLE channel_identities ADD CONSTRAINT fk_same_tenant_channel_identities_contact_id FOREIGN KEY (tenant_id, contact_id) REFERENCES contacts (tenant_id, id);
ALTER TABLE conversations ADD CONSTRAINT fk_same_tenant_conversations_assigned_user_id FOREIGN KEY (tenant_id, assigned_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE conversations ADD CONSTRAINT fk_same_tenant_conversations_contact_id FOREIGN KEY (tenant_id, contact_id) REFERENCES contacts (tenant_id, id);
ALTER TABLE conversation_messages ADD CONSTRAINT fk_same_tenant_conversation_messages_conversation_id FOREIGN KEY (tenant_id, conversation_id) REFERENCES conversations (tenant_id, id);
ALTER TABLE message_attachments ADD CONSTRAINT fk_same_tenant_message_attachments_message_id FOREIGN KEY (tenant_id, message_id) REFERENCES conversation_messages (tenant_id, id);
ALTER TABLE outbox_events ADD CONSTRAINT fk_same_tenant_outbox_events_conversation_id FOREIGN KEY (tenant_id, conversation_id) REFERENCES conversations (tenant_id, id);
ALTER TABLE accounts ADD CONSTRAINT fk_same_tenant_accounts_assigned_user_id FOREIGN KEY (tenant_id, assigned_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE leads ADD CONSTRAINT fk_same_tenant_leads_assigned_user_id FOREIGN KEY (tenant_id, assigned_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE leads ADD CONSTRAINT fk_same_tenant_leads_converted_account_id FOREIGN KEY (tenant_id, converted_account_id) REFERENCES accounts (tenant_id, id);
ALTER TABLE leads ADD CONSTRAINT fk_same_tenant_leads_converted_contact_id FOREIGN KEY (tenant_id, converted_contact_id) REFERENCES contacts (tenant_id, id);
ALTER TABLE leads ADD CONSTRAINT fk_same_tenant_leads_converted_opportunity_id FOREIGN KEY (tenant_id, converted_opportunity_id) REFERENCES opportunities (tenant_id, id);
ALTER TABLE opportunities ADD CONSTRAINT fk_same_tenant_opportunities_account_id FOREIGN KEY (tenant_id, account_id) REFERENCES accounts (tenant_id, id);
ALTER TABLE opportunities ADD CONSTRAINT fk_same_tenant_opportunities_assigned_user_id FOREIGN KEY (tenant_id, assigned_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE opportunities ADD CONSTRAINT fk_same_tenant_opportunities_contact_id FOREIGN KEY (tenant_id, contact_id) REFERENCES contacts (tenant_id, id);
ALTER TABLE opportunities ADD CONSTRAINT fk_same_tenant_opportunities_lead_id FOREIGN KEY (tenant_id, lead_id) REFERENCES leads (tenant_id, id);
ALTER TABLE activities ADD CONSTRAINT fk_same_tenant_activities_account_id FOREIGN KEY (tenant_id, account_id) REFERENCES accounts (tenant_id, id);
ALTER TABLE activities ADD CONSTRAINT fk_same_tenant_activities_assigned_user_id FOREIGN KEY (tenant_id, assigned_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE activities ADD CONSTRAINT fk_same_tenant_activities_contact_id FOREIGN KEY (tenant_id, contact_id) REFERENCES contacts (tenant_id, id);
ALTER TABLE activities ADD CONSTRAINT fk_same_tenant_activities_lead_id FOREIGN KEY (tenant_id, lead_id) REFERENCES leads (tenant_id, id);
ALTER TABLE activities ADD CONSTRAINT fk_same_tenant_activities_opportunity_id FOREIGN KEY (tenant_id, opportunity_id) REFERENCES opportunities (tenant_id, id);
ALTER TABLE product_variants ADD CONSTRAINT fk_same_tenant_product_variants_product_id FOREIGN KEY (tenant_id, product_id) REFERENCES products (tenant_id, id);
ALTER TABLE price_list_items ADD CONSTRAINT fk_same_tenant_price_list_items_price_list_id FOREIGN KEY (tenant_id, price_list_id) REFERENCES price_lists (tenant_id, id);
ALTER TABLE price_list_items ADD CONSTRAINT fk_same_tenant_price_list_items_product_id FOREIGN KEY (tenant_id, product_id) REFERENCES products (tenant_id, id);
ALTER TABLE price_list_items ADD CONSTRAINT fk_same_tenant_price_list_items_variant_id FOREIGN KEY (tenant_id, variant_id) REFERENCES product_variants (tenant_id, id);
ALTER TABLE quotes ADD CONSTRAINT fk_same_tenant_quotes_account_id FOREIGN KEY (tenant_id, account_id) REFERENCES accounts (tenant_id, id);
ALTER TABLE quotes ADD CONSTRAINT fk_same_tenant_quotes_contact_id FOREIGN KEY (tenant_id, contact_id) REFERENCES contacts (tenant_id, id);
ALTER TABLE quotes ADD CONSTRAINT fk_same_tenant_quotes_created_by_user_id FOREIGN KEY (tenant_id, created_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE quotes ADD CONSTRAINT fk_same_tenant_quotes_opportunity_id FOREIGN KEY (tenant_id, opportunity_id) REFERENCES opportunities (tenant_id, id);
ALTER TABLE quotes ADD CONSTRAINT fk_same_tenant_quotes_price_list_id FOREIGN KEY (tenant_id, price_list_id) REFERENCES price_lists (tenant_id, id);
ALTER TABLE quote_items ADD CONSTRAINT fk_same_tenant_quote_items_product_id FOREIGN KEY (tenant_id, product_id) REFERENCES products (tenant_id, id);
ALTER TABLE quote_items ADD CONSTRAINT fk_same_tenant_quote_items_quote_id FOREIGN KEY (tenant_id, quote_id) REFERENCES quotes (tenant_id, id);
ALTER TABLE quote_items ADD CONSTRAINT fk_same_tenant_quote_items_variant_id FOREIGN KEY (tenant_id, variant_id) REFERENCES product_variants (tenant_id, id);
ALTER TABLE quote_approvals ADD CONSTRAINT fk_same_tenant_quote_approvals_decided_by_user_id FOREIGN KEY (tenant_id, decided_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE quote_approvals ADD CONSTRAINT fk_same_tenant_quote_approvals_quote_id FOREIGN KEY (tenant_id, quote_id) REFERENCES quotes (tenant_id, id);
ALTER TABLE quote_approvals ADD CONSTRAINT fk_same_tenant_quote_approvals_requested_by_user_id FOREIGN KEY (tenant_id, requested_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE quote_documents ADD CONSTRAINT fk_same_tenant_quote_documents_quote_id FOREIGN KEY (tenant_id, quote_id) REFERENCES quotes (tenant_id, id);
ALTER TABLE inventory_items ADD CONSTRAINT fk_same_tenant_inventory_items_product_id FOREIGN KEY (tenant_id, product_id) REFERENCES products (tenant_id, id);
ALTER TABLE inventory_items ADD CONSTRAINT fk_same_tenant_inventory_items_variant_id FOREIGN KEY (tenant_id, variant_id) REFERENCES product_variants (tenant_id, id);
ALTER TABLE inventory_items ADD CONSTRAINT fk_same_tenant_inventory_items_warehouse_id FOREIGN KEY (tenant_id, warehouse_id) REFERENCES warehouses (tenant_id, id);
ALTER TABLE stock_reservations ADD CONSTRAINT fk_same_tenant_stock_reservations_inventory_item_id FOREIGN KEY (tenant_id, inventory_item_id) REFERENCES inventory_items (tenant_id, id);
ALTER TABLE stock_reservations ADD CONSTRAINT fk_same_tenant_stock_reservations_quote_id FOREIGN KEY (tenant_id, quote_id) REFERENCES quotes (tenant_id, id);
ALTER TABLE stock_movements ADD CONSTRAINT fk_same_tenant_stock_movements_created_by_user_id FOREIGN KEY (tenant_id, created_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE stock_movements ADD CONSTRAINT fk_same_tenant_stock_movements_inventory_item_id FOREIGN KEY (tenant_id, inventory_item_id) REFERENCES inventory_items (tenant_id, id);
ALTER TABLE sales_orders ADD CONSTRAINT fk_same_tenant_sales_orders_account_id FOREIGN KEY (tenant_id, account_id) REFERENCES accounts (tenant_id, id);
ALTER TABLE sales_orders ADD CONSTRAINT fk_same_tenant_sales_orders_contact_id FOREIGN KEY (tenant_id, contact_id) REFERENCES contacts (tenant_id, id);
ALTER TABLE sales_orders ADD CONSTRAINT fk_same_tenant_sales_orders_created_by_user_id FOREIGN KEY (tenant_id, created_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE sales_orders ADD CONSTRAINT fk_same_tenant_sales_orders_quote_id FOREIGN KEY (tenant_id, quote_id) REFERENCES quotes (tenant_id, id);
ALTER TABLE order_items ADD CONSTRAINT fk_same_tenant_order_items_order_id FOREIGN KEY (tenant_id, order_id) REFERENCES sales_orders (tenant_id, id);
ALTER TABLE order_items ADD CONSTRAINT fk_same_tenant_order_items_product_id FOREIGN KEY (tenant_id, product_id) REFERENCES products (tenant_id, id);
ALTER TABLE order_items ADD CONSTRAINT fk_same_tenant_order_items_variant_id FOREIGN KEY (tenant_id, variant_id) REFERENCES product_variants (tenant_id, id);
ALTER TABLE payment_intents ADD CONSTRAINT fk_same_tenant_payment_intents_order_id FOREIGN KEY (tenant_id, order_id) REFERENCES sales_orders (tenant_id, id);
ALTER TABLE payment_transactions ADD CONSTRAINT fk_same_tenant_payment_transactions_order_id FOREIGN KEY (tenant_id, order_id) REFERENCES sales_orders (tenant_id, id);
ALTER TABLE payment_transactions ADD CONSTRAINT fk_same_tenant_payment_transactions_payment_intent_id FOREIGN KEY (tenant_id, payment_intent_id) REFERENCES payment_intents (tenant_id, id);
ALTER TABLE refund_requests ADD CONSTRAINT fk_same_tenant_refund_requests_approved_by_user_id FOREIGN KEY (tenant_id, approved_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE refund_requests ADD CONSTRAINT fk_same_tenant_refund_requests_order_id FOREIGN KEY (tenant_id, order_id) REFERENCES sales_orders (tenant_id, id);
ALTER TABLE refund_requests ADD CONSTRAINT fk_same_tenant_refund_requests_payment_intent_id FOREIGN KEY (tenant_id, payment_intent_id) REFERENCES payment_intents (tenant_id, id);
ALTER TABLE refund_requests ADD CONSTRAINT fk_same_tenant_refund_requests_requested_by_user_id FOREIGN KEY (tenant_id, requested_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE invoices ADD CONSTRAINT fk_same_tenant_invoices_correction_of_invoice_id FOREIGN KEY (tenant_id, correction_of_invoice_id) REFERENCES invoices (tenant_id, id);
ALTER TABLE invoices ADD CONSTRAINT fk_same_tenant_invoices_order_id FOREIGN KEY (tenant_id, order_id) REFERENCES sales_orders (tenant_id, id);
ALTER TABLE invoice_items ADD CONSTRAINT fk_same_tenant_invoice_items_invoice_id FOREIGN KEY (tenant_id, invoice_id) REFERENCES invoices (tenant_id, id);
ALTER TABLE supplier_products ADD CONSTRAINT fk_same_tenant_supplier_products_product_id FOREIGN KEY (tenant_id, product_id) REFERENCES products (tenant_id, id);
ALTER TABLE supplier_products ADD CONSTRAINT fk_same_tenant_supplier_products_supplier_id FOREIGN KEY (tenant_id, supplier_id) REFERENCES suppliers (tenant_id, id);
ALTER TABLE rfqs ADD CONSTRAINT fk_same_tenant_rfqs_created_by_user_id FOREIGN KEY (tenant_id, created_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE rfqs ADD CONSTRAINT fk_same_tenant_rfqs_supplier_id FOREIGN KEY (tenant_id, supplier_id) REFERENCES suppliers (tenant_id, id);
ALTER TABLE rfq_items ADD CONSTRAINT fk_same_tenant_rfq_items_product_id FOREIGN KEY (tenant_id, product_id) REFERENCES products (tenant_id, id);
ALTER TABLE rfq_items ADD CONSTRAINT fk_same_tenant_rfq_items_rfq_id FOREIGN KEY (tenant_id, rfq_id) REFERENCES rfqs (tenant_id, id);
ALTER TABLE purchase_orders ADD CONSTRAINT fk_same_tenant_purchase_orders_approved_by_user_id FOREIGN KEY (tenant_id, approved_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE purchase_orders ADD CONSTRAINT fk_same_tenant_purchase_orders_created_by_user_id FOREIGN KEY (tenant_id, created_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE purchase_orders ADD CONSTRAINT fk_same_tenant_purchase_orders_rfq_id FOREIGN KEY (tenant_id, rfq_id) REFERENCES rfqs (tenant_id, id);
ALTER TABLE purchase_orders ADD CONSTRAINT fk_same_tenant_purchase_orders_supplier_id FOREIGN KEY (tenant_id, supplier_id) REFERENCES suppliers (tenant_id, id);
ALTER TABLE purchase_orders ADD CONSTRAINT fk_same_tenant_purchase_orders_warehouse_id FOREIGN KEY (tenant_id, warehouse_id) REFERENCES warehouses (tenant_id, id);
ALTER TABLE purchase_order_items ADD CONSTRAINT fk_same_tenant_purchase_order_items_product_id FOREIGN KEY (tenant_id, product_id) REFERENCES products (tenant_id, id);
ALTER TABLE purchase_order_items ADD CONSTRAINT fk_same_tenant_purchase_order_items_purchase_order_id FOREIGN KEY (tenant_id, purchase_order_id) REFERENCES purchase_orders (tenant_id, id);
ALTER TABLE goods_receipts ADD CONSTRAINT fk_same_tenant_goods_receipts_purchase_order_id FOREIGN KEY (tenant_id, purchase_order_id) REFERENCES purchase_orders (tenant_id, id);
ALTER TABLE goods_receipts ADD CONSTRAINT fk_same_tenant_goods_receipts_received_by_user_id FOREIGN KEY (tenant_id, received_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE goods_receipts ADD CONSTRAINT fk_same_tenant_goods_receipts_warehouse_id FOREIGN KEY (tenant_id, warehouse_id) REFERENCES warehouses (tenant_id, id);
ALTER TABLE goods_receipt_items ADD CONSTRAINT fk_same_tenant_goods_receipt_items_goods_receipt_id FOREIGN KEY (tenant_id, goods_receipt_id) REFERENCES goods_receipts (tenant_id, id);
ALTER TABLE goods_receipt_items ADD CONSTRAINT fk_same_tenant_goods_receipt_items_po_item_id FOREIGN KEY (tenant_id, po_item_id) REFERENCES purchase_order_items (tenant_id, id);
ALTER TABLE stock_transfers ADD CONSTRAINT fk_same_tenant_stock_transfers_created_by_user_id FOREIGN KEY (tenant_id, created_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE stock_transfers ADD CONSTRAINT fk_same_tenant_stock_transfers_destination_warehouse_id FOREIGN KEY (tenant_id, destination_warehouse_id) REFERENCES warehouses (tenant_id, id);
ALTER TABLE stock_transfers ADD CONSTRAINT fk_same_tenant_stock_transfers_source_warehouse_id FOREIGN KEY (tenant_id, source_warehouse_id) REFERENCES warehouses (tenant_id, id);
ALTER TABLE stock_transfer_items ADD CONSTRAINT fk_same_tenant_stock_transfer_items_transfer_id FOREIGN KEY (tenant_id, transfer_id) REFERENCES stock_transfers (tenant_id, id);
ALTER TABLE shipments ADD CONSTRAINT fk_same_tenant_shipments_created_by_user_id FOREIGN KEY (tenant_id, created_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE shipments ADD CONSTRAINT fk_same_tenant_shipments_order_id FOREIGN KEY (tenant_id, order_id) REFERENCES sales_orders (tenant_id, id);
ALTER TABLE shipments ADD CONSTRAINT fk_same_tenant_shipments_warehouse_id FOREIGN KEY (tenant_id, warehouse_id) REFERENCES warehouses (tenant_id, id);
ALTER TABLE shipment_items ADD CONSTRAINT fk_same_tenant_shipment_items_order_item_id FOREIGN KEY (tenant_id, order_item_id) REFERENCES order_items (tenant_id, id);
ALTER TABLE shipment_items ADD CONSTRAINT fk_same_tenant_shipment_items_shipment_id FOREIGN KEY (tenant_id, shipment_id) REFERENCES shipments (tenant_id, id);
ALTER TABLE shipment_tracking_events ADD CONSTRAINT fk_same_tenant_shipment_tracking_events_shipment_id FOREIGN KEY (tenant_id, shipment_id) REFERENCES shipments (tenant_id, id);
ALTER TABLE delivery_proofs ADD CONSTRAINT fk_same_tenant_delivery_proofs_shipment_id FOREIGN KEY (tenant_id, shipment_id) REFERENCES shipments (tenant_id, id);
ALTER TABLE support_tickets ADD CONSTRAINT fk_same_tenant_support_tickets_account_id FOREIGN KEY (tenant_id, account_id) REFERENCES accounts (tenant_id, id);
ALTER TABLE support_tickets ADD CONSTRAINT fk_same_tenant_support_tickets_assigned_user_id FOREIGN KEY (tenant_id, assigned_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE support_tickets ADD CONSTRAINT fk_same_tenant_support_tickets_contact_id FOREIGN KEY (tenant_id, contact_id) REFERENCES contacts (tenant_id, id);
ALTER TABLE support_tickets ADD CONSTRAINT fk_same_tenant_support_tickets_order_id FOREIGN KEY (tenant_id, order_id) REFERENCES sales_orders (tenant_id, id);
ALTER TABLE ticket_messages ADD CONSTRAINT fk_same_tenant_ticket_messages_sender_user_id FOREIGN KEY (tenant_id, sender_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE ticket_messages ADD CONSTRAINT fk_same_tenant_ticket_messages_ticket_id FOREIGN KEY (tenant_id, ticket_id) REFERENCES support_tickets (tenant_id, id);
ALTER TABLE warranty_claims ADD CONSTRAINT fk_same_tenant_warranty_claims_order_id FOREIGN KEY (tenant_id, order_id) REFERENCES sales_orders (tenant_id, id);
ALTER TABLE warranty_claims ADD CONSTRAINT fk_same_tenant_warranty_claims_order_item_id FOREIGN KEY (tenant_id, order_item_id) REFERENCES order_items (tenant_id, id);
ALTER TABLE warranty_claims ADD CONSTRAINT fk_same_tenant_warranty_claims_resolved_by_user_id FOREIGN KEY (tenant_id, resolved_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE warranty_claims ADD CONSTRAINT fk_same_tenant_warranty_claims_ticket_id FOREIGN KEY (tenant_id, ticket_id) REFERENCES support_tickets (tenant_id, id);
ALTER TABLE return_authorizations ADD CONSTRAINT fk_same_tenant_return_authorizations_authorized_by_user_id FOREIGN KEY (tenant_id, authorized_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE return_authorizations ADD CONSTRAINT fk_same_tenant_return_authorizations_destination_warehouse_id FOREIGN KEY (tenant_id, destination_warehouse_id) REFERENCES warehouses (tenant_id, id);
ALTER TABLE return_authorizations ADD CONSTRAINT fk_same_tenant_return_authorizations_inspected_by_user_id FOREIGN KEY (tenant_id, inspected_by_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE return_authorizations ADD CONSTRAINT fk_same_tenant_return_authorizations_order_id FOREIGN KEY (tenant_id, order_id) REFERENCES sales_orders (tenant_id, id);
ALTER TABLE return_authorizations ADD CONSTRAINT fk_same_tenant_return_authorizations_ticket_id FOREIGN KEY (tenant_id, ticket_id) REFERENCES support_tickets (tenant_id, id);
ALTER TABLE return_items ADD CONSTRAINT fk_same_tenant_return_items_order_item_id FOREIGN KEY (tenant_id, order_item_id) REFERENCES order_items (tenant_id, id);
ALTER TABLE return_items ADD CONSTRAINT fk_same_tenant_return_items_rma_id FOREIGN KEY (tenant_id, rma_id) REFERENCES return_authorizations (tenant_id, id);
ALTER TABLE appointments ADD CONSTRAINT fk_same_tenant_appointments_account_id FOREIGN KEY (tenant_id, account_id) REFERENCES accounts (tenant_id, id);
ALTER TABLE appointments ADD CONSTRAINT fk_same_tenant_appointments_contact_id FOREIGN KEY (tenant_id, contact_id) REFERENCES contacts (tenant_id, id);
ALTER TABLE appointments ADD CONSTRAINT fk_same_tenant_appointments_order_id FOREIGN KEY (tenant_id, order_id) REFERENCES sales_orders (tenant_id, id);
ALTER TABLE appointments ADD CONSTRAINT fk_same_tenant_appointments_staff_user_id FOREIGN KEY (tenant_id, staff_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE voice_sessions ADD CONSTRAINT fk_same_tenant_voice_sessions_customer_account_id FOREIGN KEY (tenant_id, customer_account_id) REFERENCES accounts (tenant_id, id);
ALTER TABLE voice_sessions ADD CONSTRAINT fk_same_tenant_voice_sessions_customer_contact_id FOREIGN KEY (tenant_id, customer_contact_id) REFERENCES contacts (tenant_id, id);
ALTER TABLE voice_sessions ADD CONSTRAINT fk_same_tenant_voice_sessions_manager_user_id FOREIGN KEY (tenant_id, manager_user_id) REFERENCES users (tenant_id, id);
ALTER TABLE workflow_step_logs ADD CONSTRAINT fk_same_tenant_workflow_step_logs_workflow_id FOREIGN KEY (tenant_id, workflow_id) REFERENCES workflow_executions (tenant_id, id);
ALTER TABLE notification_logs ADD CONSTRAINT fk_same_tenant_notification_logs_template_id FOREIGN KEY (tenant_id, template_id) REFERENCES notification_templates (tenant_id, id);
ALTER TABLE knowledge_documents ADD CONSTRAINT fk_same_tenant_knowledge_documents_created_by FOREIGN KEY (tenant_id, created_by) REFERENCES users (tenant_id, id);
ALTER TABLE knowledge_chunks ADD CONSTRAINT fk_same_tenant_knowledge_chunks_document_id FOREIGN KEY (tenant_id, document_id) REFERENCES knowledge_documents (tenant_id, id);
ALTER TABLE model_execution_logs ADD CONSTRAINT fk_same_tenant_model_execution_logs_conversation_id FOREIGN KEY (tenant_id, conversation_id) REFERENCES conversations (tenant_id, id);
ALTER TABLE system_alert_events ADD CONSTRAINT fk_same_tenant_system_alert_events_acknowledged_by FOREIGN KEY (tenant_id, acknowledged_by) REFERENCES users (tenant_id, id);

-- 3. Commerce invariants (F-28)
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_orders_tenant_quote ON sales_orders (tenant_id, quote_id) WHERE quote_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_refund_requests_tenant_idempotency ON refund_requests (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_intents_tenant_idempotency ON payment_intents (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
ALTER TABLE refund_requests ADD CONSTRAINT ck_refund_amount_positive CHECK (amount_cents > 0);
ALTER TABLE payment_intents ADD CONSTRAINT ck_payment_intent_amount_non_negative CHECK (amount_cents >= 0);
ALTER TABLE sales_orders ADD CONSTRAINT ck_sales_order_amounts_non_negative CHECK (grand_total_cents >= 0 AND subtotal_cents >= 0 AND discount_total_cents >= 0 AND tax_total_cents >= 0);
ALTER TABLE order_items ADD CONSTRAINT ck_order_item_quantity_positive CHECK (quantity > 0);
ALTER TABLE quote_items ADD CONSTRAINT ck_quote_item_quantity_positive CHECK (quantity > 0);
ALTER TABLE invoice_items ADD CONSTRAINT ck_invoice_item_quantity_positive CHECK (quantity > 0);
ALTER TABLE purchase_order_items ADD CONSTRAINT ck_po_item_quantities CHECK (quantity_ordered > 0 AND quantity_received >= 0);
ALTER TABLE inventory_items ADD CONSTRAINT ck_inventory_quantities_non_negative CHECK (on_hand_quantity >= 0 AND reserved_quantity >= 0 AND allocated_quantity >= 0);

-- 4. No double-booking of a staff member, enforced across all workers
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE appointments ADD CONSTRAINT ex_appointments_staff_no_overlap EXCLUDE USING gist (
    tenant_id WITH =, staff_user_id WITH =, tstzrange(start_time, end_time, '[)') WITH &&
) WHERE (staff_user_id IS NOT NULL AND status IN ('REQUESTED', 'CONFIRMED', 'IN_PROGRESS', 'RESCHEDULED'));

COMMIT;


-- =============================================================================
-- 013: Permission catalog completion (inspection finding F-34)
-- =============================================================================
-- Every permission code required by an API route must exist in the catalog
-- (enforced by tests/security/test_permission_catalog_coverage.py).
INSERT INTO permissions (id, code, description, domain) VALUES
    ('perm_inventory_manage', 'inventory:manage', 'Manage warehouses, stock items and adjustments', 'INVENTORY'),
    ('perm_orders_manage', 'orders:manage', 'Create and manage sales orders, payment intents and refund requests', 'ORDERS'),
    ('perm_users_read', 'users:read', 'View tenant users', 'IAM'),
    ('perm_users_write', 'users:write', 'Create and update tenant users', 'IAM')
ON CONFLICT (code) DO NOTHING;
