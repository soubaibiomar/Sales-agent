"""
Unit Tests for Procurement, Multi-Warehouse Operations, Logistics, Support & Scheduling.
Covers over-receipt rejection, monotonic carrier updates, warranty limits,
inspection stock mutations, and appointment conflict guards.
(Controls 05, 06, 07, 16, 21, 22, 57, 58)
Step 06: Sprint 3 - Operate
"""
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.backend.models.entities import (
    Base, Tenant, Warehouse, InventoryItem, Product, SalesOrder, OrderItem,
    Supplier, PurchaseOrder, StockTransfer, Shipment, ReturnAuthorization
)
from src.backend.domains.procurement.service import (
    ProcurementService, OverReceiptError, InsufficientTransferStockError
)
from src.backend.domains.logistics.service import (
    LogisticsService, SHIPMENT_STATUS_RANKS
)
from src.backend.domains.support.service import (
    SupportService, WarrantyExpiredError, InvalidReturnStateError
)
from src.backend.domains.scheduling.service import (
    SchedulingService, BookingConflictError
)
from src.backend.integrations.carriers.simulator import SimulatedExpressCarrierAdapter
from src.backend.integrations.carriers.amana import AmanaCarrierAdapter


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@asynccontextmanager
async def get_test_unit_env():
    db_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_{db_id}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        # Seed base tenant and warehouse
        tenant = Tenant(id="t_unit_06", name="Unit Test Tenant", slug="unit-test-tenant")
        wh1 = Warehouse(id="wh_casa", tenant_id="t_unit_06", code="CASA-HUB", name="Casablanca Hub")
        wh2 = Warehouse(id="wh_tng", tenant_id="t_unit_06", code="TNG-HUB", name="Tangier Hub")
        prod = Product(
            id="prod_01",
            tenant_id="t_unit_06",
            sku="LAPTOP-PRO-16",
            name="Professional Laptop 16-inch",
            base_price_cents=1500000
        )
        session.add_all([tenant, wh1, wh2, prod])
        await session.commit()
        yield session

    await engine.dispose()


# -----------------------------------------------------------------------------
# 1. PROCUREMENT & OVER-RECEIPT REJECTION TESTS
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_procurement_po_lifecycle_and_over_receipt_rejection():
    async with get_test_unit_env() as unit_session:
        service = ProcurementService(unit_session)
        tenant_id = "t_unit_06"

        # 1. Create supplier
        supplier = await service.create_supplier(
            tenant_id=tenant_id,
            supplier_code="SUP-TECH",
            name="TechDistro SARL",
            payment_terms="NET_30"
        )
        assert supplier.id is not None
        assert supplier.supplier_code == "SUP-TECH"

        # 2. Create purchase order with 10 units ordered
        po = await service.create_purchase_order(
            tenant_id=tenant_id,
            supplier_id=supplier.id,
            warehouse_id="wh_casa",
            items_data=[{
                "product_id": "prod_01",
                "sku": "LAPTOP-PRO-16",
                "name": "Professional Laptop 16-inch",
                "quantity_ordered": 10,
                "unit_cost_cents": 1000000
            }]
        )
        assert po.status == "DRAFT"
        assert po.grand_total_cents == 12000000  # 10 * 10,000 + 20% tax

        # 3. Approve and issue PO
        po = await service.approve_purchase_order(tenant_id, po.id, user_id="u_admin_01")
        assert po.status == "APPROVED"
        po = await service.issue_purchase_order(tenant_id, po.id)
        assert po.status == "ISSUED"

        po_item_id = po.items[0].id

        # 4. Partial goods receipt of 6 units
        receipt1 = await service.record_goods_receipt(
            tenant_id=tenant_id,
            purchase_order_id=po.id,
            warehouse_id="wh_casa",
            items_data=[{
                "po_item_id": po_item_id,
                "sku": "LAPTOP-PRO-16",
                "quantity_received": 6
            }]
        )
        assert receipt1.id is not None
        assert po.items[0].quantity_received == 6
        assert po.status == "PARTIALLY_RECEIVED"

        # 5. Over-receipt attempt: receiving 5 more when only 4 remain (6 + 5 = 11 > 10)
        # INVARIANT: Must strictly reject with OverReceiptError
        with pytest.raises(OverReceiptError, match="Over-receipt rejected"):
            await service.record_goods_receipt(
                tenant_id=tenant_id,
                purchase_order_id=po.id,
                warehouse_id="wh_casa",
                items_data=[{
                    "po_item_id": po_item_id,
                    "sku": "LAPTOP-PRO-16",
                    "quantity_received": 5
                }]
            )

        # 6. Valid exact final receipt of remaining 4 units
        receipt2 = await service.record_goods_receipt(
            tenant_id=tenant_id,
            purchase_order_id=po.id,
            warehouse_id="wh_casa",
            items_data=[{
                "po_item_id": po_item_id,
                "sku": "LAPTOP-PRO-16",
                "quantity_received": 4
            }]
        )
        assert receipt2.id is not None
        assert po.items[0].quantity_received == 10
        assert po.status == "RECEIVED"


@pytest.mark.asyncio
async def test_inter_warehouse_transfer_ledger_balance():
    async with get_test_unit_env() as unit_session:
        service = ProcurementService(unit_session)
        tenant_id = "t_unit_06"

        # Seed source warehouse inventory (15 units in Casablanca)
        inv_casa = InventoryItem(
            tenant_id=tenant_id,
            warehouse_id="wh_casa",
            sku="LAPTOP-PRO-16",
            on_hand_quantity=15,
            reserved_quantity=0,
            allocated_quantity=0
        )
        unit_session.add(inv_casa)
        await unit_session.flush()

        # 1. Create transfer of 10 units CASA -> TNG
        transfer = await service.create_stock_transfer(
            tenant_id=tenant_id,
            source_warehouse_id="wh_casa",
            destination_warehouse_id="wh_tng",
            items_data=[{"sku": "LAPTOP-PRO-16", "quantity_requested": 10}]
        )
        assert transfer.status == "REQUESTED"

        # 2. Approve and ship
        transfer = await service.approve_stock_transfer(tenant_id, transfer.id)
        transfer = await service.ship_stock_transfer(tenant_id, transfer.id)
        assert transfer.status == "IN_TRANSIT"
        assert inv_casa.on_hand_quantity == 5  # 15 - 10

        # 3. Receive at destination
        transfer = await service.receive_stock_transfer(tenant_id, transfer.id)
        assert transfer.status == "RECEIVED"

        # Verify destination warehouse inventory
        inv_tng = await service.inventory_service.get_or_create_inventory_item(
            tenant_id=tenant_id, warehouse_id="wh_tng", sku="LAPTOP-PRO-16"
        )
        assert inv_tng.on_hand_quantity == 10


# -----------------------------------------------------------------------------
# 2. LOGISTICS MONOTONIC STATE TRANSITION TESTS
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_logistics_monotonic_status_progression():
    async with get_test_unit_env() as unit_session:
        service = LogisticsService(unit_session)
        tenant_id = "t_unit_06"

        # Seed sales order
        order = SalesOrder(
            id="ord_log_01",
            tenant_id=tenant_id,
            order_number="ORD-20261118-0001",
            status="CONFIRMED",
            currency="MAD",
            subtotal_cents=1500000,
            tax_total_cents=300000,
            grand_total_cents=1800000,
            terms_hash="hash_log_01"
        )
        o_item = OrderItem(
            id="oi_log_01",
            tenant_id=tenant_id,
            order_id=order.id,
            sku="LAPTOP-PRO-16",
            name="Laptop Pro",
            quantity=1,
            unit_price_cents=1500000,
            subtotal_cents=1500000,
            tax_cents=300000,
            total_cents=1800000
        )
        unit_session.add_all([order, o_item])
        await unit_session.flush()

        # 1. Create shipment
        shipment = await service.create_shipment(
            tenant_id=tenant_id,
            order_id=order.id,
            warehouse_id="wh_casa",
            carrier_code="SIMULATED_EXPRESS",
            shipping_address={"city": "Casablanca", "street": "Bd d'Anfa"},
            delivery_contact={"name": "Yassine Mansouri", "phone": "+212600112233"},
            items_data=[{"order_item_id": o_item.id, "sku": "LAPTOP-PRO-16", "quantity": 1}]
        )
        assert shipment.status == "CREATED"

        # 2. Pick and pack
        await service.start_picking(tenant_id, shipment.id)
        assert shipment.status == "PICKING"
        await service.complete_packing(tenant_id, shipment.id)
        assert shipment.status == "PACKED"

        # 3. Ship with carrier booking
        await service.book_carrier_and_ship(tenant_id, shipment.id)
        assert shipment.status == "SHIPPED"
        assert shipment.tracking_number is not None

        # 4. Monotonic progression: SHIPPED -> IN_TRANSIT -> DELIVERED
        service._apply_monotonic_status(shipment, "IN_TRANSIT")
        assert shipment.status == "IN_TRANSIT"

        service._apply_monotonic_status(shipment, "DELIVERED")
        assert shipment.status == "DELIVERED"

        # 5. INVARIANT: Late out-of-order callback must NOT regress DELIVERED to IN_TRANSIT or SHIPPED
        regressed = service._apply_monotonic_status(shipment, "IN_TRANSIT")
        assert regressed is False
        assert shipment.status == "DELIVERED"

        regressed2 = service._apply_monotonic_status(shipment, "SHIPPED")
        assert regressed2 is False
        assert shipment.status == "DELIVERED"


# -----------------------------------------------------------------------------
# 3. SUPPORT, WARRANTY & RMA RETURN INSPECTION TESTS
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_support_warranty_expiry_and_rma_inspection():
    async with get_test_unit_env() as unit_session:
        service = SupportService(unit_session)
        tenant_id = "t_unit_06"

        # Create fresh order
        recent_order = SalesOrder(
            id="ord_sup_rec",
            tenant_id=tenant_id,
            order_number="ORD-20261118-REC",
            status="DELIVERED",
            created_at=utc_now() - timedelta(days=30),  # 30 days old
            currency="MAD",
            subtotal_cents=100000,
            tax_total_cents=20000,
            grand_total_cents=120000,
            terms_hash="hash_rec_01"
        )
        oi_rec = OrderItem(
            id="oi_sup_rec",
            tenant_id=tenant_id,
            order_id=recent_order.id,
            sku="LAPTOP-PRO-16",
            name="Laptop Pro",
            quantity=1,
            unit_price_cents=100000,
            subtotal_cents=100000,
            tax_cents=20000,
            total_cents=120000
        )

        # Create expired order (> 365 days old)
        old_order = SalesOrder(
            id="ord_sup_old",
            tenant_id=tenant_id,
            order_number="ORD-20241010-OLD",
            status="DELIVERED",
            created_at=utc_now() - timedelta(days=400),  # 400 days old
            currency="MAD",
            subtotal_cents=100000,
            tax_total_cents=20000,
            grand_total_cents=120000,
            terms_hash="hash_old_01"
        )
        oi_old = OrderItem(
            id="oi_sup_old",
            tenant_id=tenant_id,
            order_id=old_order.id,
            sku="LAPTOP-PRO-16",
            name="Laptop Pro",
            quantity=1,
            unit_price_cents=100000,
            subtotal_cents=100000,
            tax_cents=20000,
            total_cents=120000
        )
        unit_session.add_all([recent_order, oi_rec, old_order, oi_old])
        await unit_session.flush()

        # 1. Valid warranty claim on recent order
        claim = await service.create_warranty_claim(
            tenant_id=tenant_id,
            order_id=recent_order.id,
            order_item_id=oi_rec.id,
            sku="LAPTOP-PRO-16",
            claim_reason="Screen flickering intermittently"
        )
        assert claim.status == "SUBMITTED"

        # 2. Expired warranty claim (> 365 days) must be rejected
        with pytest.raises(WarrantyExpiredError, match="expired"):
            await service.create_warranty_claim(
                tenant_id=tenant_id,
                order_id=old_order.id,
                order_item_id=oi_old.id,
                sku="LAPTOP-PRO-16",
                claim_reason="Battery degradation"
            )

        # 3. RMA Return Inspection with RESTOCK outcome
        rma = await service.request_rma(
            tenant_id=tenant_id,
            order_id=recent_order.id,
            reason="Ordered wrong specifications",
            requested_action="REFUND",
            destination_warehouse_id="wh_casa",
            items_data=[{"order_item_id": oi_rec.id, "sku": "LAPTOP-PRO-16", "quantity_requested": 1}]
        )
        assert rma.status == "REQUESTED"

        await service.authorize_rma(tenant_id, rma.id)
        assert rma.status == "AUTHORIZED"

        await service.receive_return_items(
            tenant_id, rma.id, [{"return_item_id": rma.items[0].id, "quantity_received": 1}]
        )
        assert rma.status == "RECEIVED"

        # Settle RMA with RESTOCK: increments destination warehouse stock
        rma = await service.inspect_and_settle_rma(
            tenant_id=tenant_id,
            rma_id=rma.id,
            inspection_outcome="RESTOCK",
            inspection_notes="Unopened retail packaging, verified pristine",
            refund_amount_cents=120000
        )
        assert rma.status == "RESTOCKED"
        assert rma.refund_amount_cents == 120000


# -----------------------------------------------------------------------------
# 4. SCHEDULING CONCURRENCY & DOUBLE-BOOKING CONFLICT TESTS
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scheduling_double_booking_conflict_rejection():
    async with get_test_unit_env() as unit_session:
        service = SchedulingService(unit_session)
        tenant_id = "t_unit_06"
        staff_id = "staff_youssef"

        slot_start = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        slot_end = datetime(2026, 11, 20, 10, 30, 0, tzinfo=timezone.utc)

        # 1. Book first appointment
        apt1 = await service.book_appointment(
            tenant_id=tenant_id,
            service_type="SALES_DEMO",
            staff_user_id=staff_id,
            start_time=slot_start,
            end_time=slot_end,
            notes="Product demonstration for client"
        )
        assert apt1.status == "CONFIRMED"

        # 2. Concurrent overlapping booking attempt for same staff member: [10:15 - 10:45)
        overlap_start = datetime(2026, 11, 20, 10, 15, 0, tzinfo=timezone.utc)
        overlap_end = datetime(2026, 11, 20, 10, 45, 0, tzinfo=timezone.utc)

        # INVARIANT: Must strictly reject with BookingConflictError
        with pytest.raises(BookingConflictError, match="conflicting booking"):
            await service.book_appointment(
                tenant_id=tenant_id,
                service_type="HARDWARE_SUPPORT",
                staff_user_id=staff_id,
                start_time=overlap_start,
                end_time=overlap_end
            )

        # 3. Available slots calculation correctly flags 10:00 - 10:30 as unavailable
        slots = await service.get_available_slots(
            tenant_id=tenant_id,
            target_date=slot_start,
            staff_user_id=staff_id,
            duration_minutes=30
        )
        occupied_slot = next(s for s in slots if "10:00:00" in s["start_time"])
        assert occupied_slot["is_available"] is False

        free_slot = next(s for s in slots if "11:00:00" in s["start_time"])
        assert free_slot["is_available"] is True
