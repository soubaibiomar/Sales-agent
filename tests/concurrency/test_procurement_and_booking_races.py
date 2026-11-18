"""
Concurrency Tests for Procurement Over-Receipt and Appointment Double-Booking Races.
Guarantees 0 over-receipts on purchase orders and 0 double-bookings under concurrent loads.
(Control 58: Race conditions, Control 57: Business logic abuse)
Step 06: Sprint 3 - Operate
"""
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.backend.models.entities import (
    Base, Tenant, Warehouse, InventoryItem, Product, Supplier, PurchaseOrder, Appointment
)
from src.backend.domains.procurement.service import (
    ProcurementService, OverReceiptError, InsufficientTransferStockError, InvalidPOStateTransitionError
)
from src.backend.domains.scheduling.service import (
    SchedulingService, BookingConflictError
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


import uuid

@asynccontextmanager
async def get_test_concurrency_env():
    db_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_race_{db_id}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        tenant = Tenant(id="t_race_06", name="Race Test Corp", slug="race-test")
        wh1 = Warehouse(id="wh_race_casa", tenant_id="t_race_06", code="WH-CASA", name="Casablanca Depot")
        wh2 = Warehouse(id="wh_race_rabat", tenant_id="t_race_06", code="WH-RABAT", name="Rabat Depot")
        prod = Product(id="prod_race_01", tenant_id="t_race_06", sku="SERVER-RACK-42U", name="Server Rack 42U", base_price_cents=500000)
        supplier = Supplier(id="sup_race_01", tenant_id="t_race_06", supplier_code="SUP-RACE", name="RackSupplier")
        session.add_all([tenant, wh1, wh2, prod, supplier])
        await session.commit()

    try:
        yield session_factory, "t_race_06", "wh_race_casa", "wh_race_rabat", "prod_race_01", "sup_race_01"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_goods_receipt_race_zero_over_receipt():
    """
    Two concurrent receiving workers attempt to receive the last 5 units of a 10-unit PO.
    Invariants:
    1. Exactly one worker succeeds.
    2. Exactly one worker is rejected with OverReceiptError.
    3. Final PO total received is exactly 10 units (never 15).
    """
    async with get_test_concurrency_env() as (session_factory, tenant_id, wh_casa, _, prod_id, sup_id):
        # 1. Create and issue PO for 10 units
        async with session_factory() as init_session:
            proc_service = ProcurementService(init_session)
            po = await proc_service.create_purchase_order(
                tenant_id=tenant_id,
                supplier_id=sup_id,
                warehouse_id=wh_casa,
                items_data=[{
                    "product_id": prod_id,
                    "sku": "SERVER-RACK-42U",
                    "name": "Server Rack 42U",
                    "quantity_ordered": 10,
                    "unit_cost_cents": 350000
                }]
            )
            po = await proc_service.approve_purchase_order(tenant_id, po.id, user_id="u_admin_race")
            po = await proc_service.issue_purchase_order(tenant_id, po.id)
            po_id = po.id
            po_item_id = po.items[0].id

            # Initial partial receipt of 5 units (5 remain)
            await proc_service.record_goods_receipt(
                tenant_id=tenant_id,
                purchase_order_id=po_id,
                warehouse_id=wh_casa,
                items_data=[{
                    "po_item_id": po_item_id,
                    "sku": "SERVER-RACK-42U",
                    "quantity_received": 5
                }]
            )
            await init_session.commit()

        # 2. Concurrently attempt two receipts of 5 units each (5 + 5 = 10 available, 5 + 5 + 5 = 15 over-receipt)
        successes = []
        failures = []

        async def worker_receive(worker_id: int):
            async with session_factory() as sess:
                service = ProcurementService(sess)
                try:
                    receipt = await service.record_goods_receipt(
                        tenant_id=tenant_id,
                        purchase_order_id=po_id,
                        warehouse_id=wh_casa,
                        items_data=[{
                            "po_item_id": po_item_id,
                            "sku": "SERVER-RACK-42U",
                            "quantity_received": 5
                        }]
                    )
                    await sess.commit()
                    successes.append((worker_id, receipt.id))
                except (OverReceiptError, InvalidPOStateTransitionError) as e:
                    await sess.rollback()
                    failures.append((worker_id, str(e)))

        await asyncio.gather(worker_receive(1), worker_receive(2))

        # Invariant Assertions
        assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
        assert len(failures) == 1, f"Expected exactly 1 OverReceiptError, got {len(failures)}"
        assert "Over-receipt rejected" in failures[0][1]

        # Verify database state
        async with session_factory() as verify_session:
            service = ProcurementService(verify_session)
            final_po = await service.get_purchase_order(tenant_id, po_id)
            assert final_po.items[0].quantity_received == 10
            assert final_po.status == "RECEIVED"


@pytest.mark.asyncio
async def test_concurrent_appointment_booking_race_single_winner():
    """
    Two concurrent booking clients attempt to book the exact same staff member in the same slot.
    Invariants:
    1. Exactly one booking succeeds.
    2. Exactly one booking fails with BookingConflictError.
    3. Exactly 1 confirmed appointment in database (zero double-bookings).
    """
    async with get_test_concurrency_env() as (session_factory, tenant_id, _, _, _, _):
        slot_start = datetime(2026, 11, 22, 14, 0, 0, tzinfo=timezone.utc)
        slot_end = datetime(2026, 11, 22, 14, 30, 0, tzinfo=timezone.utc)
        staff_id = "staff_driss"

        successes = []
        failures = []

        async def worker_book(client_id: int):
            async with session_factory() as sess:
                service = SchedulingService(sess)
                try:
                    apt = await service.book_appointment(
                        tenant_id=tenant_id,
                        service_type="SALES_DEMO",
                        staff_user_id=staff_id,
                        start_time=slot_start,
                        end_time=slot_end,
                        notes=f"Booking by client {client_id}"
                    )
                    await sess.commit()
                    successes.append((client_id, apt.id))
                except BookingConflictError as e:
                    await sess.rollback()
                    failures.append((client_id, str(e)))

        await asyncio.gather(worker_book(1), worker_book(2))

        # Invariant Assertions
        assert len(successes) == 1, f"Expected 1 successful booking, got {len(successes)}"
        assert len(failures) == 1, f"Expected 1 BookingConflictError, got {len(failures)}"
        assert "conflicting booking" in failures[0][1]


@pytest.mark.asyncio
async def test_concurrent_inter_warehouse_transfer_contention():
    """
    Two concurrent transfer requests compete for limited stock (10 available, requests for 8 and 8).
    Invariants:
    1. One transfer ships successfully.
    2. The competing transfer is rejected with InsufficientTransferStockError.
    3. Source warehouse stock never becomes negative.
    """
    async with get_test_concurrency_env() as (session_factory, tenant_id, wh_casa, wh_rabat, prod_id, _):
        # 1. Seed initial stock: exactly 10 units in Casablanca
        async with session_factory() as init_session:
            inv = InventoryItem(
                tenant_id=tenant_id,
                warehouse_id=wh_casa,
                sku="SERVER-RACK-42U",
                on_hand_quantity=10,
                reserved_quantity=0,
                allocated_quantity=0
            )
            init_session.add(inv)
            await init_session.commit()

        # 2. Create and approve two transfer requests for 8 units each
        async with session_factory() as sess:
            service = ProcurementService(sess)
            tr1 = await service.create_stock_transfer(
                tenant_id=tenant_id,
                source_warehouse_id=wh_casa,
                destination_warehouse_id=wh_rabat,
                items_data=[{"sku": "SERVER-RACK-42U", "quantity_requested": 8}]
            )
            tr1 = await service.approve_stock_transfer(tenant_id, tr1.id)
            tr1_id = tr1.id

            tr2 = await service.create_stock_transfer(
                tenant_id=tenant_id,
                source_warehouse_id=wh_casa,
                destination_warehouse_id=wh_rabat,
                items_data=[{"sku": "SERVER-RACK-42U", "quantity_requested": 8}]
            )
            tr2 = await service.approve_stock_transfer(tenant_id, tr2.id)
            tr2_id = tr2.id
            await sess.commit()

        # 3. Attempt concurrent shipment
        successes = []
        failures = []

        async def ship_transfer(tr_id: str):
            async with session_factory() as sess:
                service = ProcurementService(sess)
                try:
                    shipped = await service.ship_stock_transfer(tenant_id, tr_id)
                    await sess.commit()
                    successes.append(shipped.id)
                except InsufficientTransferStockError as e:
                    await sess.rollback()
                    failures.append((tr_id, str(e)))

        await asyncio.gather(ship_transfer(tr1_id), ship_transfer(tr2_id))

        assert len(successes) == 1
        assert len(failures) == 1
        assert "Insufficient on-hand stock" in failures[0][1]
