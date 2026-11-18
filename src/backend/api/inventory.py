"""
Inventory API Endpoints.
Warehouses, Stock Tracking, Available-To-Promise, and Stock Holds.
Step 05: Sprint 3 - Transact
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.domains.inventory.service import (
    InventoryService, InventoryError, InsufficientStockError, ReservationNotFoundError
)
from src.backend.schemas.inventory import (
    WarehouseCreateRequest, WarehouseResponse,
    InventoryItemCreateRequest, InventoryItemAdjustRequest, InventoryItemResponse,
    StockReservationRequest, StockReservationResponse, StockMovementResponse
)

router = APIRouter(prefix="/inventory", tags=["Inventory & Warehouses"])


@router.post("/warehouses", response_model=WarehouseResponse, status_code=status.HTTP_201_CREATED)
async def create_warehouse(
    req: WarehouseCreateRequest,
    ctx: SecurityContext = Depends(require_permission("inventory:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InventoryService(db)
    warehouse = await service.create_warehouse(
        tenant_id=ctx.tenant_id,
        code=req.code,
        name=req.name,
        address_json=req.address_json or "{}"
    )
    return warehouse


@router.get("/warehouses", response_model=List[WarehouseResponse])
async def list_warehouses(
    ctx: SecurityContext = Depends(require_permission("catalog:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InventoryService(db)
    return await service.list_warehouses(tenant_id=ctx.tenant_id)


@router.post("/items", response_model=InventoryItemResponse, status_code=status.HTTP_201_CREATED)
async def get_or_create_inventory_item(
    req: InventoryItemCreateRequest,
    ctx: SecurityContext = Depends(require_permission("inventory:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InventoryService(db)
    item = await service.get_or_create_inventory_item(
        tenant_id=ctx.tenant_id,
        warehouse_id=req.warehouse_id,
        sku=req.sku,
        product_id=req.product_id,
        variant_id=req.variant_id,
        initial_on_hand=req.initial_on_hand,
        backorder_allowed=req.backorder_allowed
    )
    return item


@router.post("/items/{item_id}/adjust", response_model=InventoryItemResponse)
async def adjust_stock(
    item_id: str,
    req: InventoryItemAdjustRequest,
    ctx: SecurityContext = Depends(require_permission("inventory:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InventoryService(db)
    try:
        item = await service.adjust_stock(
            tenant_id=ctx.tenant_id,
            inventory_item_id=item_id,
            quantity_delta=req.quantity_delta,
            movement_type=req.movement_type,
            reference_type=req.reference_type,
            reference_id=req.reference_id,
            notes=req.notes,
            user_id=ctx.user_id
        )
        return item
    except InventoryError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/items", response_model=List[InventoryItemResponse])
async def list_inventory_items(
    warehouse_id: Optional[str] = None,
    sku: Optional[str] = None,
    ctx: SecurityContext = Depends(require_permission("catalog:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InventoryService(db)
    return await service.get_inventory_items(
        tenant_id=ctx.tenant_id,
        warehouse_id=warehouse_id,
        sku=sku
    )


@router.post("/reservations", response_model=StockReservationResponse, status_code=status.HTTP_201_CREATED)
async def reserve_stock(
    req: StockReservationRequest,
    ctx: SecurityContext = Depends(require_permission("quotes:create")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InventoryService(db)
    try:
        reservation = await service.reserve_stock(
            tenant_id=ctx.tenant_id,
            sku=req.sku,
            quantity=req.quantity,
            warehouse_id=req.warehouse_id,
            order_id=req.order_id,
            quote_id=req.quote_id,
            duration_seconds=req.hold_duration_seconds,
            idempotency_key=req.idempotency_key
        )
        return reservation
    except InsufficientStockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except InventoryError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/reservations/{reservation_id}/release", response_model=StockReservationResponse)
async def release_reservation(
    reservation_id: str,
    ctx: SecurityContext = Depends(require_permission("quotes:create")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InventoryService(db)
    try:
        return await service.release_reservation(
            tenant_id=ctx.tenant_id,
            reservation_id=reservation_id,
            reason="MANUAL_RELEASE"
        )
    except ReservationNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    except InventoryError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/expire-reservations")
async def expire_stale_reservations(
    ctx: SecurityContext = Depends(require_permission("inventory:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InventoryService(db)
    count = await service.expire_stale_reservations(tenant_id=ctx.tenant_id)
    return {"status": "ok", "expired_count": count}


@router.get("/movements", response_model=List[StockMovementResponse])
async def list_stock_movements(
    inventory_item_id: Optional[str] = None,
    ctx: SecurityContext = Depends(require_permission("catalog:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = InventoryService(db)
    return await service.get_stock_movements(
        tenant_id=ctx.tenant_id,
        inventory_item_id=inventory_item_id
    )
