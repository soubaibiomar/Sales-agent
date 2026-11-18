"""
Sales Order Domain Service.
Handles Idempotent Quote Acceptance, Sales Order State Machine,
Optimistic Version Concurrency, Stock Reservation Orchestration, and Audit Logging.
Step 05: Sprint 3 - Transact
"""
import uuid
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Dict, Any

_quote_locks: Dict[str, asyncio.Lock] = {}

def get_quote_lock(key: str) -> asyncio.Lock:
    if key not in _quote_locks:
        _quote_locks[key] = asyncio.Lock()
    return _quote_locks[key]
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.backend.models.entities import (
    SalesOrder, OrderItem, Quote, QuoteItem, StockReservation, AuditEvent
)
from src.backend.domains.pricing.money import Money, calculate_tax, calculate_discount
from src.backend.domains.pricing.service import PricingService
from src.backend.domains.inventory.service import InventoryService, InsufficientStockError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OrderError(Exception):
    pass


class OptimisticLockError(OrderError):
    pass


class InvalidOrderStateTransitionError(OrderError):
    pass


class QuoteNotAcceptableError(OrderError):
    pass


class OrderNotFoundError(OrderError):
    pass


VALID_ORDER_TRANSITIONS: Dict[str, List[str]] = {
    "DRAFT": ["PENDING_PAYMENT", "CANCELLED"],
    "PENDING_PAYMENT": ["PAYMENT_AUTHORIZED", "PAID", "CANCELLED"],
    "PAYMENT_AUTHORIZED": ["PAID", "CANCELLED"],
    "PAID": ["PROCESSING", "PARTIALLY_FULFILLED", "FULFILLED", "REFUNDED"],
    "PROCESSING": ["PARTIALLY_FULFILLED", "FULFILLED", "CANCELLED"],
    "PARTIALLY_FULFILLED": ["FULFILLED", "REFUNDED"],
    "FULFILLED": ["REFUNDED"],
    "CANCELLED": [],
    "REFUNDED": []
}


class OrderService:
    def __init__(self, db: AsyncSession, inventory_service: Optional[InventoryService] = None):
        self.db = db
        self.inventory_service = inventory_service or InventoryService(db)

    async def create_order(
        self,
        tenant_id: str,
        account_id: Optional[str],
        contact_id: Optional[str],
        currency: str,
        items_data: List[Dict[str, Any]],
        shipping_address_json: str = "{}",
        billing_address_json: str = "{}",
        idempotency_key: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        # Idempotency check
        if idempotency_key:
            stmt = select(SalesOrder).where(
                and_(
                    SalesOrder.tenant_id == tenant_id,
                    SalesOrder.idempotency_key == idempotency_key
                )
            ).options(selectinload(SalesOrder.items))
            res = await self.db.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                return existing

        order_number = f"ORD-{datetime.now().strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"

        subtotal_cents = 0
        discount_total_cents = 0
        tax_total_cents = 0
        canonical_items = []

        order = SalesOrder(
            tenant_id=tenant_id,
            order_number=order_number,
            account_id=account_id,
            contact_id=contact_id,
            currency=currency.upper(),
            status="PENDING_PAYMENT",
            version=1,
            payment_status="UNPAID",
            fulfillment_status="UNFULFILLED",
            shipping_address_json=shipping_address_json,
            billing_address_json=billing_address_json,
            idempotency_key=idempotency_key,
            created_by_user_id=user_id,
            terms_hash=""
        )
        self.db.add(order)
        await self.db.flush()

        for it in items_data:
            qty = it["quantity"]
            unit_price = it["unit_price_cents"]
            unit_cost = it.get("unit_cost_cents", 0)
            disc_pct = Decimal(str(it.get("discount_percent", 0.0)))
            tax_pct = Decimal(str(it.get("tax_rate_percent", 20.0)))

            item_subtotal = unit_price * qty
            item_discount = calculate_discount(item_subtotal, disc_pct)
            net_item_subtotal = item_subtotal - item_discount
            item_tax = calculate_tax(net_item_subtotal, tax_pct)
            item_total = net_item_subtotal + item_tax

            subtotal_cents += item_subtotal
            discount_total_cents += item_discount
            tax_total_cents += item_tax

            order_item = OrderItem(
                tenant_id=tenant_id,
                order_id=order.id,
                product_id=it.get("product_id"),
                variant_id=it.get("variant_id"),
                sku=it["sku"].upper(),
                name=it["name"],
                quantity=qty,
                uom=it.get("uom", "UNIT"),
                unit_price_cents=unit_price,
                unit_cost_cents=unit_cost,
                discount_percent=disc_pct,
                discount_cents=item_discount,
                tax_rate_percent=tax_pct,
                tax_cents=item_tax,
                subtotal_cents=net_item_subtotal,
                total_cents=item_total,
                fulfillment_status="UNFULFILLED"
            )
            self.db.add(order_item)

            canonical_items.append({
                "sku_snapshot": it["sku"].upper(),
                "variant_id": it.get("variant_id"),
                "quantity": qty,
                "unit_price_cents": unit_price,
                "discount_percent": disc_pct,
                "discount_cents": item_discount,
                "tax_cents": item_tax,
                "total_cents": item_total
            })

            # Attempt atomic stock reservation
            await self.inventory_service.reserve_stock(
                tenant_id=tenant_id,
                sku=it["sku"].upper(),
                quantity=qty,
                order_id=order.id,
                duration_seconds=1800,
                idempotency_key=f"res_{order.id}_{it['sku'].upper()}"
            )

        grand_total_cents = subtotal_cents - discount_total_cents + tax_total_cents
        terms_hash = PricingService.compute_terms_hash(
            items=canonical_items,
            subtotal_cents=subtotal_cents,
            discount_total_cents=discount_total_cents,
            tax_total_cents=tax_total_cents,
            grand_total_cents=grand_total_cents,
            currency=currency,
            payment_terms="IMMEDIATE"
        )

        order.subtotal_cents = subtotal_cents
        order.discount_total_cents = discount_total_cents
        order.tax_total_cents = tax_total_cents
        order.grand_total_cents = grand_total_cents
        order.terms_hash = terms_hash

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id=user_id,
            event_type="ORDER_CREATED",
            resource_type="SALES_ORDER",
            resource_id=order.id,
            action="CREATE",
            status="SUCCESS",
            payload_json=f'{{"order_number": "{order_number}", "grand_total_cents": {grand_total_cents}}}'
        )
        self.db.add(audit)
        await self.db.flush()

        stmt = select(SalesOrder).where(SalesOrder.id == order.id).options(selectinload(SalesOrder.items))
        res = await self.db.execute(stmt)
        return res.scalar_one()

    async def create_order_from_quote(
        self,
        tenant_id: str,
        quote_id: str,
        expected_quote_version: int,
        shipping_address_json: str = "{}",
        billing_address_json: str = "{}",
        idempotency_key: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        async with get_quote_lock(f"{tenant_id}_{quote_id}"):
            # Check idempotency first (Control 51, Control 58)
            if idempotency_key:
                stmt = select(SalesOrder).where(
                    and_(
                        SalesOrder.tenant_id == tenant_id,
                        SalesOrder.idempotency_key == idempotency_key
                    )
                ).options(selectinload(SalesOrder.items))
                res = await self.db.execute(stmt)
                existing = res.scalar_one_or_none()
                if existing:
                    return existing

            # Check if an order already exists for this quote
            existing_stmt = select(SalesOrder).where(
                and_(
                    SalesOrder.tenant_id == tenant_id,
                    SalesOrder.quote_id == quote_id
                )
            ).options(selectinload(SalesOrder.items))
            existing_res = await self.db.execute(existing_stmt)
            existing_order = existing_res.scalar_one_or_none()
            if existing_order:
                return existing_order

            # Lock and validate quote
            q_stmt = select(Quote).where(
                and_(Quote.id == quote_id, Quote.tenant_id == tenant_id)
            ).options(selectinload(Quote.items)).with_for_update()
            q_res = await self.db.execute(q_stmt)
            quote = q_res.scalar_one_or_none()
            if not quote:
                raise OrderError("Quote not found")

            if quote.version != expected_quote_version:
                raise OptimisticLockError(
                    f"Quote version conflict: current={quote.version}, expected={expected_quote_version}"
                )

            now = utc_now()
            quote_valid_until = quote.valid_until
            if quote_valid_until.tzinfo is None:
                quote_valid_until = quote_valid_until.replace(tzinfo=timezone.utc)
            if quote_valid_until < now:
                raise QuoteNotAcceptableError(f"Quote {quote.quote_number} has expired on {quote.valid_until}")

            if quote.status not in ("ISSUED", "SENT", "ACCEPTED"):
                raise QuoteNotAcceptableError(
                    f"Cannot create order from quote with status {quote.status}. Must be ISSUED, SENT, or ACCEPTED."
                )

            # Transition quote to ACCEPTED if not already
            if quote.status != "ACCEPTED":
                quote.status = "ACCEPTED"
                quote.accepted_at = now
                quote.version += 1

            order_number = f"ORD-{datetime.now().strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}"

            order = SalesOrder(
                tenant_id=tenant_id,
                order_number=order_number,
                quote_id=quote.id,
                account_id=quote.account_id,
                contact_id=quote.contact_id,
                currency=quote.currency,
                status="PENDING_PAYMENT",
                version=1,
                subtotal_cents=quote.subtotal_cents,
                discount_total_cents=quote.discount_total_cents,
                tax_total_cents=quote.tax_total_cents,
                grand_total_cents=quote.grand_total_cents,
                terms_hash=quote.terms_hash,
                payment_status="UNPAID",
                fulfillment_status="UNFULFILLED",
                shipping_address_json=shipping_address_json,
                billing_address_json=billing_address_json,
                idempotency_key=idempotency_key,
                created_by_user_id=user_id
            )
            self.db.add(order)
            await self.db.flush()

            # Copy line items and hold stock atomically
            for qi in quote.items:
                order_item = OrderItem(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    product_id=qi.product_id,
                    variant_id=qi.variant_id,
                    sku=qi.sku_snapshot,
                    name=qi.name_snapshot,
                    quantity=qi.quantity,
                    uom=qi.uom_snapshot,
                    unit_price_cents=qi.unit_price_cents,
                    unit_cost_cents=qi.unit_cost_cents,
                    discount_percent=qi.discount_percent,
                    discount_cents=qi.discount_cents,
                    tax_rate_percent=qi.tax_rate_percent,
                    tax_cents=qi.tax_cents,
                    subtotal_cents=qi.subtotal_cents,
                    total_cents=qi.total_cents,
                    fulfillment_status="UNFULFILLED"
                )
                self.db.add(order_item)

                # Atomic stock hold per line item
                await self.inventory_service.reserve_stock(
                    tenant_id=tenant_id,
                    sku=qi.sku_snapshot,
                    quantity=qi.quantity,
                    order_id=order.id,
                    quote_id=quote.id,
                    duration_seconds=1800,
                    idempotency_key=f"res_{order.id}_{qi.sku_snapshot}"
                )

            audit = AuditEvent(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                actor_id=user_id,
                event_type="ORDER_CREATED_FROM_QUOTE",
                resource_type="SALES_ORDER",
                resource_id=order.id,
                action="CREATE",
                status="SUCCESS",
                payload_json=f'{{"quote_id": "{quote.id}", "order_number": "{order_number}"}}'
            )
            self.db.add(audit)
            await self.db.flush()

            stmt = select(SalesOrder).where(SalesOrder.id == order.id).options(selectinload(SalesOrder.items))
            res = await self.db.execute(stmt)
            return res.scalar_one()

    async def transition_order_status(
        self,
        tenant_id: str,
        order_id: str,
        new_status: str,
        expected_version: int,
        reason: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        new_status = new_status.upper()
        stmt = select(SalesOrder).where(
            and_(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        ).options(selectinload(SalesOrder.items)).with_for_update()
        res = await self.db.execute(stmt)
        order = res.scalar_one_or_none()
        if not order:
            raise OrderNotFoundError("Order not found")

        if order.version != expected_version:
            raise OptimisticLockError(
                f"Order version conflict: current={order.version}, expected={expected_version}"
            )

        allowed = VALID_ORDER_TRANSITIONS.get(order.status, [])
        if new_status not in allowed:
            raise InvalidOrderStateTransitionError(
                f"Cannot transition order from {order.status} to {new_status}. Allowed: {allowed}"
            )

        old_status = order.status
        order.status = new_status
        order.version += 1

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id=user_id,
            event_type="ORDER_STATUS_CHANGED",
            resource_type="SALES_ORDER",
            resource_id=order.id,
            action="UPDATE",
            status="SUCCESS",
            payload_json=f'{{"old_status": "{old_status}", "new_status": "{new_status}", "reason": "{reason}"}}'
        )
        self.db.add(audit)
        await self.db.flush()
        return order

    async def cancel_order(
        self,
        tenant_id: str,
        order_id: str,
        expected_version: int,
        reason: str,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        order = await self.transition_order_status(
            tenant_id=tenant_id,
            order_id=order_id,
            new_status="CANCELLED",
            expected_version=expected_version,
            reason=reason,
            user_id=user_id
        )

        # Release all active reservations for this order
        res_stmt = select(StockReservation).where(
            and_(
                StockReservation.order_id == order_id,
                StockReservation.tenant_id == tenant_id,
                StockReservation.status == "ACTIVE"
            )
        )
        res_out = await self.db.execute(res_stmt)
        for res in res_out.scalars().all():
            await self.inventory_service.release_reservation(
                tenant_id=tenant_id,
                reservation_id=res.id,
                reason="ORDER_CANCELLED"
            )

        return order

    async def mark_order_paid(
        self,
        tenant_id: str,
        order_id: str,
        expected_version: int,
        transaction_id: str,
        user_id: Optional[str] = None
    ) -> SalesOrder:
        stmt = select(SalesOrder).where(
            and_(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        ).options(selectinload(SalesOrder.items)).with_for_update()
        res = await self.db.execute(stmt)
        order = res.scalar_one_or_none()
        if not order:
            raise OrderNotFoundError("Order not found")

        if order.version != expected_version:
            raise OptimisticLockError(
                f"Order version conflict: current={order.version}, expected={expected_version}"
            )

        order.status = "PAID"
        order.payment_status = "PAID"
        order.version += 1

        # Commit stock reservations
        res_stmt = select(StockReservation).where(
            and_(
                StockReservation.order_id == order_id,
                StockReservation.tenant_id == tenant_id,
                StockReservation.status == "ACTIVE"
            )
        )
        res_out = await self.db.execute(res_stmt)
        for reservation in res_out.scalars().all():
            await self.inventory_service.commit_reservation(
                tenant_id=tenant_id,
                reservation_id=reservation.id,
                reference_id=order.order_number,
                user_id=user_id
            )

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id=user_id,
            event_type="ORDER_PAID",
            resource_type="SALES_ORDER",
            resource_id=order.id,
            action="UPDATE",
            status="SUCCESS",
            payload_json=f'{{"transaction_id": "{transaction_id}", "order_number": "{order.order_number}"}}'
        )
        self.db.add(audit)
        await self.db.flush()
        return order

    async def get_order_by_id(self, tenant_id: str, order_id: str) -> Optional[SalesOrder]:
        stmt = select(SalesOrder).where(
            and_(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        ).options(selectinload(SalesOrder.items))
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_orders(
        self,
        tenant_id: str,
        status: Optional[str] = None
    ) -> List[SalesOrder]:
        query = select(SalesOrder).where(SalesOrder.tenant_id == tenant_id)
        if status:
            query = query.where(SalesOrder.status == status.upper())
        query = query.options(selectinload(SalesOrder.items)).order_by(SalesOrder.created_at.desc())
        res = await self.db.execute(query)
        return list(res.scalars().all())
