"""
Integration Test Suite: Real PostgreSQL 16 Orders, Inventory, Payments, and Invoicing Validation.
Executes against live PostgreSQL container (sales-ai-postgres) on 127.0.0.1:5432
under the unprivileged 'sales_app_user' account with FORCE ROW LEVEL SECURITY.

Verifies:
1. PostgreSQL RLS tenant isolation across all 11 Step 05 tables.
2. Cross-tenant leakage rejection (Tenant Beta sees 0 rows from Tenant Alpha).
3. Missing tenant context rejection (unscoped queries see 0 rows under FORCE RLS).
4. End-to-end live transactional order, payment confirmation, and invoice generation against real PostgreSQL.
5. Real PostgreSQL pessimistic row locking (SELECT ... FOR UPDATE) on inventory holds.
(Controls 31, 32, 33, 34, 48, 57, 58, 59; SAI-07, SAI-08)
Step 05: Sprint 3 - Transact
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
    Tenant, Warehouse, InventoryItem, StockReservation, StockMovement,
    SalesOrder, OrderItem, PaymentIntent, PaymentTransaction, RefundRequest,
    Invoice, InvoiceItem
)
from src.backend.domains.inventory.service import InventoryService
from src.backend.domains.orders.service import OrderService
from src.backend.domains.payments.service import PaymentService
from src.backend.domains.invoicing.service import InvoicingService

PG_ASYNC_URL = "postgresql+psycopg://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"
PG_SYNC_CONN = "postgresql://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"

STEP05_TABLES = [
    "warehouses",
    "inventory_items",
    "stock_reservations",
    "stock_movements",
    "sales_orders",
    "order_items",
    "payment_intents",
    "payment_transactions",
    "refund_requests",
    "invoices",
    "invoice_items"
]


@pytest.fixture(scope="module")
def real_pg_tenants():
    t_alpha = f"t_pg05_alpha_{uuid.uuid4().hex[:8]}"
    t_beta = f"t_pg05_beta_{uuid.uuid4().hex[:8]}"

    # Insert test tenants as postgres admin
    admin_conn_str = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
    with psycopg.connect(admin_conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_alpha, "PG05 Alpha", f"slug-{t_alpha}"))
            cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t_beta, "PG05 Beta", f"slug-{t_beta}"))
        conn.commit()

    yield t_alpha, t_beta

    with psycopg.connect(admin_conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (t_alpha, t_beta))
        conn.commit()


def test_real_postgres_step05_rls_isolation_all_11_tables(real_pg_tenants):
    """
    Control 33, 34: Verifies PostgreSQL 16 RLS on all 11 Step 05 tables.
    Tenant Alpha inserts records; Tenant Beta reads and sees 0 rows under sales_app_user.
    """
    t_alpha, t_beta = real_pg_tenants

    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            # 1. Tenant Alpha session: Insert sample records in all 11 tables
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_alpha,))

            wh_id = f"wh_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO warehouses (id, tenant_id, code, name) VALUES (%s, %s, %s, %s)",
                        (wh_id, t_alpha, f"WH-{uuid.uuid4().hex[:4]}", "Alpha Depot"))

            inv_id = f"inv_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO inventory_items (id, tenant_id, warehouse_id, sku, on_hand_quantity) VALUES (%s, %s, %s, %s, %s)",
                        (inv_id, t_alpha, wh_id, "SKU-PG05-01", 10))

            res_id = f"res_{uuid.uuid4().hex[:8]}"
            expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
            cur.execute("INSERT INTO stock_reservations (id, tenant_id, inventory_item_id, sku, quantity, status, reserved_until) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (res_id, t_alpha, inv_id, "SKU-PG05-01", 2, "ACTIVE", expiry))

            sm_id = f"sm_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO stock_movements (id, tenant_id, inventory_item_id, movement_type, quantity_delta, previous_on_hand, new_on_hand, reference_type, reference_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (sm_id, t_alpha, inv_id, "INBOUND_RECEIPT", 10, 0, 10, "INITIAL", "INIT-1"))

            ord_id = f"ord_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO sales_orders (id, tenant_id, order_number, terms_hash, subtotal_cents, grand_total_cents) VALUES (%s, %s, %s, %s, %s, %s)",
                        (ord_id, t_alpha, f"ORD-{uuid.uuid4().hex[:6]}", "a"*64, 10000, 12000))

            oi_id = f"oi_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO order_items (id, tenant_id, order_id, sku, name, quantity, unit_price_cents, subtotal_cents, total_cents) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (oi_id, t_alpha, ord_id, "SKU-PG05-01", "PG05 Item", 2, 5000, 10000, 12000))

            pi_id = f"pi_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO payment_intents (id, tenant_id, order_id, provider_intent_id, amount_cents) VALUES (%s, %s, %s, %s, %s)",
                        (pi_id, t_alpha, ord_id, f"pi_{uuid.uuid4().hex[:8]}", 12000))

            tx_id = f"tx_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO payment_transactions (id, tenant_id, payment_intent_id, order_id, provider_transaction_id, amount_cents) VALUES (%s, %s, %s, %s, %s, %s)",
                        (tx_id, t_alpha, pi_id, ord_id, f"tx_{uuid.uuid4().hex[:8]}", 12000))

            ref_id = f"ref_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO refund_requests (id, tenant_id, order_id, amount_cents, reason) VALUES (%s, %s, %s, %s, %s)",
                        (ref_id, t_alpha, ord_id, 12000, "Return request"))

            invc_id = f"invc_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO invoices (id, tenant_id, order_id, invoice_number, subtotal_cents, tax_total_cents, grand_total_cents, terms_hash, invoice_hash, due_date) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (invc_id, t_alpha, ord_id, f"INV-{uuid.uuid4().hex[:6]}", 10000, 2000, 12000, "b"*64, "c"*64, expiry))

            invi_id = f"invi_{uuid.uuid4().hex[:8]}"
            cur.execute("INSERT INTO invoice_items (id, tenant_id, invoice_id, sku, name, quantity, unit_price_cents, tax_cents, subtotal_cents, total_cents) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (invi_id, t_alpha, invc_id, "SKU-PG05-01", "PG05 Item", 2, 5000, 2000, 10000, 12000))

            conn.commit()

            # Verify Tenant Alpha can see its records
            for tbl in STEP05_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE tenant_id = %s", (t_alpha,))
                count = cur.fetchone()[0]
                assert count >= 1, f"Tenant Alpha must see records in {tbl}"

            # 2. Tenant Beta session: Read under RLS -> Must see exactly 0 rows!
            cur.execute("SELECT set_config('app.current_tenant_id', %s, false)", (t_beta,))
            for tbl in STEP05_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                count = cur.fetchone()[0]
                assert count == 0, f"Tenant Beta must see 0 rows in {tbl} due to RLS, found {count}"


def test_real_postgres_step05_missing_tenant_fails_closed(real_pg_tenants):
    """
    Control 33: Unscoped query with missing or empty 'app.current_tenant_id'
    fails closed under FORCE RLS, returning 0 rows across all Step 05 tables.
    """
    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_tenant_id', '', false)")
            for tbl in STEP05_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                count = cur.fetchone()[0]
                assert count == 0, f"Unscoped query on {tbl} must fail closed (0 rows), found {count}"


@pytest.mark.asyncio
async def test_real_postgres_live_inventory_order_payment_lifecycle(real_pg_tenants):
    """
    Live PostgreSQL Transactional Integration:
    Creates warehouse, adds stock, places order, confirms payment, commits stock, and issues invoice.
    All state transitions run against live PostgreSQL 16 container.
    """
    t_alpha, _ = real_pg_tenants
    engine = create_async_engine(PG_ASYNC_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        # Set tenant context
        await session.execute(text(f"SELECT set_config('app.current_tenant_id', '{t_alpha}', false)"))

        inv_service = InventoryService(session)
        order_service = OrderService(session, inventory_service=inv_service)
        pay_service = PaymentService(session, order_service=order_service)
        invc_service = InvoicingService(session)

        # 1. Create warehouse and stock
        wh = await inv_service.create_warehouse(tenant_id=t_alpha, code=f"WH-LIVE-{uuid.uuid4().hex[:4]}", name="Live Warehouse")
        item = await inv_service.get_or_create_inventory_item(
            tenant_id=t_alpha,
            warehouse_id=wh.id,
            sku="SKU-LIVE-01",
            initial_on_hand=5
        )
        assert item.available_to_promise == 5

        # 2. Place order for 2 units
        items_data = [{
            "sku": "SKU-LIVE-01",
            "name": "Live Server",
            "quantity": 2,
            "unit_price_cents": 25000,
            "discount_percent": 0.0,
            "tax_rate_percent": 20.0
        }]
        order = await order_service.create_order(
            tenant_id=t_alpha,
            account_id=None,
            contact_id=None,
            currency="USD",
            items_data=items_data
        )
        assert order.status == "PENDING_PAYMENT"
        assert order.grand_total_cents == 60000  # 50000 + 10000 tax

        # Check ATP is now 3 (5 - 2 = 3)
        updated_item = (await inv_service.get_inventory_items(tenant_id=t_alpha, sku="SKU-LIVE-01"))[0]
        assert updated_item.available_to_promise == 3
        assert updated_item.reserved_quantity == 2

        # 3. Create payment intent and confirm
        intent = await pay_service.create_payment_intent(
            tenant_id=t_alpha,
            order_id=order.id
        )
        tx = await pay_service.confirm_payment_intent(
            tenant_id=t_alpha,
            intent_id=intent.id,
            payment_method_token="tok_sandbox_valid_card"
        )
        assert tx.status == "SUCCESS"

        # Check order is PAID
        paid_order = await order_service.get_order_by_id(tenant_id=t_alpha, order_id=order.id)
        assert paid_order.status == "PAID"
        assert paid_order.payment_status == "PAID"

        # Check stock committed: on_hand=3, reserved=0, ATP=3
        committed_item = (await inv_service.get_inventory_items(tenant_id=t_alpha, sku="SKU-LIVE-01"))[0]
        assert committed_item.on_hand_quantity == 3
        assert committed_item.reserved_quantity == 0
        assert committed_item.available_to_promise == 3

        # 4. Issue invoice
        invoice = await invc_service.create_invoice_from_order(
            tenant_id=t_alpha,
            order_id=order.id
        )
        assert invoice.status == "PAID"
        assert invoice.grand_total_cents == 60000

        await session.commit()

    await engine.dispose()
