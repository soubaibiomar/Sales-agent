"""
Concurrency Tests for Quote Acceptance, Duplicate Order Prevention, and Optimistic Locking.
(Control 58: Race conditions, Control 57: Business logic abuse)
Step 05: Sprint 3 - Transact
"""
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.backend.models.entities import (
    Base, Tenant, Warehouse, InventoryItem, Quote, QuoteItem, SalesOrder
)
from src.backend.domains.orders.service import (
    OrderService, OptimisticLockError, QuoteNotAcceptableError
)
from src.backend.domains.inventory.service import InventoryService


@asynccontextmanager
async def get_test_order_env():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        tenant = Tenant(id="tenant_order_race", name="Race Test Tenant", slug="race-tenant", is_active=True)
        session.add(tenant)

        wh = Warehouse(id="wh_race", tenant_id=tenant.id, code="WH-RACE", name="Warehouse", is_active=True)
        session.add(wh)

        item = InventoryItem(
            id="item_race_sku",
            tenant_id=tenant.id,
            warehouse_id=wh.id,
            sku="SKU-RACE-1",
            on_hand_quantity=10,
            reserved_quantity=0,
            allocated_quantity=0,
            backorder_allowed=False
        )
        session.add(item)

        valid_until = datetime.now(timezone.utc) + timedelta(days=7)
        quote = Quote(
            id="quote_race_1",
            tenant_id=tenant.id,
            quote_number="QUO-RACE-001",
            currency="USD",
            status="ISSUED",
            version=1,
            subtotal_cents=10000,
            discount_total_cents=0,
            tax_total_cents=2000,
            grand_total_cents=12000,
            terms_hash="a"*64,
            valid_until=valid_until
        )
        session.add(quote)

        quote_item = QuoteItem(
            id="qi_race_1",
            tenant_id=tenant.id,
            quote_id=quote.id,
            sku_snapshot="SKU-RACE-1",
            name_snapshot="Race SKU",
            quantity=2,
            uom_snapshot="UNIT",
            unit_price_cents=5000,
            subtotal_cents=10000,
            tax_cents=2000,
            total_cents=12000
        )
        session.add(quote_item)
        await session.commit()

    try:
        yield session_factory, "tenant_order_race", "quote_race_1"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_quote_acceptance_race_produces_exactly_one_order():
    """
    Two concurrent checkout calls attempt to accept the same quotation.
    Verifies that only 1 order is created, and both callers receive the exact same order_id.
    Zero duplicate orders.
    """
    async with get_test_order_env() as (session_factory, tenant_id, quote_id):
        order_ids = []

        async def accept_quote_call(call_id: int):
            async with session_factory() as session:
                order_service = OrderService(session)
                order = await order_service.create_order_from_quote(
                    tenant_id=tenant_id,
                    quote_id=quote_id,
                    expected_quote_version=1,
                    idempotency_key=f"idem_quote_{quote_id}"
                )
                await session.commit()
                order_ids.append(order.id)

        tasks = [asyncio.create_task(accept_quote_call(i)) for i in range(2)]
        await asyncio.gather(*tasks)

        assert len(order_ids) == 2
        assert order_ids[0] == order_ids[1], "Both calls must return the same order ID"

        # Verify only 1 order exists in database
        async with session_factory() as session:
            order_service = OrderService(session)
            orders = await order_service.list_orders(tenant_id=tenant_id)
            assert len(orders) == 1


@pytest.mark.asyncio
async def test_quote_version_conflict_fails_closed():
    """
    If the expected_quote_version does not match the current quote version,
    the acceptance must fail with OptimisticLockError.
    """
    async with get_test_order_env() as (session_factory, tenant_id, quote_id):
        async with session_factory() as session:
            order_service = OrderService(session)
            with pytest.raises(OptimisticLockError, match="Quote version conflict"):
                await order_service.create_order_from_quote(
                    tenant_id=tenant_id,
                    quote_id=quote_id,
                    expected_quote_version=99  # Stale version
                )


@pytest.mark.asyncio
async def test_order_status_optimistic_concurrency_conflict():
    """
    Two concurrent managers attempt to transition the order state.
    The first succeeds and advances version; the second fails with OptimisticLockError.
    """
    async with get_test_order_env() as (session_factory, tenant_id, quote_id):
        # Create initial order
        async with session_factory() as session:
            order_service = OrderService(session)
            order = await order_service.create_order_from_quote(
                tenant_id=tenant_id,
                quote_id=quote_id,
                expected_quote_version=1
            )
            await session.commit()
            order_id = order.id
            initial_version = order.version

        # Transition 1 succeeds
        async with session_factory() as session:
            order_service = OrderService(session)
            await order_service.transition_order_status(
                tenant_id=tenant_id,
                order_id=order_id,
                new_status="PAYMENT_AUTHORIZED",
                expected_version=initial_version
            )
            await session.commit()

        # Transition 2 with stale initial_version fails
        async with session_factory() as session:
            order_service = OrderService(session)
            with pytest.raises(OptimisticLockError, match="Order version conflict"):
                await order_service.transition_order_status(
                    tenant_id=tenant_id,
                    order_id=order_id,
                    new_status="CANCELLED",
                    expected_version=initial_version  # Stale!
                )
