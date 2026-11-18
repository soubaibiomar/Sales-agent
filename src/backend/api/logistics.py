"""
Logistics, Fulfillment & Carrier REST API Endpoints.
Pick, Pack, Ship, Carrier Bookings, Monotonic Tracking Events, Delivery Proofs, and Webhooks.
(Controls 16, 21, 22, 57, 58)
Step 06: Sprint 3 - Operate
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.domains.logistics.service import (
    LogisticsService, LogisticsError, ShipmentNotFoundError,
    InvalidShipmentStateError, CarrierNotFoundError
)
from src.backend.schemas.logistics import (
    ShipmentCreateRequest, ShipmentResponse, ShipmentTrackingEventResponse,
    DeliveryProofCreateRequest, DeliveryProofResponse,
    CarrierRateQuoteRequest, CarrierRateQuoteResponse
)

router = APIRouter(prefix="/logistics", tags=["Logistics & Fulfillment"])


# -----------------------------------------------------------------------------
# 1. SHIPMENTS LIFECYCLE
# -----------------------------------------------------------------------------
@router.post("/shipments", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
async def create_shipment(
    req: ShipmentCreateRequest,
    ctx: SecurityContext = Depends(require_permission("logistics:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = LogisticsService(db)
    items_data = [item.model_dump() for item in req.items]
    try:
        return await service.create_shipment(
            tenant_id=ctx.tenant_id,
            order_id=req.order_id,
            warehouse_id=req.warehouse_id,
            carrier_code=req.carrier_code,
            shipping_address=req.shipping_address_json,
            delivery_contact=req.delivery_contact_json,
            items_data=items_data,
            carrier_service=req.carrier_service,
            created_by_user_id=ctx.user_id
        )
    except LogisticsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/shipments", response_model=List[ShipmentResponse])
async def list_shipments(
    status_filter: Optional[str] = Query(None, alias="status"),
    order_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: SecurityContext = Depends(require_permission("logistics:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = LogisticsService(db)
    return await service.list_shipments(
        ctx.tenant_id, status=status_filter, order_id=order_id, limit=limit, offset=offset
    )


@router.get("/shipments/{shipment_id}", response_model=ShipmentResponse)
async def get_shipment(
    shipment_id: str,
    ctx: SecurityContext = Depends(require_permission("logistics:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = LogisticsService(db)
    try:
        return await service.get_shipment(ctx.tenant_id, shipment_id)
    except ShipmentNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/shipments/{shipment_id}/pick", response_model=ShipmentResponse)
async def start_picking(
    shipment_id: str,
    ctx: SecurityContext = Depends(require_permission("logistics:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = LogisticsService(db)
    try:
        return await service.start_picking(ctx.tenant_id, shipment_id)
    except ShipmentNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidShipmentStateError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/shipments/{shipment_id}/pack", response_model=ShipmentResponse)
async def complete_packing(
    shipment_id: str,
    ctx: SecurityContext = Depends(require_permission("logistics:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = LogisticsService(db)
    try:
        return await service.complete_packing(ctx.tenant_id, shipment_id)
    except ShipmentNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidShipmentStateError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/shipments/{shipment_id}/ship", response_model=ShipmentResponse)
async def dispatch_shipment(
    shipment_id: str,
    weight_grams: int = Query(1000, ge=100),
    ctx: SecurityContext = Depends(require_permission("logistics:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = LogisticsService(db)
    try:
        return await service.book_carrier_and_ship(ctx.tenant_id, shipment_id, weight_grams=weight_grams)
    except ShipmentNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (InvalidShipmentStateError, LogisticsError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/shipments/{shipment_id}/delivery-proof", response_model=DeliveryProofResponse, status_code=status.HTTP_201_CREATED)
async def attach_delivery_proof(
    shipment_id: str,
    req: DeliveryProofCreateRequest,
    ctx: SecurityContext = Depends(require_permission("logistics:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = LogisticsService(db)
    try:
        return await service.record_delivery_proof(
            tenant_id=ctx.tenant_id,
            shipment_id=shipment_id,
            recipient_name=req.recipient_name,
            signature_image_url=req.signature_image_url,
            photo_url=req.photo_url,
            location_coordinates=req.location_coordinates
        )
    except ShipmentNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# -----------------------------------------------------------------------------
# 2. MULTI-CARRIER RATE QUOTES
# -----------------------------------------------------------------------------
@router.post("/rates/quotes", response_model=List[CarrierRateQuoteResponse])
async def get_carrier_quotes(
    req: CarrierRateQuoteRequest,
    ctx: SecurityContext = Depends(require_permission("logistics:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = LogisticsService(db)
    origin_address = {"warehouse_id": req.warehouse_id}
    destination_address = {
        "postal_code": req.destination_postal_code,
        "city": req.destination_city,
        "country": req.destination_country
    }
    weight_grams = int(req.weight_kg * 1000)
    quotes = await service.get_multi_carrier_quotes(
        origin_address=origin_address,
        destination_address=destination_address,
        weight_grams=weight_grams
    )
    return [
        CarrierRateQuoteResponse(
            carrier_code=q.carrier_code,
            carrier_service=q.carrier_service,
            currency=q.currency,
            shipping_cost_cents=q.cost_cents,
            estimated_transit_days=q.estimated_transit_days
        )
        for q in quotes
    ]


# -----------------------------------------------------------------------------
# 3. CARRIER WEBHOOK (MONOTONIC UPDATES + HMAC SIGNATURE)
# -----------------------------------------------------------------------------
@router.post("/webhooks/carrier/{carrier_code}", response_model=List[ShipmentTrackingEventResponse])
async def carrier_tracking_webhook(
    carrier_code: str,
    request: Request,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Receives carrier status updates, validates HMAC signature, and enforces
    monotonic progression (out-of-order/late callbacks cannot regress status).
    """
    raw_body = await request.body()
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON webhook body.")

    headers = dict(request.headers)
    service = LogisticsService(db)

    # Use tenant's carrier webhook secret (or default testing secret)
    secret = "amana_webhook_secret_default" if carrier_code.upper() == "AMANA" else "simulated_webhook_secret_default"

    try:
        return await service.process_carrier_webhook(
            tenant_id=x_tenant_id,
            carrier_code=carrier_code,
            headers=headers,
            raw_body=raw_body,
            payload=payload,
            secret=secret
        )
    except ShipmentNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except LogisticsError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
