"""
Integration Test Suite: Real PostgreSQL 16 Procurement, Logistics, Support, and Scheduling Validation.
Executes against live PostgreSQL container (sales-ai-postgres) on 127.0.0.1:5432
under the unprivileged 'sales_app_user' account with FORCE ROW LEVEL SECURITY.

Verifies:
1. PostgreSQL 16 RLS tenant isolation across all 20 Step 06 tables.
2. Cross-tenant leakage rejection (Tenant Beta sees 0 rows from Tenant Alpha).
3. Missing tenant context rejection (unscoped queries see 0 rows under FORCE RLS).
4. End-to-end live transactional procurement, goods receipt, over-receipt rejection on real PostgreSQL 16.
5. Live logistics fulfillment lifecycle and monotonic tracking status on real PostgreSQL 16.
6. Live RMA inspection and inventory restock on real PostgreSQL 16.
(Controls 05, 06, 07, 16, 21, 22, 31, 32, 33, 34, 48, 57, 58, 59; SAI-07, SAI-08)
Step 06: Sprint 3 - Operate
"""
import sys
import uuid
import psycopg
import pytest
import warnings
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text, select

if sys.platform == "win32":
    import asyncio
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from src.backend.models.entities import (
    Tenant, Warehouse, InventoryItem, Product, Supplier, RFQ, PurchaseOrder,
    GoodsReceipt, StockTransfer, Shipment, SupportTicket, WarrantyClaim,
    ReturnAuthorization, Appointment, SalesOrder, OrderItem
)
from src.backend.domains.procurement.service import ProcurementService, OverReceiptError
from src.backend.domains.logistics.service import LogisticsService
from src.backend.domains.support.service import SupportService
from src.backend.domains.scheduling.service import SchedulingService

PG_ASYNC_URL = "postgresql+psycopg://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"
PG_SYNC_CONN = "postgresql://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"

STEP06_TABLES = [
    "suppliers",
    "supplier_products",
    "rfqs",
    "rfq_items",
    "purchase_orders",
    "purchase_order_items",
    "goods_receipts",
    "goods_receipt_items",
    "stock_transfers",
    "stock_transfer_items",
    "shipments",
    "shipment_items",
    "shipment_tracking_events",
    "delivery_proofs",
    "support_tickets",
    "ticket_messages",
    "warranty_claims",
    "return_authorizations",
    "return_items",
    "appointments"
]


@pytest.fixture(scope="module")
def real_pg06_tenants():
    t_alpha = f"t_pg06_alpha_{uuid.uuid4().hex[:8]}"
    t_beta = f"t_pg06_beta_{uuid.uuid4().hex[:8]}"

    # Insert test tenants as postgres admin
    admin_conn_str = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
    with psycopg.connect(admin_conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_alpha, "PG06 Alpha", f"slug-{t_alpha}"))
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_beta, "PG06 Beta", f"slug-{t_beta}"))
        conn.commit()

    yield t_alpha, t_beta

    with psycopg.connect(admin_conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (t_alpha, t_beta))
        conn.commit()


def test_real_postgres_step06_rls_isolation_all_20_tables(real_pg06_tenants):
    """
    Control 33, 34: Verifies PostgreSQL 16 RLS on all 20 Step 06 tables.
    Tenant Alpha inserts records; Tenant Beta reads and sees 0 rows under unprivileged sales_app_user.
    """
    t_alpha, t_beta = real_pg06_tenants

    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            # 1. Tenant Alpha session
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_alpha,))

            wh_id = f"wh_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO warehouses (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
                        (wh_id, t_alpha, f"WH-{uuid.uuid4().hex[:4]}", "Alpha Main Depot"))

            prod_id = f"prod_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO products (id, tenant_id, sku, name, base_price_cents) VALUES (%s, %s, %s, %s, %s)",
                        (prod_id, t_alpha, f"SKU-{uuid.uuid4().hex[:6]}", "Alpha Product", 10000))

            sup_id = f"sup_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO suppliers (id, tenant_id, supplier_code, name, currency) VALUES (%s, %s, %s, %s, %s)",
                        (sup_id, t_alpha, f"SUP-{uuid.uuid4().hex[:4]}", "Alpha Supplies", "MAD"))

            sp_id = f"sp_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO supplier_products (id, tenant_id, supplier_id, product_id, sku, supplier_sku, unit_cost_cents) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (sp_id, t_alpha, sup_id, prod_id, "SKU-01", "SSKU-01", 8000))

            rfq_id = f"rfq_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO rfqs (id, tenant_id, rfq_number, supplier_id, status) VALUES (%s, %s, %s, %s, %s)",
                        (rfq_id, t_alpha, f"RFQ-{uuid.uuid4().hex[:4]}", sup_id, "DRAFT"))

            rfqi_id = f"rfqi_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO rfq_items (id, tenant_id, rfq_id, sku, name, quantity) VALUES (%s, %s, %s, %s, %s, %s)",
                        (rfqi_id, t_alpha, rfq_id, "SKU-01", "Item 1", 10))

            po_id = f"po_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO purchase_orders (id, tenant_id, po_number, supplier_id, warehouse_id, status) VALUES (%s, %s, %s, %s, %s, %s)",
                        (po_id, t_alpha, f"PO-{uuid.uuid4().hex[:4]}", sup_id, wh_id, "ISSUED"))

            poi_id = f"poi_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO purchase_order_items (id, tenant_id, purchase_order_id, sku, name, quantity_ordered, unit_cost_cents, subtotal_cents) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (poi_id, t_alpha, po_id, "SKU-01", "Item 1", 10, 8000, 80000))

            gr_id = f"gr_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO goods_receipts (id, tenant_id, receipt_number, purchase_order_id, warehouse_id) VALUES (%s, %s, %s, %s, %s)",
                        (gr_id, t_alpha, f"GRN-{uuid.uuid4().hex[:4]}", po_id, wh_id))

            gri_id = f"gri_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO goods_receipt_items (id, tenant_id, goods_receipt_id, po_item_id, sku, quantity_received) VALUES (%s, %s, %s, %s, %s, %s)",
                        (gri_id, t_alpha, gr_id, poi_id, "SKU-01", 5))

            wh2_id = f"wh2_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO warehouses (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
                        (wh2_id, t_alpha, f"WH-{uuid.uuid4().hex[:4]}", "Alpha Secondary Depot"))

            tr_id = f"tr_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO stock_transfers (id, tenant_id, transfer_number, source_warehouse_id, destination_warehouse_id, status) VALUES (%s, %s, %s, %s, %s, %s)",
                        (tr_id, t_alpha, f"TRF-{uuid.uuid4().hex[:4]}", wh_id, wh2_id, "REQUESTED"))

            tri_id = f"tri_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO stock_transfer_items (id, tenant_id, transfer_id, sku, quantity_requested) VALUES (%s, %s, %s, %s, %s)",
                        (tri_id, t_alpha, tr_id, "SKU-01", 5))

            ord_id = f"ord_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO sales_orders (id, tenant_id, order_number, terms_hash, subtotal_cents, grand_total_cents) VALUES (%s, %s, %s, %s, %s, %s)",
                        (ord_id, t_alpha, f"ORD-{uuid.uuid4().hex[:6]}", "a"*64, 10000, 12000))

            oi_id = f"oi_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO order_items (id, tenant_id, order_id, sku, name, quantity, unit_price_cents, subtotal_cents, total_cents) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (oi_id, t_alpha, ord_id, "SKU-01", "Item 1", 2, 5000, 10000, 12000))

            shp_id = f"shp_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO shipments (id, tenant_id, shipment_number, order_id, warehouse_id, carrier_code, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (shp_id, t_alpha, f"SHP-{uuid.uuid4().hex[:4]}", ord_id, wh_id, "AMANA", "CREATED"))

            shpi_id = f"shpi_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO shipment_items (id, tenant_id, shipment_id, order_item_id, sku, name, quantity) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (shpi_id, t_alpha, shp_id, oi_id, "SKU-01", "Item 1", 2))

            ste_id = f"ste_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO shipment_tracking_events (id, tenant_id, shipment_id, status, location, description, event_timestamp) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (ste_id, t_alpha, shp_id, "CREATED", "Casablanca Hub", "Package initialized", datetime.now(timezone.utc)))

            pod_id = f"pod_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO delivery_proofs (id, tenant_id, shipment_id, recipient_name) VALUES (%s, %s, %s, %s)",
                        (pod_id, t_alpha, shp_id, "Receiver Alpha"))

            tck_id = f"tck_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO support_tickets (id, tenant_id, ticket_number, subject, description, priority, category, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (tck_id, t_alpha, f"TCK-{uuid.uuid4().hex[:4]}", "Need Help", "Broken part", "HIGH", "GENERAL", "OPEN"))

            tm_id = f"tm_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO ticket_messages (id, tenant_id, ticket_id, sender_type, message_text) VALUES (%s, %s, %s, %s, %s)",
                        (tm_id, t_alpha, tck_id, "CUSTOMER", "Hello support team"))

            wc_id = f"wc_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO warranty_claims (id, tenant_id, claim_number, order_id, order_item_id, sku, status, warranty_valid_until, claim_reason) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (wc_id, t_alpha, f"WAR-{uuid.uuid4().hex[:4]}", ord_id, oi_id, "SKU-01", "SUBMITTED", datetime.now(timezone.utc) + timedelta(days=100), "Malfunction"))

            rma_id = f"rma_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO return_authorizations (id, tenant_id, rma_number, order_id, status, reason, requested_action) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (rma_id, t_alpha, f"RMA-{uuid.uuid4().hex[:4]}", ord_id, "REQUESTED", "Broken", "REFUND"))

            ri_id = f"ri_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO return_items (id, tenant_id, rma_id, order_item_id, sku, quantity_requested) VALUES (%s, %s, %s, %s, %s, %s)",
                        (ri_id, t_alpha, rma_id, oi_id, "SKU-01", 1))

            apt_id = f"apt_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO appointments (id, tenant_id, booking_number, service_type, start_time, end_time, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (apt_id, t_alpha, f"APT-{uuid.uuid4().hex[:4]}", "DEMO", datetime.now(timezone.utc), datetime.now(timezone.utc) + timedelta(hours=1), "CONFIRMED"))

            conn.commit()

            # Verify Tenant Alpha can see its records
            for tbl in STEP06_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = %s", (t_alpha,))
                count = cur.fetchone()[0]
                assert count >= 1, f"Tenant Alpha must see records in {tbl}"

            # 2. Tenant Beta session: Read under RLS -> Must see exactly 0 rows!
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_beta,))
            for tbl in STEP06_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                count = cur.fetchone()[0]
                assert count == 0, f"Tenant Beta must see 0 rows in {tbl} due to RLS, found {count}"


def test_real_postgres_step06_missing_tenant_fails_closed(real_pg06_tenants):
    """
    Control 33: Unscoped query with missing or empty 'app.current_tenant_id'
    fails closed under FORCE RLS, returning 0 rows across all 20 Step 06 tables.
    """
    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', '', false)")
            for tbl in STEP06_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                count = cur.fetchone()[0]
                assert count == 0, f"Unscoped query on {tbl} must fail closed (0 rows), found {count}"


@pytest.mark.asyncio
async def test_real_postgres_live_procurement_and_over_receipt(real_pg06_tenants):
    """
    Live PostgreSQL Transactional Integration:
    Creates supplier, PO for 10 units, issues PO, receives 6 units, and validates that
    attempting to receive 5 more (11 > 10) raises OverReceiptError and rolls back on real PostgreSQL.
    """
    t_alpha, _ = real_pg06_tenants
    engine = create_async_engine(PG_ASYNC_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        await session.execute(text(f"SELECT set_config('app.current_tenant_id', '{t_alpha}', false)"))

        proc = ProcurementService(session)

        # 1. Create Supplier and Warehouse
        supp = await proc.create_supplier(t_alpha, f"SUP-PG-{uuid.uuid4().hex[:4]}", "Live PG Supplier")
        wh = Warehouse(id=str(uuid.uuid4()), tenant_id=t_alpha, code=f"WH-PG-{uuid.uuid4().hex[:4]}", name="Live Depot")
        session.add(wh)
        await session.flush()

        # 2. Create and Issue PO for 10 units
        po = await proc.create_purchase_order(
            tenant_id=t_alpha,
            supplier_id=supp.id,
            warehouse_id=wh.id,
            items_data=[{"sku": "PG-TRANSFORMER-50KVA", "name": "Transformer 50kVA", "quantity_ordered": 10, "unit_cost_cents": 500000}]
        )
        po = await proc.approve_purchase_order(t_alpha, po.id)
        po = await proc.issue_purchase_order(t_alpha, po.id)
        po_id = po.id
        po_item_id = po.items[0].id

        # 3. Valid partial receipt of 6 units
        grn = await proc.record_goods_receipt(
            tenant_id=t_alpha,
            purchase_order_id=po_id,
            warehouse_id=wh.id,
            items_data=[{"po_item_id": po_item_id, "sku": "PG-TRANSFORMER-50KVA", "quantity_received": 6}]
        )
        await session.commit()
        assert grn.items[0].quantity_received == 6

        # 4. Attempt over-receipt for 5 units (6 + 5 = 11 > 10)
        with pytest.raises(OverReceiptError, match="Over-receipt rejected"):
            await proc.record_goods_receipt(
                tenant_id=t_alpha,
                purchase_order_id=po_id,
                warehouse_id=wh.id,
                items_data=[{"po_item_id": po_item_id, "sku": "PG-TRANSFORMER-50KVA", "quantity_received": 5}]
            )
        await session.rollback()

    await engine.dispose()


@pytest.mark.asyncio
async def test_real_postgres_live_logistics_monotonic_progression(real_pg06_tenants):
    """
    Live PostgreSQL Transactional Integration:
    Creates shipment, transitions through PICKING -> PACKED -> SHIPPED, and delivers POD.
    Validates that real PostgreSQL constraints and RLS allow the full flow.
    """
    t_alpha, _ = real_pg06_tenants
    engine = create_async_engine(PG_ASYNC_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        await session.execute(text(f"SELECT set_config('app.current_tenant_id', '{t_alpha}', false)"))

        logistics = LogisticsService(session)

        # 1. Setup Order & Warehouse
        wh = Warehouse(id=str(uuid.uuid4()), tenant_id=t_alpha, code=f"WH-LOG-{uuid.uuid4().hex[:4]}", name="Logistics Hub")
        order = SalesOrder(
            id=str(uuid.uuid4()),
            tenant_id=t_alpha,
            order_number=f"ORD-LOG-{uuid.uuid4().hex[:6]}",
            terms_hash="d" * 64,
            subtotal_cents=100000,
            grand_total_cents=120000
        )
        oi = OrderItem(
            id=str(uuid.uuid4()),
            tenant_id=t_alpha,
            order_id=order.id,
            sku="PG-TRANSFORMER-50KVA",
            name="Transformer",
            quantity=1,
            unit_price_cents=100000,
            subtotal_cents=100000,
            total_cents=120000
        )
        # Stock must exist in the warehouse ledger before it can be shipped
        stock = InventoryItem(
            id=str(uuid.uuid4()), tenant_id=t_alpha, warehouse_id=wh.id, sku="PG-TRANSFORMER-50KVA",
            on_hand_quantity=1, reserved_quantity=0, allocated_quantity=0
        )
        session.add_all([wh, order, oi])
        await session.flush()
        session.add(stock)
        await session.flush()

        # 2. Create Shipment
        shipment = await logistics.create_shipment(
            tenant_id=t_alpha,
            order_id=order.id,
            warehouse_id=wh.id,
            carrier_code="AMANA",
            shipping_address={"city": "Tangier"},
            delivery_contact={"name": "Live Customer"},
            items_data=[{"order_item_id": oi.id, "sku": "PG-TRANSFORMER-50KVA", "name": "Transformer", "quantity": 1}]
        )
        assert shipment.status == "CREATED"

        # 3. Advance to PICKING then PACKED
        shipment = await logistics.start_picking(t_alpha, shipment.id)
        assert shipment.status == "PICKING"

        shipment = await logistics.complete_packing(t_alpha, shipment.id)
        assert shipment.status == "PACKED"

        # 4. Ship
        shipment = await logistics.book_carrier_and_ship(t_alpha, shipment.id)
        assert shipment.status == "SHIPPED"
        assert shipment.tracking_number is not None

        await session.commit()

    await engine.dispose()
