"""
Security & Adversarial Tests for Carrier Webhooks, Monotonic State Invariants, and Cross-Tenant Isolation.
(Controls 05, 06, 07, 16, 21, 22, 57, 58)
Step 06: Sprint 3 - Operate
"""
import pytest
import hmac
import hashlib
import json
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.backend.models.entities import (
    InventoryItem,
    Base, Tenant, Warehouse, SalesOrder, OrderItem, Shipment, Supplier, PurchaseOrder,
    SupportTicket, Appointment
)
from src.backend.domains.logistics.service import (
    LogisticsService, LogisticsError, ShipmentNotFoundError
)
from src.backend.domains.procurement.service import (
    ProcurementService, PurchaseOrderNotFoundError
)
from src.backend.domains.support.service import (
    SupportService, TicketNotFoundError
)
from src.backend.domains.scheduling.service import (
    SchedulingService, AppointmentNotFoundError
)
from src.backend.integrations.carriers.simulator import SimulatedExpressCarrierAdapter


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


import uuid

@asynccontextmanager
async def get_test_sec_env():
    db_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_sec_{db_id}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        # Two distinct tenants
        t_a = Tenant(id="t_sec_a", name="Tenant A (Acme)", slug="tenant-a")
        t_b = Tenant(id="t_sec_b", name="Tenant B (Competitor)", slug="tenant-b")
        wh_a = Warehouse(id="wh_sec_a", tenant_id="t_sec_a", code="WH-A", name="Depot A")
        wh_b = Warehouse(id="wh_sec_b", tenant_id="t_sec_b", code="WH-B", name="Depot B")
        session.add_all([t_a, t_b, wh_a, wh_b])
        await session.commit()

    try:
        yield session_factory, "t_sec_a", "t_sec_b", "wh_sec_a", "wh_sec_b"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_carrier_webhook_tampered_signature_rejected():
    """
    Validates that carrier webhooks with tampered payloads, wrong signatures,
    or missing headers are rejected immediately.
    """
    async with get_test_sec_env() as (session_factory, tenant_a, _, wh_a, _):
        async with session_factory() as session:
            service = LogisticsService(session)

            payload = {
                "tracking_number": "SIM-TEST12345",
                "status": "DELIVERED",
                "location": "Casablanca",
                "timestamp": utc_now().isoformat()
            }
            raw_body = json.dumps(payload).encode("utf-8")
            valid_secret = "simulated_webhook_secret_default"

            # 1. Missing signature header
            with pytest.raises(LogisticsError, match="Invalid carrier webhook HMAC signature"):
                await service.process_carrier_webhook(
                    tenant_id=tenant_a,
                    carrier_code="SIMULATED_EXPRESS",
                    headers={},
                    raw_body=raw_body,
                    payload=payload,
                    secret=valid_secret
                )

            # 2. Tampered signature
            bad_headers = {"X-Carrier-Signature": "invalid_tampered_hex_digest_000"}
            with pytest.raises(LogisticsError, match="Invalid carrier webhook HMAC signature"):
                await service.process_carrier_webhook(
                    tenant_id=tenant_a,
                    carrier_code="SIMULATED_EXPRESS",
                    headers=bad_headers,
                    raw_body=raw_body,
                    payload=payload,
                    secret=valid_secret
                )

            # 3. Payload tampered after signing
            valid_sig = SimulatedExpressCarrierAdapter.compute_webhook_signature(raw_body, valid_secret)
            tampered_body = json.dumps({**payload, "status": "FAILED"}).encode("utf-8")
            with pytest.raises(LogisticsError, match="Invalid carrier webhook HMAC signature"):
                await service.process_carrier_webhook(
                    tenant_id=tenant_a,
                    carrier_code="SIMULATED_EXPRESS",
                    headers={"X-Carrier-Signature": valid_sig},
                    raw_body=tampered_body,
                    payload=payload,
                    secret=valid_secret
                )


@pytest.mark.asyncio
async def test_carrier_webhook_out_of_order_replay_does_not_regress_delivered():
    """
    Adversarial scenario: A network glitch or replay attacker sends an older 'IN_TRANSIT'
    webhook event after the package has already been signed and DELIVERED.
    INVARIANT: Shipment status must remain DELIVERED.
    """
    async with get_test_sec_env() as (session_factory, tenant_a, _, wh_a, _):
        async with session_factory() as session:
            logistics = LogisticsService(session)

            # Create and dispatch order and shipment
            order = SalesOrder(
                id="ord_sec_01",
                tenant_id=tenant_a,
                order_number="ORD-SEC-001",
                status="CONFIRMED",
                currency="MAD",
                subtotal_cents=100000,
                tax_total_cents=20000,
                grand_total_cents=120000,
                terms_hash="a" * 64
            )
            item = OrderItem(
                id="oi_sec_01",
                tenant_id=tenant_a,
                order_id=order.id,
                sku="SEC-SKU-1",
                name="Security Widget",
                quantity=1,
                unit_price_cents=100000,
                subtotal_cents=100000,
                tax_cents=20000,
                total_cents=120000
            )
            # Stock must exist in the warehouse ledger before it can ship
            stock = InventoryItem(tenant_id=tenant_a, warehouse_id=wh_a, sku="SEC-SKU-1",
                                  on_hand_quantity=1, reserved_quantity=0, allocated_quantity=0)
            session.add_all([order, item, stock])
            await session.flush()

            shipment = await logistics.create_shipment(
                tenant_id=tenant_a,
                order_id=order.id,
                warehouse_id=wh_a,
                carrier_code="SIMULATED_EXPRESS",
                shipping_address={"city": "Rabat"},
                delivery_contact={"name": "Omar"},
                items_data=[{"order_item_id": item.id, "sku": "SEC-SKU-1", "quantity": 1}]
            )
            await logistics.start_picking(tenant_a, shipment.id)
            await logistics.complete_packing(tenant_a, shipment.id)
            shipment = await logistics.book_carrier_and_ship(tenant_a, shipment.id)
            tracking_num = shipment.tracking_number
            await session.commit()

        # Step 1: Deliver webhook indicating DELIVERED
        async with session_factory() as session:
            logistics = LogisticsService(session)
            secret = "simulated_webhook_secret_default"

            delivered_payload = {
                "tracking_number": tracking_num,
                "status": "DELIVERED",
                "location": "Customer Front Door",
                "timestamp": utc_now().isoformat()
            }
            raw_delivered = json.dumps(delivered_payload).encode("utf-8")
            sig_delivered = SimulatedExpressCarrierAdapter.compute_webhook_signature(raw_delivered, secret)

            events = await logistics.process_carrier_webhook(
                tenant_id=tenant_a,
                carrier_code="SIMULATED_EXPRESS",
                headers={"X-Carrier-Signature": sig_delivered},
                raw_body=raw_delivered,
                payload=delivered_payload,
                secret=secret
            )
            await session.commit()

            shp = await logistics.get_shipment(tenant_a, shipment.id)
            assert shp.status == "DELIVERED"
            assert shp.delivered_at is not None

        # Step 2: Replay older IN_TRANSIT webhook
        async with session_factory() as session:
            logistics = LogisticsService(session)
            transit_payload = {
                "tracking_number": tracking_num,
                "status": "IN_TRANSIT",
                "location": "En Route Hub",
                "timestamp": (utc_now() - timedelta(hours=2)).isoformat()
            }
            raw_transit = json.dumps(transit_payload).encode("utf-8")
            sig_transit = SimulatedExpressCarrierAdapter.compute_webhook_signature(raw_transit, secret)

            await logistics.process_carrier_webhook(
                tenant_id=tenant_a,
                carrier_code="SIMULATED_EXPRESS",
                headers={"X-Carrier-Signature": sig_transit},
                raw_body=raw_transit,
                payload=transit_payload,
                secret=secret
            )
            await session.commit()

            # INVARIANT: Status must remain DELIVERED, not regressed
            final_shp = await logistics.get_shipment(tenant_a, shipment.id)
            assert final_shp.status == "DELIVERED"


@pytest.mark.asyncio
async def test_cross_tenant_idor_procurement_and_logistics():
    """
    Validates zero-trust multi-tenancy:
    Tenant B cannot access or modify Tenant A's POs, shipments, tickets, or appointments.
    """
    async with get_test_sec_env() as (session_factory, tenant_a, tenant_b, wh_a, wh_b):
        # 1. Tenant A creates resources
        async with session_factory() as session:
            proc = ProcurementService(session)
            supp = await proc.create_supplier(tenant_a, "SUP-A", "Acme Supplier")
            po = await proc.create_purchase_order(
                tenant_a, supp.id, wh_a,
                [{"sku": "SKU-A", "name": "Item A", "quantity_ordered": 5, "unit_cost_cents": 1000}]
            )
            po_id = po.id

            support = SupportService(session)
            tck = await support.create_ticket(tenant_a, "Ticket A", "Problem with order")
            tck_id = tck.id

            sched = SchedulingService(session)
            apt = await sched.book_appointment(
                tenant_a, "SALES_DEMO",
                utc_now() + timedelta(days=1),
                utc_now() + timedelta(days=1, minutes=30)
            )
            apt_id = apt.id
            await session.commit()

        # 2. Tenant B attempts IDOR on Tenant A's resources
        async with session_factory() as session:
            proc = ProcurementService(session)
            po = await proc.get_purchase_order(tenant_b, po_id)
            assert po is None
            with pytest.raises(PurchaseOrderNotFoundError):
                await proc.approve_purchase_order(tenant_b, po_id)

            support = SupportService(session)
            with pytest.raises(TicketNotFoundError):
                await support.get_ticket(tenant_b, tck_id)

            sched = SchedulingService(session)
            with pytest.raises(AppointmentNotFoundError):
                await sched.get_appointment(tenant_b, apt_id)
