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
