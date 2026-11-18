"""
Contract Tests for Sales Orders, Payment Intents, Confirmation, Invoices, and Credit Notes APIs.
Step 05: Sprint 3 - Transact
"""
import pytest
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from datetime import timedelta, datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.backend.main import app
from src.backend.models.entities import (
    Base, Tenant, User, Role, UserRole, Account, Product, Quote, QuoteItem,
    Warehouse, InventoryItem
)
from src.backend.core.security import SecurityService
from src.backend.core.database import get_db_session

TEST_DB = "sqlite+aiosqlite:///:memory:"


@asynccontextmanager
async def get_orders_api_env():
    engine = create_async_engine(
        TEST_DB,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        t = Tenant(id="t_ord_01", name="Order Test Tenant", slug="order-test-tenant")
        session.add(t)

        user = User(
            id="u_rep_ord",
            tenant_id="t_ord_01",
            email="rep@ordercorp.com",
            hashed_password=SecurityService.hash_password("RepPass123!"),
            full_name="Sales Executive",
            is_active=True,
            is_verified=True
        )
        session.add(user)

        r_admin = Role(id="r_admin_ord", name="tenant_admin", description="Tenant Admin", is_privileged=True)
        session.add(r_admin)
        session.add(UserRole(tenant_id="t_ord_01", user_id=user.id, role_id=r_admin.id))

        account = Account(id="acc_ord_01", tenant_id="t_ord_01", name="Acme Logistics")
        session.add(account)

        prod = Product(
            id="p_ord_01",
            tenant_id="t_ord_01",
            sku="HW-SRV-01",
            name="Enterprise Rack Server",
            is_active=True
        )
        session.add(prod)

        wh = Warehouse(
            id="wh_ord_01",
            tenant_id="t_ord_01",
            code="WH-MAIN",
            name="Main Fulfillment Center",
            is_active=True
        )
        session.add(wh)

        inv_item = InventoryItem(
            id="inv_ord_01",
            tenant_id="t_ord_01",
            warehouse_id="wh_ord_01",
            product_id="p_ord_01",
            sku="HW-SRV-01",
            on_hand_quantity=10,
            reserved_quantity=0,
            allocated_quantity=0,
            backorder_allowed=False
        )
        session.add(inv_item)

        valid_until = datetime.now(timezone.utc) + timedelta(days=14)
        quote = Quote(
            id="q_ord_01",
            tenant_id="t_ord_01",
            quote_number="QUO-202611-00001",
            account_id="acc_ord_01",
            currency="USD",
            status="ISSUED",
            version=1,
            subtotal_cents=100000,
            discount_total_cents=0,
            tax_total_cents=20000,
            grand_total_cents=120000,
            terms_hash="qterms123"*7 + "q",
            valid_until=valid_until
        )
        session.add(quote)

        q_item = QuoteItem(
            id="qi_ord_01",
            tenant_id="t_ord_01",
            quote_id=quote.id,
            product_id="p_ord_01",
            sku_snapshot="HW-SRV-01",
            name_snapshot="Enterprise Rack Server",
            quantity=2,
            uom_snapshot="UNIT",
            unit_price_cents=50000,
            subtotal_cents=100000,
            tax_cents=20000,
            total_cents=120000
        )
        session.add(q_item)
        await session.commit()

    token_str, _, _ = SecurityService.create_access_token(
        user_id="u_rep_ord",
        tenant_id="t_ord_01",
        email="rep@corp.com",
        roles=["tenant_admin"],
        permissions=[
            "orders:manage", "orders:read", "quotes:create", "quotes:read", "quotes:approve",
            "inventory:manage", "inventory:read", "invoices:manage", "invoices:read"
        ],
        mfa_verified=True
    )

    async def override_db():
        async with session_factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_db

    import src.backend.core.auth_middleware as mw
    import src.backend.core.database as db_mod
    orig_factory = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = session_factory
    mw.AsyncSessionLocal = session_factory

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, token_str, "t_ord_01", "q_ord_01"
    finally:
        db_mod.AsyncSessionLocal = orig_factory
        mw.AsyncSessionLocal = orig_factory
        app.dependency_overrides.pop(get_db_session, None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_full_order_payment_and_invoice_api_lifecycle():
    """
    End-to-End API Test:
    1. Accept quote and create order via POST /api/v1/orders/from-quote
    2. Verify stock reservation is active (ATP reduced from 10 to 8)
    3. Create payment intent via POST /api/v1/payments/intents
    4. Confirm payment in sandbox via POST /api/v1/payments/intents/{id}/confirm
    5. Verify order transitions to PAID, stock reservation committed (on-hand 8, reserved 0)
    6. Issue invoice via POST /api/v1/invoices/from-order
    7. Issue credit note via POST /api/v1/invoices/credit-note
    """
    async with get_orders_api_env() as (client, token, tenant_id, quote_id):
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Accept quote to create order
        accept_resp = await client.post(
            "/api/v1/orders/from-quote",
            headers=headers,
            json={
                "quote_id": quote_id,
                "expected_quote_version": 1,
                "shipping_address_json": '{"city": "Casablanca"}',
                "idempotency_key": "test_idem_ord_01"
            }
        )
        assert accept_resp.status_code == 201, accept_resp.text
        order_data = accept_resp.json()
        assert order_data["status"] == "PENDING_PAYMENT"
        assert order_data["payment_status"] == "UNPAID"
        assert order_data["grand_total_cents"] == 120000
        order_id = order_data["id"]

        # 2. Check inventory ATP: on_hand=10, reserved=2, ATP=8
        inv_resp = await client.get("/api/v1/inventory/items", headers=headers)
        assert inv_resp.status_code == 200
        inv_items = inv_resp.json()
        assert inv_items[0]["available_to_promise"] == 8
        assert inv_items[0]["reserved_quantity"] == 2

        # 3. Create payment intent
        pi_resp = await client.post(
            "/api/v1/payments/intents",
            headers=headers,
            json={
                "order_id": order_id,
                "provider": "STRIPE_SANDBOX",
                "idempotency_key": f"pi_idem_{order_id}"
            }
        )
        assert pi_resp.status_code == 201, pi_resp.text
        pi_data = pi_resp.json()
        assert pi_data["status"] == "REQUIRES_PAYMENT_METHOD"
        assert pi_data["amount_cents"] == 120000
        intent_id = pi_data["id"]

        # 4. Confirm payment with valid test card
        confirm_resp = await client.post(
            f"/api/v1/payments/intents/{intent_id}/confirm",
            headers=headers,
            json={
                "payment_method_type": "CARD",
                "payment_method_token": "tok_sandbox_valid_card"
            }
        )
        assert confirm_resp.status_code == 200, confirm_resp.text
        tx_data = confirm_resp.json()
        assert tx_data["status"] == "SUCCESS"
        assert tx_data["transaction_type"] == "CAPTURE"

        # 5. Verify order is now PAID
        get_order_resp = await client.get(f"/api/v1/orders/{order_id}", headers=headers)
        assert get_order_resp.status_code == 200
        paid_order = get_order_resp.json()
        assert paid_order["status"] == "PAID"
        assert paid_order["payment_status"] == "PAID"

        # Verify stock was committed (on_hand 8, reserved 0, ATP 8)
        inv_resp2 = await client.get("/api/v1/inventory/items", headers=headers)
        inv_items2 = inv_resp2.json()
        assert inv_items2[0]["on_hand_quantity"] == 8
        assert inv_items2[0]["reserved_quantity"] == 0
        assert inv_items2[0]["available_to_promise"] == 8

        # 6. Issue compliance invoice
        inv_create_resp = await client.post(
            "/api/v1/invoices/from-order",
            headers=headers,
            json={"order_id": order_id, "due_days": 30}
        )
        assert inv_create_resp.status_code == 201, inv_create_resp.text
        inv_data = inv_create_resp.json()
        assert inv_data["status"] == "PAID"
        assert inv_data["invoice_number"].startswith("INV-")
        assert len(inv_data["invoice_hash"]) == 64
        invoice_id = inv_data["id"]

        # 7. Issue credit note against invoice
        cn_resp = await client.post(
            "/api/v1/invoices/credit-note",
            headers=headers,
            json={
                "original_invoice_id": invoice_id,
                "reason": "Commercial goodwill discount",
                "amount_cents": 10000
            }
        )
        assert cn_resp.status_code == 201, cn_resp.text
        cn_data = cn_resp.json()
        assert cn_data["invoice_number"].startswith("CN-")
        assert cn_data["grand_total_cents"] == -10000
        assert cn_data["correction_of_invoice_id"] == invoice_id
