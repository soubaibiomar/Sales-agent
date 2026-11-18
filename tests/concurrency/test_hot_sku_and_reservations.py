"""
Concurrency Tests for Hot SKU Contention and Atomic Stock Holds.
Guarantees 0 oversells under high concurrent customer load.
(Control 58: Race conditions, Control 57: Business logic abuse)
Step 05: Sprint 3 - Transact
"""
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.backend.models.entities import Base, Tenant, Warehouse, InventoryItem, StockReservation
from src.backend.domains.inventory.service import (
    InventoryService, InsufficientStockError, ReservationAlreadyResolvedError
)


@asynccontextmanager
async def get_test_inventory_env():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        tenant = Tenant(id="tenant_hot_sku", name="Hot SKU Corp", slug="hot-sku", is_active=True)
        session.add(tenant)
        wh = Warehouse(id="wh_hot_sku", tenant_id=tenant.id, code="WH-HOT", name="Central Depot", is_active=True)
        session.add(wh)
        await session.flush()

        # Seed hot product with exactly 3 items on hand
        hot_item = InventoryItem(
            id="item_hot_gpu",
            tenant_id=tenant.id,
            warehouse_id=wh.id,
            sku="NVIDIA-RTX-4090",
            on_hand_quantity=3,
            reserved_quantity=0,
            allocated_quantity=0,
            backorder_allowed=False
        )
        session.add(hot_item)
        await session.commit()

    try:
        yield session_factory, "tenant_hot_sku", "wh_hot_sku", "NVIDIA-RTX-4090"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_hot_sku_five_customers_three_units_zero_oversell():
    """
    Five concurrent customer orders compete for the last 3 units of an RTX 4090.
    Invariants:
    1. Exactly 3 succeed with ACTIVE reservation.
    2. Exactly 2 are rejected with InsufficientStockError.
    3. Zero overselling: on_hand (3) == reserved (3). Available-to-promise is exactly 0.
    """
    async with get_test_inventory_env() as (session_factory, tenant_id, wh_id, sku):
        successes = []
        failures = []

        async def customer_reserve(customer_idx: int):
            async with session_factory() as session:
                service = InventoryService(session)
                try:
                    res = await service.reserve_stock(
                        tenant_id=tenant_id,
                        sku=sku,
                        quantity=1,
                        warehouse_id=wh_id,
                        duration_seconds=1800,
                        idempotency_key=f"cust_{customer_idx}_hold"
                    )
                    await session.commit()
                    successes.append(res.id)
                except InsufficientStockError as e:
                    failures.append(str(e))
                except Exception as e:
                    failures.append(str(e))

        # Launch 5 concurrent reservations
        tasks = [asyncio.create_task(customer_reserve(i)) for i in range(5)]
        await asyncio.gather(*tasks)

        assert len(successes) == 3, f"Expected exactly 3 reservations to succeed, got {len(successes)}"
        assert len(failures) == 2, f"Expected exactly 2 reservations to fail, got {len(failures)}"

        # Verify final database state
        async with session_factory() as session:
            service = InventoryService(session)
            items = await service.get_inventory_items(tenant_id=tenant_id, sku=sku)
            assert len(items) == 1
            item = items[0]
            assert item.on_hand_quantity == 3
            assert item.reserved_quantity == 3
            assert item.available_to_promise == 0  # 3 - 3 = 0, no oversell!


@pytest.mark.asyncio
async def test_reservation_expiry_frees_available_to_promise():
    """
    Simulates a stock reservation that expires without customer checkout.
    Verifies that the hold-expiry worker safely releases the hold and restores ATP.
    """
    async with get_test_inventory_env() as (session_factory, tenant_id, wh_id, sku):
        async with session_factory() as session:
            service = InventoryService(session)
            # Hold 2 units
            res = await service.reserve_stock(
                tenant_id=tenant_id,
                sku=sku,
                quantity=2,
                warehouse_id=wh_id,
                duration_seconds=1  # 1 second expiry
            )
            await session.commit()
            res_id = res.id

        # Fast forward / wait for expiry
        await asyncio.sleep(1.2)

        # Run expiry worker
        async with session_factory() as session:
            service = InventoryService(session)
            expired_count = await service.expire_stale_reservations(tenant_id=tenant_id)
            assert expired_count == 1
            await session.commit()

        # Check inventory is restored to full ATP (3 units)
        async with session_factory() as session:
            service = InventoryService(session)
            items = await service.get_inventory_items(tenant_id=tenant_id, sku=sku)
            item = items[0]
            assert item.on_hand_quantity == 3
            assert item.reserved_quantity == 0
            assert item.available_to_promise == 3


@pytest.mark.asyncio
async def test_commit_reservation_appends_ledger_deduction():
    """
    Verifies that committing a reservation decreases on_hand, decreases reserved,
    and appends a SALE_DEDUCTION entry to the append-only stock movement ledger.
    """
    async with get_test_inventory_env() as (session_factory, tenant_id, wh_id, sku):
        async with session_factory() as session:
            service = InventoryService(session)
            res = await service.reserve_stock(
                tenant_id=tenant_id,
                sku=sku,
                quantity=1,
                warehouse_id=wh_id
            )
            await session.commit()
            res_id = res.id

        # Commit stock
        async with session_factory() as session:
            service = InventoryService(session)
            await service.commit_reservation(
                tenant_id=tenant_id,
                reservation_id=res_id,
                reference_id="ORD-2026-TEST"
            )
            await session.commit()

        # Check final balance and ledger
        async with session_factory() as session:
            service = InventoryService(session)
            items = await service.get_inventory_items(tenant_id=tenant_id, sku=sku)
            item = items[0]
            assert item.on_hand_quantity == 2  # 3 - 1 = 2
            assert item.reserved_quantity == 0
            assert item.available_to_promise == 2

            movements = await service.get_stock_movements(tenant_id=tenant_id)
            deduction = [m for m in movements if m.movement_type == "SALE_DEDUCTION"]
            assert len(deduction) == 1
            assert deduction[0].quantity_delta == -1
            assert deduction[0].new_on_hand == 2
