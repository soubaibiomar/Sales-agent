"""
Sales Orders API Endpoints.
Order Creation, Idempotent Quote-to-Order Conversion, State Transitions, and Cancellation.
Step 05: Sprint 3 - Transact
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.domains.orders.service import (
    OrderService, OrderError, OptimisticLockError,
    InvalidOrderStateTransitionError, QuoteNotAcceptableError, OrderNotFoundError
)
from src.backend.domains.inventory.service import InsufficientStockError
from src.backend.schemas.orders import (
    OrderCreateRequest, QuoteAcceptOrderRequest, OrderResponse,
    OrderItemResponse, OrderCancelRequest
)
from src.backend.models.entities import SalesOrder

router = APIRouter(prefix="/orders", tags=["Sales Orders"])


def map_order_to_response(order: SalesOrder) -> OrderResponse:
    item_responses = [
        OrderItemResponse(
            id=it.id,
            tenant_id=it.tenant_id,
            order_id=it.order_id,
            product_id=it.product_id,
            variant_id=it.variant_id,
            sku=it.sku,
            name=it.name,
            quantity=it.quantity,
            uom=it.uom,
            unit_price_cents=it.unit_price_cents,
            unit_cost_cents=it.unit_cost_cents,
            discount_percent=float(it.discount_percent),
            discount_cents=it.discount_cents,
            tax_rate_percent=float(it.tax_rate_percent),
            tax_cents=it.tax_cents,
            subtotal_cents=it.subtotal_cents,
            total_cents=it.total_cents,
            fulfillment_status=it.fulfillment_status,
            created_at=it.created_at
        )
        for it in (order.items or [])
    ]
    return OrderResponse(
        id=order.id,
        tenant_id=order.tenant_id,
        order_number=order.order_number,
        quote_id=order.quote_id,
        account_id=order.account_id,
        contact_id=order.contact_id,
        status=order.status,
        version=order.version,
        currency=order.currency,
        subtotal_cents=order.subtotal_cents,
        discount_total_cents=order.discount_total_cents,
        tax_total_cents=order.tax_total_cents,
        grand_total_cents=order.grand_total_cents,
        terms_hash=order.terms_hash,
        payment_status=order.payment_status,
        fulfillment_status=order.fulfillment_status,
        shipping_address_json=order.shipping_address_json,
        billing_address_json=order.billing_address_json,
        idempotency_key=order.idempotency_key,
        created_by_user_id=order.created_by_user_id,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=item_responses
    )


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    req: OrderCreateRequest,
    ctx: SecurityContext = Depends(require_permission("orders:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = OrderService(db)
    items_data = [it.model_dump() for it in req.items]
    try:
        order = await service.create_order(
            tenant_id=ctx.tenant_id,
            account_id=req.account_id,
            contact_id=req.contact_id,
            currency=req.currency,
            items_data=items_data,
            shipping_address_json=req.shipping_address_json or "{}",
            billing_address_json=req.billing_address_json or "{}",
            idempotency_key=req.idempotency_key,
            user_id=ctx.user_id
        )
        return map_order_to_response(order)
    except InsufficientStockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except OrderError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/from-quote", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order_from_quote(
    req: QuoteAcceptOrderRequest,
    ctx: SecurityContext = Depends(require_permission("quotes:create")),
    db: AsyncSession = Depends(get_db_session)
):
    service = OrderService(db)
    try:
        order = await service.create_order_from_quote(
            tenant_id=ctx.tenant_id,
            quote_id=req.quote_id,
            expected_quote_version=req.expected_quote_version,
            shipping_address_json=req.shipping_address_json or "{}",
            billing_address_json=req.billing_address_json or "{}",
            idempotency_key=req.idempotency_key,
            user_id=ctx.user_id
        )
        return map_order_to_response(order)
    except OptimisticLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except InsufficientStockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except QuoteNotAcceptableError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except OrderError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=List[OrderResponse])
async def list_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    ctx: SecurityContext = Depends(require_permission("orders:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = OrderService(db)
    orders = await service.list_orders(tenant_id=ctx.tenant_id, status=status_filter)
    return [map_order_to_response(o) for o in orders]


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    ctx: SecurityContext = Depends(require_permission("orders:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = OrderService(db)
    order = await service.get_order_by_id(tenant_id=ctx.tenant_id, order_id=order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return map_order_to_response(order)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: str,
    req: OrderCancelRequest,
    ctx: SecurityContext = Depends(require_permission("orders:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = OrderService(db)
    try:
        order = await service.cancel_order(
            tenant_id=ctx.tenant_id,
            order_id=order_id,
            expected_version=req.expected_version,
            reason=req.reason,
            user_id=ctx.user_id
        )
        return map_order_to_response(order)
    except OptimisticLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except OrderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    except OrderError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
