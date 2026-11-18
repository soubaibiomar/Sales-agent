-- =============================================================================
-- Migration 005: Suppliers, Multi-Warehouse Procurement, Logistics, Support & Scheduling
-- Step 06: Sprint 3 - Operate
-- Comprehensive relational schema for purchase orders, goods receipts, transfers,
-- pick/pack/ship, carrier tracking, proof of delivery, support tickets, RMAs, warranties,
-- and appointment booking with PostgreSQL 16 Row-Level Security (RLS).
-- =============================================================================

-- 1. Suppliers Registry
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
CREATE INDEX IF NOT EXISTS idx_suppliers_tenant ON suppliers(tenant_id);

-- 2. Supplier Product Catalog & Pricing
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
CREATE INDEX IF NOT EXISTS idx_supplier_products_tenant ON supplier_products(tenant_id);
CREATE INDEX IF NOT EXISTS idx_supplier_products_supplier ON supplier_products(tenant_id, supplier_id);

-- 3. Request For Quotation (RFQ)
CREATE TABLE IF NOT EXISTS rfqs (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    rfq_number VARCHAR(64) NOT NULL,
    supplier_id VARCHAR(36) NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    status VARCHAR(30) DEFAULT 'DRAFT' NOT NULL, -- DRAFT, SENT, RESPONDED, CLOSED, CANCELLED
    deadline_date TIMESTAMPTZ,
    notes TEXT,
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_rfqs_tenant_number UNIQUE (tenant_id, rfq_number)
);
CREATE INDEX IF NOT EXISTS idx_rfqs_tenant ON rfqs(tenant_id);

-- 4. RFQ Line Items
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
CREATE INDEX IF NOT EXISTS idx_rfq_items_tenant ON rfq_items(tenant_id, rfq_id);

-- 5. Purchase Orders (PO)
CREATE TABLE IF NOT EXISTS purchase_orders (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    po_number VARCHAR(64) NOT NULL,
    supplier_id VARCHAR(36) NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    warehouse_id VARCHAR(36) NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    rfq_id VARCHAR(36) REFERENCES rfqs(id) ON DELETE SET NULL,
    status VARCHAR(30) DEFAULT 'DRAFT' NOT NULL, -- DRAFT, APPROVED, ISSUED, PARTIALLY_RECEIVED, RECEIVED, CLOSED, CANCELLED
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
CREATE INDEX IF NOT EXISTS idx_purchase_orders_tenant ON purchase_orders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders(tenant_id, status);

-- 6. Purchase Order Items
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
CREATE INDEX IF NOT EXISTS idx_po_items_tenant ON purchase_order_items(tenant_id, purchase_order_id);

-- 7. Goods Receipts (GRN)
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
CREATE INDEX IF NOT EXISTS idx_goods_receipts_tenant ON goods_receipts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_goods_receipts_po ON goods_receipts(tenant_id, purchase_order_id);

-- 8. Goods Receipt Line Items
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
CREATE INDEX IF NOT EXISTS idx_gr_items_tenant ON goods_receipt_items(tenant_id, goods_receipt_id);

-- 9. Inter-Warehouse Stock Transfers
CREATE TABLE IF NOT EXISTS stock_transfers (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    transfer_number VARCHAR(64) NOT NULL,
    source_warehouse_id VARCHAR(36) NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    destination_warehouse_id VARCHAR(36) NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    status VARCHAR(30) DEFAULT 'DRAFT' NOT NULL, -- DRAFT, REQUESTED, APPROVED, IN_TRANSIT, RECEIVED, CANCELLED
    notes TEXT,
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    shipped_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_stock_transfers_tenant_number UNIQUE (tenant_id, transfer_number),
    CONSTRAINT chk_transfer_diff_warehouses CHECK (source_warehouse_id <> destination_warehouse_id)
);
CREATE INDEX IF NOT EXISTS idx_stock_transfers_tenant ON stock_transfers(tenant_id);

-- 10. Stock Transfer Items
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
CREATE INDEX IF NOT EXISTS idx_stock_transfer_items_tenant ON stock_transfer_items(tenant_id, transfer_id);

-- 11. Shipments (Fulfillment & Logistics)
CREATE TABLE IF NOT EXISTS shipments (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    shipment_number VARCHAR(64) NOT NULL,
    order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id) ON DELETE RESTRICT,
    warehouse_id VARCHAR(36) NOT NULL REFERENCES warehouses(id) ON DELETE RESTRICT,
    carrier_code VARCHAR(50) NOT NULL, -- AMANA, DHL, FEDEX, LOCAL_COURIER
    carrier_service VARCHAR(100),
    tracking_number VARCHAR(100),
    status VARCHAR(30) DEFAULT 'CREATED' NOT NULL, -- CREATED, PICKING, PACKED, SHIPPED, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED, FAILED, RETURNED, CANCELLED
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
CREATE INDEX IF NOT EXISTS idx_shipments_tenant ON shipments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_shipments_order ON shipments(tenant_id, order_id);
CREATE INDEX IF NOT EXISTS idx_shipments_tracking ON shipments(tenant_id, carrier_code, tracking_number);

-- 12. Shipment Items
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
CREATE INDEX IF NOT EXISTS idx_shipment_items_tenant ON shipment_items(tenant_id, shipment_id);

-- 13. Shipment Tracking Events (Normalized Event Timeline)
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
CREATE INDEX IF NOT EXISTS idx_tracking_events_tenant ON shipment_tracking_events(tenant_id, shipment_id, event_timestamp);

-- 14. Delivery Proofs
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
CREATE INDEX IF NOT EXISTS idx_delivery_proofs_tenant ON delivery_proofs(tenant_id);

-- 15. Customer Support Tickets
CREATE TABLE IF NOT EXISTS support_tickets (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    ticket_number VARCHAR(64) NOT NULL,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
    contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    order_id VARCHAR(36) REFERENCES sales_orders(id) ON DELETE SET NULL,
    priority VARCHAR(20) DEFAULT 'MEDIUM' NOT NULL, -- LOW, MEDIUM, HIGH, URGENT
    category VARCHAR(50) DEFAULT 'GENERAL' NOT NULL, -- SHIPPING_DELAY, DAMAGED_GOODS, WARRANTY_CLAIM, BILLING, GENERAL
    status VARCHAR(30) DEFAULT 'OPEN' NOT NULL, -- OPEN, IN_PROGRESS, PENDING_CUSTOMER, RESOLVED, CLOSED
    subject VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    assigned_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_support_tickets_tenant_number UNIQUE (tenant_id, ticket_number)
);
CREATE INDEX IF NOT EXISTS idx_support_tickets_tenant ON support_tickets(tenant_id);
CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets(tenant_id, status);

-- 16. Support Ticket Messages
CREATE TABLE IF NOT EXISTS ticket_messages (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    ticket_id VARCHAR(36) NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
    sender_type VARCHAR(20) NOT NULL, -- CUSTOMER, AGENT, SYSTEM
    sender_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    message_text TEXT NOT NULL,
    attachments_json JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticket_messages_tenant ON ticket_messages(tenant_id, ticket_id);

-- 17. Warranty Claims
CREATE TABLE IF NOT EXISTS warranty_claims (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    claim_number VARCHAR(64) NOT NULL,
    order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id) ON DELETE RESTRICT,
    order_item_id VARCHAR(36) NOT NULL REFERENCES order_items(id) ON DELETE RESTRICT,
    ticket_id VARCHAR(36) REFERENCES support_tickets(id) ON DELETE SET NULL,
    sku VARCHAR(100) NOT NULL,
    serial_number VARCHAR(100),
    status VARCHAR(30) DEFAULT 'SUBMITTED' NOT NULL, -- SUBMITTED, VALIDATED, REJECTED, REPLACEMENT_ISSUED, REFUNDED
    warranty_valid_until TIMESTAMPTZ NOT NULL,
    claim_reason TEXT NOT NULL,
    inspection_notes TEXT,
    resolved_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_warranty_claims_tenant_number UNIQUE (tenant_id, claim_number)
);
CREATE INDEX IF NOT EXISTS idx_warranty_claims_tenant ON warranty_claims(tenant_id);

-- 18. Return Authorizations (RMA)
CREATE TABLE IF NOT EXISTS return_authorizations (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    rma_number VARCHAR(64) NOT NULL,
    order_id VARCHAR(36) NOT NULL REFERENCES sales_orders(id) ON DELETE RESTRICT,
    ticket_id VARCHAR(36) REFERENCES support_tickets(id) ON DELETE SET NULL,
    status VARCHAR(30) DEFAULT 'REQUESTED' NOT NULL, -- REQUESTED, AUTHORIZED, RECEIVED, INSPECTED, RESTOCKED, REJECTED, CANCELLED
    reason TEXT NOT NULL,
    requested_action VARCHAR(30) DEFAULT 'REFUND' NOT NULL, -- REFUND, REPLACEMENT, STORE_CREDIT
    inspection_outcome VARCHAR(30), -- RESTOCK, QUARANTINE, SCRAP, REJECT
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
CREATE INDEX IF NOT EXISTS idx_rma_tenant ON return_authorizations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rma_order ON return_authorizations(tenant_id, order_id);

-- 19. Return Authorization Items
CREATE TABLE IF NOT EXISTS return_items (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    rma_id VARCHAR(36) NOT NULL REFERENCES return_authorizations(id) ON DELETE CASCADE,
    order_item_id VARCHAR(36) NOT NULL REFERENCES order_items(id) ON DELETE RESTRICT,
    sku VARCHAR(100) NOT NULL,
    quantity_requested INTEGER NOT NULL,
    quantity_received INTEGER DEFAULT 0 NOT NULL,
    condition VARCHAR(50), -- UNOPENED, OPENED_LIKE_NEW, DAMAGED, DEFECTIVE
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chk_return_qty_requested CHECK (quantity_requested > 0),
    CONSTRAINT chk_return_qty_received CHECK (quantity_received >= 0)
);
CREATE INDEX IF NOT EXISTS idx_return_items_tenant ON return_items(tenant_id, rma_id);

-- 20. Appointments & Bookings (Service, Delivery, Consultations)
CREATE TABLE IF NOT EXISTS appointments (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    booking_number VARCHAR(64) NOT NULL,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE SET NULL,
    contact_id VARCHAR(36) REFERENCES contacts(id) ON DELETE SET NULL,
    order_id VARCHAR(36) REFERENCES sales_orders(id) ON DELETE SET NULL,
    service_type VARCHAR(50) NOT NULL, -- SALES_DEMO, ON_SITE_INSTALLATION, HARDWARE_SUPPORT, DELIVERY_SLOT
    status VARCHAR(30) DEFAULT 'REQUESTED' NOT NULL, -- REQUESTED, CONFIRMED, IN_PROGRESS, COMPLETED, CANCELLED, RESCHEDULED
    staff_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    location_type VARCHAR(30) DEFAULT 'VIDEO_CALL' NOT NULL, -- VIDEO_CALL, ON_SITE, PHONE
    location_details VARCHAR(255),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_appointments_tenant_number UNIQUE (tenant_id, booking_number),
    CONSTRAINT chk_appointment_times CHECK (end_time > start_time)
);
CREATE INDEX IF NOT EXISTS idx_appointments_tenant ON appointments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_appointments_staff_schedule ON appointments(tenant_id, staff_user_id, start_time, end_time);

-- =============================================================================
-- ROW LEVEL SECURITY (RLS) FOR ALL 20 STEP 06 TABLES
-- =============================================================================

ALTER TABLE suppliers ENABLE ROW LEVEL SECURITY;
ALTER TABLE suppliers FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_suppliers ON suppliers
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE supplier_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE supplier_products FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_supplier_products ON supplier_products
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE rfqs ENABLE ROW LEVEL SECURITY;
ALTER TABLE rfqs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_rfqs ON rfqs
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE rfq_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE rfq_items FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_rfq_items ON rfq_items
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_orders FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_purchase_orders ON purchase_orders
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE purchase_order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE purchase_order_items FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_purchase_order_items ON purchase_order_items
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE goods_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE goods_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_goods_receipts ON goods_receipts
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE goods_receipt_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE goods_receipt_items FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_goods_receipt_items ON goods_receipt_items
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE stock_transfers ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_transfers FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_stock_transfers ON stock_transfers
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE stock_transfer_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_transfer_items FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_stock_transfer_items ON stock_transfer_items
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE shipments ENABLE ROW LEVEL SECURITY;
ALTER TABLE shipments FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_shipments ON shipments
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE shipment_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE shipment_items FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_shipment_items ON shipment_items
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE shipment_tracking_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE shipment_tracking_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_shipment_tracking_events ON shipment_tracking_events
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE delivery_proofs ENABLE ROW LEVEL SECURITY;
ALTER TABLE delivery_proofs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_delivery_proofs ON delivery_proofs
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE support_tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE support_tickets FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_support_tickets ON support_tickets
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE ticket_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE ticket_messages FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_ticket_messages ON ticket_messages
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE warranty_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE warranty_claims FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_warranty_claims ON warranty_claims
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE return_authorizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE return_authorizations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_return_authorizations ON return_authorizations
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE return_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE return_items FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_return_items ON return_items
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_appointments ON appointments
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));

-- Permissions grants for application user
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sales_app_user;
