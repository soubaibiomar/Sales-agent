-- Migration: 003_crm_catalog_quotes_schema.sql
-- Step 04: CRM, Catalog, Pricing, Quotations and Approvals
-- Authoritative commercial foundation with deterministic pricing, margin floors, and exact-term approvals.

-- 1. Accounts Table (B2B/B2C Organization or Client Account)
CREATE TABLE IF NOT EXISTS accounts (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    account_type VARCHAR(50) NOT NULL DEFAULT 'CUSTOMER', -- CUSTOMER, PROSPECT, PARTNER, VENDOR
    tax_identifier VARCHAR(100), -- ICE (Morocco), VAT, EIN
    industry VARCHAR(100),
    website VARCHAR(255),
    phone VARCHAR(50),
    billing_address TEXT,
    shipping_address TEXT,
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_account_name UNIQUE (tenant_id, name)
);

-- Link contacts to accounts if not already linked
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'contacts' AND column_name = 'account_id'
    ) THEN
        ALTER TABLE contacts ADD COLUMN account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL;
    END IF;
END $$;

-- 2. Leads Table
CREATE TABLE IF NOT EXISTS leads (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    company_name VARCHAR(200),
    email VARCHAR(255),
    phone VARCHAR(50),
    status VARCHAR(50) NOT NULL DEFAULT 'NEW', -- NEW, CONTACTED, QUALIFIED, CONVERTED, DISQUALIFIED
    source VARCHAR(50) NOT NULL DEFAULT 'MANUAL', -- WEB_CHAT, WHATSAPP, EMAIL, VOICE_SIP, MANUAL, REFERRAL
    score INTEGER NOT NULL DEFAULT 0,
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    converted_account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
    converted_contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    converted_opportunity_id VARCHAR(36),
    notes TEXT,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Opportunities Table
CREATE TABLE IF NOT EXISTS opportunities (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE CASCADE,
    contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    lead_id VARCHAR(36) REFERENCES leads(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    stage VARCHAR(50) NOT NULL DEFAULT 'DISCOVERY', -- DISCOVERY, QUALIFICATION, PROPOSAL, NEGOTIATION, CLOSED_WON, CLOSED_LOST
    amount_cents BIGINT NOT NULL DEFAULT 0,
    currency VARCHAR(10) NOT NULL DEFAULT 'MAD',
    probability_percent INTEGER NOT NULL DEFAULT 20,
    expected_close_date TIMESTAMP WITH TIME ZONE,
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    lost_reason VARCHAR(255),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Add foreign key constraint for converted_opportunity_id on leads now that opportunities exists
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

-- 4. Activities Table (CRM Tasks, Calls, Notes, Meetings)
CREATE TABLE IF NOT EXISTS activities (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL, -- NOTE, CALL, EMAIL, MEETING, TASK
    subject VARCHAR(255) NOT NULL,
    description TEXT,
    due_date TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    lead_id VARCHAR(36) REFERENCES leads(id) ON DELETE CASCADE,
    opportunity_id VARCHAR(36) REFERENCES opportunities(id) ON DELETE CASCADE,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE CASCADE,
    contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 5. Products Table (Catalog Products & Services)
CREATE TABLE IF NOT EXISTS products (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    sku VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    product_type VARCHAR(50) NOT NULL DEFAULT 'PHYSICAL', -- PHYSICAL, SERVICE, SUBSCRIPTION
    uom VARCHAR(50) NOT NULL DEFAULT 'UNIT', -- UNIT, HOUR, DAY, KG, METER, BOX, PACK
    category VARCHAR(100),
    base_price_cents BIGINT NOT NULL DEFAULT 0,
    cost_cents BIGINT NOT NULL DEFAULT 0,
    currency VARCHAR(10) NOT NULL DEFAULT 'MAD',
    tax_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 20.00, -- e.g. 20% TVA in Morocco
    min_margin_percent NUMERIC(5,2) NOT NULL DEFAULT 15.00, -- Minimum acceptable profit margin floor
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_product_sku UNIQUE (tenant_id, sku)
);

-- 6. Product SKU Variants Table
CREATE TABLE IF NOT EXISTS product_variants (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    product_id VARCHAR(36) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    sku_variant VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}', -- e.g. {"color": "black", "storage": "256GB"}
    price_adjustment_cents BIGINT NOT NULL DEFAULT 0,
    cost_adjustment_cents BIGINT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_variant_sku UNIQUE (tenant_id, sku_variant)
);

-- 7. Price Lists Table
CREATE TABLE IF NOT EXISTS price_lists (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'MAD',
    description TEXT,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from TIMESTAMP WITH TIME ZONE,
    valid_to TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_pricelist_code UNIQUE (tenant_id, code)
);

-- 8. Price List Items Table (Custom pricing, tier pricing)
CREATE TABLE IF NOT EXISTS price_list_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    price_list_id VARCHAR(36) NOT NULL REFERENCES price_lists(id) ON DELETE CASCADE,
    product_id VARCHAR(36) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    variant_id VARCHAR(36) REFERENCES product_variants(id) ON DELETE CASCADE,
    unit_price_cents BIGINT NOT NULL,
    min_quantity INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 9. Quotes Table (Commercial Quotations & State Machine)
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
    -- DRAFT, PRICED, PENDING_APPROVAL, APPROVED, ISSUED, SENT, ACCEPTED, REJECTED, EXPIRED, CANCELLED
    version INTEGER NOT NULL DEFAULT 1,
    subtotal_cents BIGINT NOT NULL DEFAULT 0,
    discount_total_cents BIGINT NOT NULL DEFAULT 0,
    tax_total_cents BIGINT NOT NULL DEFAULT 0,
    grand_total_cents BIGINT NOT NULL DEFAULT 0,
    margin_percent NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    requires_approval BOOLEAN NOT NULL DEFAULT FALSE,
    approval_reason VARCHAR(255),
    terms_hash VARCHAR(64) NOT NULL, -- Cryptographic SHA-256 of line items and pricing terms
    valid_until TIMESTAMP WITH TIME ZONE NOT NULL,
    payment_terms VARCHAR(100) DEFAULT 'NET_30',
    notes TEXT,
    issued_at TIMESTAMP WITH TIME ZONE,
    accepted_at TIMESTAMP WITH TIME ZONE,
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tenant_quote_number UNIQUE (tenant_id, quote_number)
);

-- 10. Quote Items Table (Frozen Line Items Snapshot)
CREATE TABLE IF NOT EXISTS quote_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    quote_id VARCHAR(36) NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    product_id VARCHAR(36) REFERENCES products(id) ON DELETE SET NULL,
    variant_id VARCHAR(36) REFERENCES product_variants(id) ON DELETE SET NULL,
    sku_snapshot VARCHAR(100) NOT NULL,
    name_snapshot VARCHAR(255) NOT NULL,
    quantity INTEGER NOT NULL,
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
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_quote_item_quantity_positive CHECK (quantity > 0)
);

-- 11. Quote Approvals Table (Canonical Approval Queue with Exact Terms Hash)
CREATE TABLE IF NOT EXISTS quote_approvals (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    quote_id VARCHAR(36) NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    quote_version INTEGER NOT NULL,
    terms_hash VARCHAR(64) NOT NULL,
    requested_by_user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING', -- PENDING, APPROVED, REJECTED, INVALIDATED
    decided_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMP WITH TIME ZONE,
    decision_reason VARCHAR(255),
    mfa_verified BOOLEAN NOT NULL DEFAULT FALSE,
    decision_signature VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 12. Quote Documents Table (Hash-addressed generated pro-forma/quote documents)
CREATE TABLE IF NOT EXISTS quote_documents (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    quote_id VARCHAR(36) NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    quote_version INTEGER NOT NULL,
    document_type VARCHAR(50) NOT NULL DEFAULT 'PRO_FORMA', -- PRO_FORMA, FORMAL_QUOTE
    document_hash VARCHAR(64) NOT NULL, -- Cryptographic SHA-256 of document content
    file_path VARCHAR(500) NOT NULL,
    content_json TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 13. Performance Indexes
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


-- 14. Enable Row-Level Security (RLS) on all Step 04 tables
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

-- 15. Define RLS Isolation Policies
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

-- 16. Permissions grant to sales_app_user
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sales_app_user;
