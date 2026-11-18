"""
Concrete Business Sagas & Transactional Workflows.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.workflows.engine import WorkflowStep, SagaDefinition, WorkflowEngine
from src.backend.domains.inventory.service import InventoryService
from src.backend.domains.payments.service import PaymentService
from src.backend.domains.orders.service import OrderService
from src.backend.domains.invoicing.service import InvoicingService
from src.backend.models.entities import (
    StockReservation,
    PaymentIntent,
    SalesOrder,
    Quote,
    Shipment,
    ReturnAuthorization,
    OutboxEvent
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# 1. CHECKOUT & PAYMENT SETTLEMENT SAGA
# ============================================================================

async def checkout_step_reserve_stock(ctx: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    tenant_id = ctx["tenant_id"]
    payload = ctx["payload"]
    warehouse_id = payload["warehouse_id"]
    sku = payload["sku"]
    quantity = payload["quantity"]
    order_ref = payload.get("order_id") or f"ord_{uuid.uuid4().hex[:12]}"

    inv_service = InventoryService(db)
    reservation = await inv_service.reserve_stock(
        tenant_id=tenant_id,
        sku=sku,
        quantity=quantity,
        warehouse_id=warehouse_id,
        order_id=order_ref,
        duration_seconds=900
    )
    ctx["reservation_id"] = reservation.id
    ctx["order_id"] = order_ref
    return {"reservation_id": reservation.id, "order_id": order_ref, "quantity_reserved": quantity}


async def checkout_compensate_reserve_stock(ctx: Dict[str, Any], db: AsyncSession) -> None:
    tenant_id = ctx["tenant_id"]
    res_id = ctx.get("reservation_id") or ctx.get("step_outputs", {}).get("reserve_stock", {}).get("reservation_id")
    if res_id:
        inv_service = InventoryService(db)
        await inv_service.release_reservation(tenant_id, res_id, reason="Checkout saga failure compensation")


async def checkout_step_create_payment_intent(ctx: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    tenant_id = ctx["tenant_id"]
    payload = ctx["payload"]
    amount_cents = payload["amount_cents"]
    currency = payload.get("currency", "MAD")
    order_id = ctx.get("order_id", payload.get("order_id", "ord_temp"))

    # Intentional failure injection for testing
    if payload.get("simulate_payment_failure"):
        raise RuntimeError("Simulated Payment Gateway Network Timeout (HTTP 504)")

    # Ensure a sales order exists for foreign key constraint
    order_stmt = select(SalesOrder).where(SalesOrder.tenant_id == tenant_id, SalesOrder.id == order_id)
    order = (await db.execute(order_stmt)).scalars().first()
    if not order:
        order = SalesOrder(
            id=order_id,
            tenant_id=tenant_id,
            order_number=f"ORD-{order_id[:8]}",
            status="PENDING_PAYMENT",
            grand_total_cents=amount_cents,
            terms_hash="hash_auto_saga",
            currency=currency
        )
        db.add(order)
        await db.flush()

    pay_service = PaymentService(db)
    intent = await pay_service.create_payment_intent(
        tenant_id=tenant_id,
        order_id=order_id,
        metadata={"workflow_id": ctx.get("workflow_id")}
    )
    ctx["payment_intent_id"] = intent.id
    return {"payment_intent_id": intent.id, "amount_cents": amount_cents, "status": intent.status}


async def checkout_compensate_payment_intent(ctx: Dict[str, Any], db: AsyncSession) -> None:
    tenant_id = ctx["tenant_id"]
    intent_id = ctx.get("payment_intent_id") or ctx.get("step_outputs", {}).get("create_payment_intent", {}).get("payment_intent_id")
    if intent_id:
        stmt = select(PaymentIntent).where(PaymentIntent.tenant_id == tenant_id, PaymentIntent.id == intent_id)
        intent = (await db.execute(stmt)).scalars().first()
        if intent:
            intent.status = "CANCELLED"
            await db.flush()


async def checkout_step_commit_order_and_ledger(ctx: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    tenant_id = ctx["tenant_id"]
    payload = ctx["payload"]
    reservation_id = ctx["reservation_id"]
    order_id = ctx["order_id"]

    inv_service = InventoryService(db)
    # Commit reservation to permanent ledger deduction
    movement = await inv_service.commit_reservation(
        tenant_id=tenant_id,
        reservation_id=reservation_id,
        reference_id=order_id
    )

    # Enqueue Outbox notification
    from src.backend.domains.conversations.outbox import OutboxService
    outbox_ev = await OutboxService.enqueue_outbound_event(
        session=db,
        tenant_id=tenant_id,
        channel_type=payload.get("notification_channel", "EMAIL"),
        recipient_identifier=payload.get("customer_email", "customer@example.com"),
        event_type="ORDER_CONFIRMED",
        payload_dict={"order_id": order_id, "sku": payload["sku"], "quantity": payload["quantity"]},
        message_class="TRANSACTIONAL"
    )

    return {
        "order_id": order_id,
        "stock_movement_id": movement.id,
        "outbox_event_id": outbox_ev.id,
        "status": "COMMITTED"
    }


checkout_saga = SagaDefinition(
    name="CHECKOUT_SAGA",
    steps=[
        WorkflowStep("reserve_stock", checkout_step_reserve_stock, checkout_compensate_reserve_stock),
        WorkflowStep("create_payment_intent", checkout_step_create_payment_intent, checkout_compensate_payment_intent),
        WorkflowStep("commit_order_and_ledger", checkout_step_commit_order_and_ledger, None)
    ]
)
WorkflowEngine.register_saga(checkout_saga)


# ============================================================================
# 2. STOCK HOLD EXPIRATION WORKFLOW
# ============================================================================

async def stock_expiry_scan_and_release(ctx: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    tenant_id = ctx["tenant_id"]
    inv_service = InventoryService(db)
    expired_count = await inv_service.expire_stale_reservations(tenant_id)
    return {"expired_reservations_released": expired_count}


stock_expiry_workflow = SagaDefinition(
    name="STOCK_EXPIRY",
    steps=[
        WorkflowStep("scan_and_release_expired", stock_expiry_scan_and_release, None)
    ]
)
WorkflowEngine.register_saga(stock_expiry_workflow)


# ============================================================================
# 3. QUOTE APPROVAL ESCALATION WORKFLOW
# ============================================================================

async def quote_escalation_step(ctx: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    tenant_id = ctx["tenant_id"]
    quote_id = ctx["payload"].get("quote_id")

    stmt = select(Quote).where(Quote.tenant_id == tenant_id, Quote.id == quote_id)
    quote = (await db.execute(stmt)).scalars().first()
    if not quote:
        raise ValueError(f"Quote '{quote_id}' not found.")

    if quote.status == "PENDING_APPROVAL":
        # Check if expired or escalate
        if quote.valid_until and quote.valid_until <= utc_now():
            quote.status = "EXPIRED"
            outcome = "AUTO_EXPIRED"
        else:
            outcome = "MANAGER_REMINDER_SENT"
            # Enqueue high-priority reminder in outbox
            from src.backend.domains.conversations.outbox import OutboxService
            await OutboxService.enqueue_outbound_event(
                session=db,
                tenant_id=tenant_id,
                channel_type="EMAIL",
                recipient_identifier="manager@tenant.com",
                event_type="QUOTE_APPROVAL_REQUIRED",
                payload_dict={"quote_id": quote_id, "total_cents": quote.total_cents},
                message_class="TRANSACTIONAL",
                is_high_priority=True
            )
        await db.flush()
        return {"quote_id": quote_id, "action": outcome, "status": quote.status}

    return {"quote_id": quote_id, "action": "NO_OP", "status": quote.status}


quote_escalation_workflow = SagaDefinition(
    name="QUOTE_APPROVAL_ESCALATION",
    steps=[
        WorkflowStep("evaluate_and_escalate", quote_escalation_step, None)
    ]
)
WorkflowEngine.register_saga(quote_escalation_workflow)


# ============================================================================
# 4. FULFILLMENT DISPATCH WORKFLOW
# ============================================================================

async def fulfillment_dispatch_step(ctx: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    tenant_id = ctx["tenant_id"]
    shipment_id = ctx["payload"].get("shipment_id")

    stmt = select(Shipment).where(Shipment.tenant_id == tenant_id, Shipment.id == shipment_id)
    shipment = (await db.execute(stmt)).scalars().first()
    if not shipment:
        raise ValueError(f"Shipment '{shipment_id}' not found.")

    # Monotonic progression: CREATED -> PICKING -> PACKED -> SHIPPED
    if shipment.status in ("CREATED", "PICKING", "PACKED"):
        shipment.status = "SHIPPED"
        shipment.shipped_at = utc_now()
        shipment.carrier_status = "IN_TRANSIT"
        await db.flush()

        from src.backend.domains.conversations.outbox import OutboxService
        await OutboxService.enqueue_outbound_event(
            session=db,
            tenant_id=tenant_id,
            channel_type="WHATSAPP",
            recipient_identifier=ctx["payload"].get("customer_phone", "+212600000000"),
            event_type="SHIPMENT_SHIPPED",
            payload_dict={"shipment_id": shipment_id, "tracking_number": shipment.tracking_number},
            message_class="TRANSACTIONAL"
        )
        return {"shipment_id": shipment_id, "status": "SHIPPED", "tracking_number": shipment.tracking_number}

    return {"shipment_id": shipment_id, "status": shipment.status, "message": "Already dispatched"}


fulfillment_workflow = SagaDefinition(
    name="FULFILLMENT_DISPATCH",
    steps=[
        WorkflowStep("dispatch_shipment", fulfillment_dispatch_step, None)
    ]
)
WorkflowEngine.register_saga(fulfillment_workflow)


# ============================================================================
# 5. RMA INSPECTION & RESTOCK SAGA
# ============================================================================

async def rma_step_inspect(ctx: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    tenant_id = ctx["tenant_id"]
    rma_id = ctx["payload"].get("rma_id")
    disposition = ctx["payload"].get("disposition", "RESTOCK")

    stmt = select(ReturnAuthorization).where(ReturnAuthorization.tenant_id == tenant_id, ReturnAuthorization.id == rma_id)
    rma = (await db.execute(stmt)).scalars().first()
    if not rma:
        raise ValueError(f"RMA '{rma_id}' not found.")

    rma.status = "RECEIVED"
    await db.flush()
    return {"rma_id": rma_id, "disposition": disposition}


async def rma_step_settle(ctx: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    tenant_id = ctx["tenant_id"]
    rma_id = ctx["payload"].get("rma_id")
    disposition = ctx["payload"].get("disposition", "RESTOCK")
    sku = ctx["payload"].get("sku")
    quantity = ctx["payload"].get("quantity", 1)
    warehouse_id = ctx["payload"].get("warehouse_id")

    stmt = select(ReturnAuthorization).where(ReturnAuthorization.tenant_id == tenant_id, ReturnAuthorization.id == rma_id)
    rma = (await db.execute(stmt)).scalars().first()

    refund_issued = False
    if disposition == "RESTOCK" and warehouse_id and sku:
        inv_service = InventoryService(db)
        items = await inv_service.get_inventory_items(tenant_id)
        matching = [i for i in items if i.sku == sku and i.warehouse_id == warehouse_id]
        if matching:
            await inv_service.adjust_stock(
                tenant_id=tenant_id,
                inventory_item_id=matching[0].id,
                quantity_delta=quantity,
                movement_type="RETURN_RESTOCK",
                reference_id=rma_id
            )
        rma.status = "RESTOCKED"
        refund_issued = True
    elif disposition in ("QUARANTINE", "SCRAP"):
        rma.status = "COMPLETED"
    else:
        rma.status = "REJECTED"

    await db.flush()
    return {"rma_id": rma_id, "final_status": rma.status, "refund_issued": refund_issued}


rma_saga = SagaDefinition(
    name="RMA_TRIAGE",
    steps=[
        WorkflowStep("inspect_return", rma_step_inspect, None),
        WorkflowStep("settle_return_and_restock", rma_step_settle, None)
    ]
)
WorkflowEngine.register_saga(rma_saga)


# ============================================================================
# 6. DAILY RECONCILIATION JOB
# ============================================================================

async def reconciliation_step_audit(ctx: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    tenant_id = ctx["tenant_id"]
    # Check total active reservations vs items
    inv_service = InventoryService(db)
    items = await inv_service.get_inventory_items(tenant_id)
    total_on_hand = sum(i.on_hand_quantity for i in items)
    total_allocated = sum(i.allocated_quantity for i in items)
    total_atp = sum(i.available_to_promise for i in items)

    return {
        "tenant_id": tenant_id,
        "total_on_hand": total_on_hand,
        "total_allocated": total_allocated,
        "total_atp": total_atp,
        "reconciliation_healthy": (total_on_hand == total_allocated + total_atp),
        "timestamp": utc_now().isoformat()
    }


reconciliation_job = SagaDefinition(
    name="DAILY_RECONCILIATION",
    steps=[
        WorkflowStep("audit_ledger_atp_balance", reconciliation_step_audit, None)
    ]
)
WorkflowEngine.register_saga(reconciliation_job)
