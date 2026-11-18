"""
Contract Tests for Procurement, Logistics, Support, and Scheduling REST APIs.
Tests route handlers, authentication/authorization, payload schemas, and HTTP status codes.
(Controls 05, 06, 07, 16, 21, 22, 33, 34, 48, 57, 58)
Step 06: Sprint 3 - Operate
"""
import pytest
import uuid
import json
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from datetime import timedelta, datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.backend.main import app
from src.backend.models.entities import (
    Base, Tenant, User, Role, UserRole, Warehouse, Product, InventoryItem, SalesOrder, OrderItem
)
from src.backend.core.security import SecurityService
from src.backend.core.database import get_db_session
from src.backend.integrations.carriers.simulator import SimulatedExpressCarrierAdapter


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@asynccontextmanager
async def get_logistics_api_env():
    db_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_api_{db_id}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        t = Tenant(id="t_api_06", name="Contract Test Tenant", slug="contract-test-06")
        session.add(t)

        user = User(
            id="u_api_manager",
            tenant_id="t_api_06",
            email="manager@operations.com",
            hashed_password=SecurityService.hash_password("OperationsPass123!"),
            full_name="Operations Manager",
            is_active=True,
            is_verified=True
        )
        session.add(user)

        r_admin = Role(id="r_admin_06", name="tenant_admin", description="Tenant Admin", is_privileged=True)
        session.add(r_admin)
        session.add(UserRole(tenant_id="t_api_06", user_id=user.id, role_id=r_admin.id))

        wh1 = Warehouse(id="wh_api_casa", tenant_id="t_api_06", code="WH-CASA", name="Casablanca Hub")
        wh2 = Warehouse(id="wh_api_rabat", tenant_id="t_api_06", code="WH-RABAT", name="Rabat Hub")
        prod = Product(id="p_api_01", tenant_id="t_api_06", sku="SOLAR-PANEL-400W", name="Solar Panel 400W", base_price_cents=250000)
        session.add_all([wh1, wh2, prod])

        inv = InventoryItem(
            id="inv_api_01",
            tenant_id="t_api_06",
            warehouse_id=wh1.id,
            product_id=prod.id,
            sku="SOLAR-PANEL-400W",
            on_hand_quantity=50,
            reserved_quantity=0,
            allocated_quantity=0
        )
        session.add(inv)

        order = SalesOrder(
            id="ord_api_01",
            tenant_id="t_api_06",
            order_number="ORD-202611-00099",
            status="CONFIRMED",
            currency="MAD",
            subtotal_cents=250000,
            discount_total_cents=0,
            tax_total_cents=50000,
            grand_total_cents=300000,
            terms_hash="c" * 64
        )
        order_item = OrderItem(
            id="oi_api_01",
            tenant_id="t_api_06",
            order_id=order.id,
            sku="SOLAR-PANEL-400W",
            name="Solar Panel 400W",
            quantity=1,
            unit_price_cents=250000,
            subtotal_cents=250000,
            tax_cents=50000,
            total_cents=300000
        )
        session.add_all([order, order_item])
        await session.commit()

    token_str, _, _ = SecurityService.create_access_token(
        user_id="u_api_manager",
        tenant_id="t_api_06",
        email="manager@operations.com",
        roles=["tenant_admin"],
        permissions=[
            "procurement:manage", "procurement:read",
            "logistics:manage", "logistics:read",
            "support:manage", "support:read",
            "scheduling:manage", "scheduling:read"
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
            yield client, token_str, "t_api_06"
    finally:
        db_mod.AsyncSessionLocal = orig_factory
        mw.AsyncSessionLocal = orig_factory
        app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.asyncio
async def test_procurement_po_and_over_receipt_api():
    """
    Test PO creation, approval, partial receipt, and HTTP 422 over-receipt rejection via REST API.
    """
    async with get_logistics_api_env() as (client, token, tenant_id):
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create Supplier
        sup_resp = await client.post(
            "/api/v1/procurement/suppliers",
            headers=headers,
            json={
                "supplier_code": "SUP-SOLAR",
                "name": "SolarTech Industries",
                "currency": "MAD",
                "email": "contact@solartech.ma"
            }
        )
        assert sup_resp.status_code == 201, sup_resp.text
        supplier_id = sup_resp.json()["id"]

        # 2. Create PO
        po_resp = await client.post(
            "/api/v1/procurement/purchase-orders",
            headers=headers,
            json={
                "supplier_id": supplier_id,
                "warehouse_id": "wh_api_casa",
                "currency": "MAD",
                "items": [{
                    "sku": "SOLAR-PANEL-400W",
                    "name": "Solar Panel 400W",
                    "quantity_ordered": 10,
                    "unit_cost_cents": 180000
                }]
            }
        )
        assert po_resp.status_code == 201, po_resp.text
        po_data = po_resp.json()
        po_id = po_data["id"]
        po_item_id = po_data["items"][0]["id"]
        assert po_data["status"] == "DRAFT"

        # 3. Approve PO
        appr_resp = await client.post(f"/api/v1/procurement/purchase-orders/{po_id}/approve", headers=headers)
        assert appr_resp.status_code == 200, appr_resp.text
        assert appr_resp.json()["status"] == "APPROVED"

        # 4. Issue PO
        issue_resp = await client.post(f"/api/v1/procurement/purchase-orders/{po_id}/issue", headers=headers)
        assert issue_resp.status_code == 200, issue_resp.text
        assert issue_resp.json()["status"] == "ISSUED"

        # 5. Record valid Goods Receipt for 6 units (4 remain)
        gr_resp = await client.post(
            "/api/v1/procurement/goods-receipts",
            headers=headers,
            json={
                "purchase_order_id": po_id,
                "warehouse_id": "wh_api_casa",
                "items": [{
                    "po_item_id": po_item_id,
                    "sku": "SOLAR-PANEL-400W",
                    "quantity_received": 6
                }]
            }
        )
        assert gr_resp.status_code == 201, gr_resp.text
        assert gr_resp.json()["items"][0]["quantity_received"] == 6

        # 6. Attempt Over-Receipt for 5 units (only 4 remain) -> must return HTTP 422
        over_resp = await client.post(
            "/api/v1/procurement/goods-receipts",
            headers=headers,
            json={
                "purchase_order_id": po_id,
                "warehouse_id": "wh_api_casa",
                "items": [{
                    "po_item_id": po_item_id,
                    "sku": "SOLAR-PANEL-400W",
                    "quantity_received": 5
                }]
            }
        )
        assert over_resp.status_code == 422, f"Expected 422 OverReceiptError, got {over_resp.status_code}: {over_resp.text}"
        assert "Over-receipt rejected" in over_resp.json()["detail"]


@pytest.mark.asyncio
async def test_stock_transfers_lifecycle_api():
    """
    Test Inter-Warehouse Transfer creation, approval, dispatch, and receipt.
    """
    async with get_logistics_api_env() as (client, token, tenant_id):
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create Stock Transfer
        tr_resp = await client.post(
            "/api/v1/procurement/transfers",
            headers=headers,
            json={
                "source_warehouse_id": "wh_api_casa",
                "destination_warehouse_id": "wh_api_rabat",
                "items": [{"sku": "SOLAR-PANEL-400W", "quantity_requested": 5}],
                "notes": "Relocating stock to Rabat"
            }
        )
        assert tr_resp.status_code == 201, tr_resp.text
        tr_id = tr_resp.json()["id"]

        # 2. Approve Transfer
        appr_resp = await client.post(f"/api/v1/procurement/transfers/{tr_id}/approve", headers=headers)
        assert appr_resp.status_code == 200, appr_resp.text
        assert appr_resp.json()["status"] == "APPROVED"

        # 3. Ship Transfer
        ship_resp = await client.post(f"/api/v1/procurement/transfers/{tr_id}/ship", headers=headers)
        assert ship_resp.status_code == 200, ship_resp.text
        assert ship_resp.json()["status"] == "IN_TRANSIT"

        # 4. Receive Transfer
        recv_resp = await client.post(f"/api/v1/procurement/transfers/{tr_id}/receive", headers=headers)
        assert recv_resp.status_code == 200, recv_resp.text
        assert recv_resp.json()["status"] == "RECEIVED"


@pytest.mark.asyncio
async def test_logistics_shipment_and_webhook_api():
    """
    Test Shipment creation, pick/pack/ship, carrier webhook with HMAC signature.
    """
    async with get_logistics_api_env() as (client, token, tenant_id):
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create Shipment
        shp_resp = await client.post(
            "/api/v1/logistics/shipments",
            headers=headers,
            json={
                "order_id": "ord_api_01",
                "warehouse_id": "wh_api_casa",
                "carrier_code": "SIMULATED_EXPRESS",
                "shipping_address_json": {"city": "Casablanca", "street": "Bd Roudani 123"},
                "delivery_contact_json": {"name": "Customer Omar", "phone": "+212600000000"},
                "items": [{"order_item_id": "oi_api_01", "sku": "SOLAR-PANEL-400W", "name": "Solar Panel 400W", "quantity": 1}]
            }
        )
        assert shp_resp.status_code == 201, shp_resp.text
        shp_data = shp_resp.json()
        shipment_id = shp_data["id"]
        assert shp_data["status"] == "CREATED"

        # 2. Pick & Pack
        p_resp = await client.post(f"/api/v1/logistics/shipments/{shipment_id}/pick", headers=headers)
        assert p_resp.status_code == 200
        pk_resp = await client.post(f"/api/v1/logistics/shipments/{shipment_id}/pack", headers=headers)
        assert pk_resp.status_code == 200

        # 3. Ship
        s_resp = await client.post(f"/api/v1/logistics/shipments/{shipment_id}/ship", headers=headers)
        assert s_resp.status_code == 200
        tracking_num = s_resp.json()["tracking_number"]
        assert tracking_num is not None

        # 4. Carrier Webhook Delivery
        webhook_payload = {
            "tracking_number": tracking_num,
            "status": "DELIVERED",
            "location": "Casablanca Depot Front Desk",
            "timestamp": utc_now().isoformat()
        }
        raw_body = json.dumps(webhook_payload).encode("utf-8")
        secret = "simulated_webhook_secret_default"
        sig = SimulatedExpressCarrierAdapter.compute_webhook_signature(raw_body, secret)

        wh_resp = await client.post(
            "/api/v1/logistics/webhooks/carrier/SIMULATED_EXPRESS",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Tenant-Id": tenant_id,
                "X-Carrier-Signature": sig,
                "Content-Type": "application/json"
            },
            content=raw_body
        )
        assert wh_resp.status_code == 200, wh_resp.text
        assert len(wh_resp.json()) >= 1

        # 5. Check Shipment is DELIVERED
        get_shp = await client.get(f"/api/v1/logistics/shipments/{shipment_id}", headers=headers)
        assert get_shp.status_code == 200
        assert get_shp.json()["status"] == "DELIVERED"


@pytest.mark.asyncio
async def test_support_ticket_and_rma_api():
    """
    Test Support Ticket creation, messaging, warranty claim, and RMA inspection.
    """
    async with get_logistics_api_env() as (client, token, tenant_id):
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create Ticket
        tck_resp = await client.post(
            "/api/v1/support/tickets",
            headers=headers,
            json={
                "subject": "Panel output 10% lower than spec",
                "description": "Need technical assistance with inverted solar yield.",
                "priority": "HIGH",
                "order_id": "ord_api_01"
            }
        )
        assert tck_resp.status_code == 201, tck_resp.text
        ticket_id = tck_resp.json()["id"]

        # 2. Add Message
        msg_resp = await client.post(
            f"/api/v1/support/tickets/{ticket_id}/messages",
            headers=headers,
            json={
                "sender_type": "AGENT",
                "message_text": "Checking warranty status."
            }
        )
        assert msg_resp.status_code == 201, msg_resp.text

        # 3. Create RMA
        rma_resp = await client.post(
            "/api/v1/support/rmas",
            headers=headers,
            json={
                "order_id": "ord_api_01",
                "ticket_id": ticket_id,
                "reason": "DEFECTIVE",
                "requested_action": "REFUND",
                "items": [{
                    "order_item_id": "oi_api_01",
                    "sku": "SOLAR-PANEL-400W",
                    "quantity_requested": 1,
                    "condition": "OPEN_BOX"
                }]
            }
        )
        assert rma_resp.status_code == 201, rma_resp.text
        rma_id = rma_resp.json()["id"]
        return_item_id = rma_resp.json()["items"][0]["id"]

        # 4. Inspect RMA item (RESTOCK outcome)
        insp_resp = await client.post(
            f"/api/v1/support/rmas/{rma_id}/inspect",
            headers=headers,
            json={
                "inspection_outcome": "RESTOCK",
                "inspection_notes": "Cosmetic packaging damage only, tested cells 100% operational.",
                "quantity_received_map": {return_item_id: 1},
                "refund_amount_cents": 300000
            }
        )
        assert insp_resp.status_code == 200, insp_resp.text
        assert insp_resp.json()["status"] == "INSPECTED"


@pytest.mark.asyncio
async def test_scheduling_appointment_double_booking_api():
    """
    Test appointment booking and HTTP 409 conflict on double-booking.
    """
    async with get_logistics_api_env() as (client, token, tenant_id):
        headers = {"Authorization": f"Bearer {token}"}

        start = (utc_now() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(minutes=45)

        # 1. First booking succeeds
        apt1_resp = await client.post(
            "/api/v1/scheduling/appointments",
            headers=headers,
            json={
                "service_type": "TECHNICAL_CONSULTATION",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "staff_user_id": "u_api_manager",
                "notes": "First client booking"
            }
        )
        assert apt1_resp.status_code == 201, apt1_resp.text

        # 2. Competing booking on the exact same staff member and slot -> HTTP 409
        apt2_resp = await client.post(
            "/api/v1/scheduling/appointments",
            headers=headers,
            json={
                "service_type": "TECHNICAL_CONSULTATION",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "staff_user_id": "u_api_manager",
                "notes": "Conflicting second booking"
            }
        )
        assert apt2_resp.status_code == 409, f"Expected 409 conflict, got {apt2_resp.status_code}: {apt2_resp.text}"
        assert "conflicting booking" in apt2_resp.json()["detail"]
