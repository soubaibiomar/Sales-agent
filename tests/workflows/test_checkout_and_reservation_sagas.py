"""
Tests for Concrete Business Sagas: Checkout, Stock Expiry, Quote Escalation, Fulfillment, and RMA Triage.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
import pytest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from src.backend.models.entities import (
    Base, Tenant, Warehouse, Product, InventoryItem, StockReservation,
    PaymentIntent, Quote, Shipment, ReturnAuthorization, OutboxEvent, WorkflowExecution, SalesOrder
)
from src.backend.workflows.engine import WorkflowEngine, WorkflowExecutionStatus
import src.backend.workflows.sagas  # Ensure sagas are registered


@asynccontextmanager
async def get_saga_test_db():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_sagas_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tenant_id = "tenant_saga_test"
    wh_id = f"wh-{uuid.uuid4().hex[:8]}"
    prod_id = f"prod-{uuid.uuid4().hex[:8]}"
    sku = "SKU-LAPTOP-01"

    async with session_factory() as session:
        tenant = Tenant(id=tenant_id, name="Saga Test Tenant", slug=f"saga-tenant-{unique_id}")
        wh = Warehouse(id=wh_id, tenant_id=tenant_id, name="Casablanca Central Hub", code=f"WH-{unique_id[:4]}")
        prod = Product(id=prod_id, tenant_id=tenant_id, sku=sku, name="High Performance Laptop", base_price_cents=1500000)
        item = InventoryItem(
            id=f"item-{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            warehouse_id=wh_id,
            product_id=prod_id,
            sku=sku,
            on_hand_quantity=10,
            reserved_quantity=0,
            allocated_quantity=0
        )
        session.add_all([tenant, wh, prod, item])
        await session.commit()

    async with session_factory() as session:
        yield {
            "session": session,
            "tenant_id": tenant_id,
            "warehouse_id": wh_id,
            "sku": sku
        }

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_checkout_saga_happy_path():
    """
    Verifies that CHECKOUT_SAGA executes all forward steps:
    1. Reserves stock
    2. Creates payment intent
    3. Commits order & stock ledger
    Status reaches COMPLETED.
    """
    async with get_saga_test_db() as db_ctx:
        session = db_ctx["session"]
        tenant_id = db_ctx["tenant_id"]
        wh_id = db_ctx["warehouse_id"]
        sku = db_ctx["sku"]

        order_id = "ord-chk-happy-01"
        order = SalesOrder(
            id=order_id,
            tenant_id=tenant_id,
            order_number="ORD-CHK-01",
            status="PENDING_PAYMENT",
            grand_total_cents=3000000,
            terms_hash="hash_chk_happy"
        )
        session.add(order)
        await session.commit()

        payload = {
            "warehouse_id": wh_id,
            "sku": sku,
            "quantity": 2,
            "amount_cents": 3000000,
            "currency": "MAD",
            "order_id": order_id,
            "notification_channel": "EMAIL",
            "customer_email": "customer@acme.ma",
            "simulate_payment_failure": False
        }

        execution = await WorkflowEngine.execute_workflow(
            session=session,
            tenant_id=tenant_id,
            workflow_type="CHECKOUT_SAGA",
            workflow_name="Checkout Order Saga",
            idempotency_key=f"idemp-chk-{uuid.uuid4().hex[:8]}",
            input_payload=payload
        )

        assert execution.status == WorkflowExecutionStatus.COMPLETED.value
        assert execution.current_step == "commit_order_and_ledger"

        # Verify inventory was committed
        stmt = select(InventoryItem).where(InventoryItem.tenant_id == tenant_id, InventoryItem.sku == sku)
        item = (await session.execute(stmt)).scalars().one()
        assert item.on_hand_quantity == 8
        assert item.allocated_quantity == 0


@pytest.mark.asyncio
async def test_checkout_saga_failure_and_reverse_compensation():
    """
    Verifies that when Step 2 (payment intent) fails, the engine runs compensation
    in reverse order:
    - Step 1 (reserve_stock) is compensated by calling release_reservation.
    - Status transitions to COMPENSATED.
    - Allocated stock is released back.
    """
    async with get_saga_test_db() as db_ctx:
        session = db_ctx["session"]
        tenant_id = db_ctx["tenant_id"]
        wh_id = db_ctx["warehouse_id"]
        sku = db_ctx["sku"]

        order_id = "ord-chk-fail-01"
        order = SalesOrder(
            id=order_id,
            tenant_id=tenant_id,
            order_number="ORD-CHK-02",
            status="PENDING_PAYMENT",
            grand_total_cents=4500000,
            terms_hash="hash_chk_fail"
        )
        session.add(order)
        await session.commit()

        # Initial inventory state
        stmt = select(InventoryItem).where(InventoryItem.tenant_id == tenant_id, InventoryItem.sku == sku)
        item_before = (await session.execute(stmt)).scalars().one()
        initial_on_hand = item_before.on_hand_quantity

        payload = {
            "warehouse_id": wh_id,
            "sku": sku,
            "quantity": 3,
            "amount_cents": 4500000,
            "currency": "MAD",
            "order_id": order_id,
            "customer_email": "fail@acme.ma",
            "simulate_payment_failure": True  # INJECT FAILURE AT STEP 2
        }

        execution = await WorkflowEngine.execute_workflow(
            session=session,
            tenant_id=tenant_id,
            workflow_type="CHECKOUT_SAGA",
            workflow_name="Failing Checkout Saga",
            idempotency_key=f"idemp-fail-{uuid.uuid4().hex[:8]}",
            input_payload=payload
        )

        # Status must be COMPENSATED
        assert execution.status == WorkflowExecutionStatus.COMPENSATED.value
        assert execution.error_message is not None
        assert "Simulated Payment Gateway Network Timeout" in execution.error_message

        # Verify that the stock reservation was released and on_hand was NOT lost
        stmt = select(InventoryItem).where(InventoryItem.tenant_id == tenant_id, InventoryItem.sku == sku)
        item_after = (await session.execute(stmt)).scalars().one()
        assert item_after.on_hand_quantity == initial_on_hand
        assert item_after.allocated_quantity == 0


@pytest.mark.asyncio
async def test_stock_expiry_saga():
    """
    Verifies that STOCK_EXPIRY scans and releases reservations past their TTL.
    """
    async with get_saga_test_db() as db_ctx:
        session = db_ctx["session"]
        tenant_id = db_ctx["tenant_id"]
        wh_id = db_ctx["warehouse_id"]
        sku = db_ctx["sku"]

        # Create an expired reservation
        from src.backend.domains.inventory.service import InventoryService
        inv_service = InventoryService(session)
        res = await inv_service.reserve_stock(
            tenant_id=tenant_id,
            sku=sku,
            quantity=1,
            warehouse_id=wh_id,
            order_id="ref-stale-001",
            duration_seconds=900
        )
        # Force reserved_until into the past
        res.reserved_until = datetime.now(timezone.utc) - timedelta(minutes=30)
        await session.commit()

        execution = await WorkflowEngine.execute_workflow(
            session=session,
            tenant_id=tenant_id,
            workflow_type="STOCK_EXPIRY",
            workflow_name="Stock Expiry Workflow",
            idempotency_key=f"idemp-exp-{uuid.uuid4().hex[:8]}",
            input_payload={}
        )

        assert execution.status == WorkflowExecutionStatus.COMPLETED.value
        step_out = execution.context_payload.get("step_outputs", {}).get("scan_and_release_expired", {})
        assert step_out.get("expired_reservations_released") >= 1


@pytest.mark.asyncio
async def test_quote_approval_escalation_saga():
    """
    Verifies that QUOTE_APPROVAL_ESCALATION marks expired quotes as EXPIRED.
    """
    async with get_saga_test_db() as db_ctx:
        session = db_ctx["session"]
        tenant_id = db_ctx["tenant_id"]

        quote_id = f"q-{uuid.uuid4().hex[:8]}"
        past_due = datetime.now(timezone.utc) - timedelta(hours=2)
        quote = Quote(
            id=quote_id,
            tenant_id=tenant_id,
            quote_number="QT-2026-999",
            status="PENDING_APPROVAL",
            grand_total_cents=500000,
            terms_hash="hash_sample_terms_1234",
            valid_until=past_due
        )
        session.add(quote)
        await session.commit()

        execution = await WorkflowEngine.execute_workflow(
            session=session,
            tenant_id=tenant_id,
            workflow_type="QUOTE_APPROVAL_ESCALATION",
            workflow_name="Quote Escalation",
            idempotency_key=f"idemp-qesc-{uuid.uuid4().hex[:8]}",
            input_payload={"quote_id": quote_id}
        )

        assert execution.status == WorkflowExecutionStatus.COMPLETED.value

        # Check quote was updated to EXPIRED
        stmt = select(Quote).where(Quote.tenant_id == tenant_id, Quote.id == quote_id)
        updated_q = (await session.execute(stmt)).scalars().one()
        assert updated_q.status == "EXPIRED"


@pytest.mark.asyncio
async def test_rma_triage_saga():
    """
    Verifies that RMA_TRIAGE restocks returned goods and completes return authorization.
    """
    async with get_saga_test_db() as db_ctx:
        session = db_ctx["session"]
        tenant_id = db_ctx["tenant_id"]
        wh_id = db_ctx["warehouse_id"]
        sku = db_ctx["sku"]

        order_id = f"ord-{uuid.uuid4().hex[:8]}"
        order = SalesOrder(
            id=order_id,
            tenant_id=tenant_id,
            order_number=f"ORD-{order_id[:6]}",
            terms_hash="hash_order_rma"
        )
        session.add(order)
        await session.flush()

        rma_id = f"rma-{uuid.uuid4().hex[:8]}"
        rma = ReturnAuthorization(
            id=rma_id,
            tenant_id=tenant_id,
            order_id=order_id,
            rma_number="RMA-2026-001",
            status="PENDING",
            reason="Item defective on arrival"
        )
        session.add(rma)
        await session.commit()

        execution = await WorkflowEngine.execute_workflow(
            session=session,
            tenant_id=tenant_id,
            workflow_type="RMA_TRIAGE",
            workflow_name="RMA Triage Saga",
            idempotency_key=f"idemp-rma-{uuid.uuid4().hex[:8]}",
            input_payload={
                "rma_id": rma_id,
                "disposition": "RESTOCK",
                "sku": sku,
                "quantity": 1,
                "warehouse_id": wh_id
            }
        )

        assert execution.status == WorkflowExecutionStatus.COMPLETED.value
        stmt = select(ReturnAuthorization).where(ReturnAuthorization.tenant_id == tenant_id, ReturnAuthorization.id == rma_id)
        updated_rma = (await session.execute(stmt)).scalars().one()
        assert updated_rma.status in ("REFUNDED", "RESTOCKED")


@pytest.mark.asyncio
async def test_daily_reconciliation_saga():
    """
    Verifies that DAILY_RECONCILIATION calculates ATP consistency across warehouses.
    """
    async with get_saga_test_db() as db_ctx:
        session = db_ctx["session"]
        tenant_id = db_ctx["tenant_id"]

        execution = await WorkflowEngine.execute_workflow(
            session=session,
            tenant_id=tenant_id,
            workflow_type="DAILY_RECONCILIATION",
            workflow_name="Daily Ledger Audit",
            idempotency_key=f"idemp-recon-{uuid.uuid4().hex[:8]}",
            input_payload={}
        )

        assert execution.status == WorkflowExecutionStatus.COMPLETED.value
        step_out = execution.context_payload.get("step_outputs", {}).get("audit_ledger_atp_balance", {})
        assert step_out.get("reconciliation_healthy") is True
