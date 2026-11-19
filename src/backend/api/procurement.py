"""
Procurement & Multi-Warehouse REST API Endpoints.
Suppliers, Supplier Catalogs, RFQs, Purchase Orders, Goods Receipts with Over-Receipt Protection,
and Inter-Warehouse Stock Transfers.
(Controls 05, 06, 07, 16, 21, 22, 33, 34, 48, 57, 58)
Step 06: Sprint 3 - Operate
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.domains.procurement.service import (
    ProcurementService, ProcurementError, SupplierNotFoundError,
    RFQNotFoundError, PurchaseOrderNotFoundError, OverReceiptError,
    InvalidPOStateTransitionError, StockTransferNotFoundError, InsufficientTransferStockError
)
from src.backend.schemas.procurement import (
    SupplierCreate, SupplierResponse,
    SupplierProductCreate, SupplierProductResponse,
    RFQCreateRequest, RFQResponse,
    PurchaseOrderCreateRequest, PurchaseOrderResponse,
    GoodsReceiptCreateRequest, GoodsReceiptResponse,
    StockTransferCreateRequest, StockTransferResponse
)

router = APIRouter(prefix="/procurement", tags=["Procurement & Multi-Warehouse"])


# -----------------------------------------------------------------------------
# 1. SUPPLIERS
# -----------------------------------------------------------------------------
@router.post("/suppliers", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    req: SupplierCreate,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    supplier = await service.create_supplier(
        tenant_id=ctx.tenant_id,
        supplier_code=req.supplier_code,
        name=req.name,
        contact_name=req.contact_name,
        email=req.email,
        phone=req.phone,
        payment_terms=req.payment_terms,
        currency=req.currency,
        address_json=req.address_json
    )
    return supplier


@router.get("/suppliers", response_model=List[SupplierResponse])
async def list_suppliers(
    active_only: bool = True,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: SecurityContext = Depends(require_permission("procurement:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    return await service.list_suppliers(ctx.tenant_id, active_only=active_only, limit=limit, offset=offset)


@router.get("/suppliers/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(
    supplier_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.get_supplier(ctx.tenant_id, supplier_id)
    except SupplierNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/suppliers/{supplier_id}/products", response_model=SupplierProductResponse, status_code=status.HTTP_201_CREATED)
async def add_supplier_product(
    supplier_id: str,
    req: SupplierProductCreate,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.add_supplier_product(
            tenant_id=ctx.tenant_id,
            supplier_id=supplier_id,
            product_id=req.product_id,
            sku=req.sku,
            unit_cost_cents=req.unit_cost_cents,
            supplier_sku=req.supplier_sku,
            currency=req.currency,
            lead_time_days=req.lead_time_days,
            min_order_quantity=req.min_order_quantity
        )
    except SupplierNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/suppliers/{supplier_id}/products", response_model=List[SupplierProductResponse])
async def list_supplier_products(
    supplier_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    return await service.list_supplier_products(ctx.tenant_id, supplier_id)


# -----------------------------------------------------------------------------
# 2. RFQ
# -----------------------------------------------------------------------------
@router.post("/rfqs", response_model=RFQResponse, status_code=status.HTTP_201_CREATED)
async def create_rfq(
    req: RFQCreateRequest,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    items_data = [item.model_dump() for item in req.items]
    return await service.create_rfq(
        tenant_id=ctx.tenant_id,
        supplier_id=req.supplier_id,
        items_data=items_data,
        deadline_date=req.deadline_date,
        notes=req.notes,
        created_by_user_id=ctx.user_id
    )


@router.get("/rfqs", response_model=List[RFQResponse])
async def list_rfqs(
    status_filter: Optional[str] = Query(None, alias="status"),
    supplier_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: SecurityContext = Depends(require_permission("procurement:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    return await service.list_rfqs(
        ctx.tenant_id, status=status_filter, supplier_id=supplier_id, limit=limit, offset=offset
    )


@router.get("/rfqs/{rfq_id}", response_model=RFQResponse)
async def get_rfq(
    rfq_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.get_rfq(ctx.tenant_id, rfq_id)
    except RFQNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/rfqs/{rfq_id}/send", response_model=RFQResponse)
async def send_rfq(
    rfq_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.send_rfq(ctx.tenant_id, rfq_id)
    except RFQNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# -----------------------------------------------------------------------------
# 3. PURCHASE ORDERS
# -----------------------------------------------------------------------------
@router.post("/purchase-orders", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    req: PurchaseOrderCreateRequest,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    items_data = [item.model_dump() for item in req.items]
    return await service.create_purchase_order(
        tenant_id=ctx.tenant_id,
        supplier_id=req.supplier_id,
        warehouse_id=req.warehouse_id,
        items_data=items_data,
        currency=req.currency,
        payment_terms=req.payment_terms,
        notes=req.notes,
        rfq_id=req.rfq_id,
        expected_delivery_date=req.expected_delivery_date,
        created_by_user_id=ctx.user_id
    )


@router.get("/purchase-orders", response_model=List[PurchaseOrderResponse])
async def list_purchase_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    supplier_id: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: SecurityContext = Depends(require_permission("procurement:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    return await service.list_purchase_orders(
        ctx.tenant_id, status=status_filter, supplier_id=supplier_id,
        warehouse_id=warehouse_id, limit=limit, offset=offset
    )


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderResponse)
async def get_purchase_order(
    po_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.get_purchase_order(ctx.tenant_id, po_id)
    except PurchaseOrderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/purchase-orders/{po_id}/approve", response_model=PurchaseOrderResponse)
async def approve_purchase_order(
    po_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.approve_purchase_order(ctx.tenant_id, po_id, approved_by_user_id=ctx.user_id)
    except PurchaseOrderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidPOStateTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/purchase-orders/{po_id}/issue", response_model=PurchaseOrderResponse)
async def issue_purchase_order(
    po_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.issue_purchase_order(ctx.tenant_id, po_id)
    except PurchaseOrderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidPOStateTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# -----------------------------------------------------------------------------
# 4. GOODS RECEIPTS WITH OVER-RECEIPT REJECTION
# -----------------------------------------------------------------------------
@router.post("/goods-receipts", response_model=GoodsReceiptResponse, status_code=status.HTTP_201_CREATED)
async def record_goods_receipt(
    req: GoodsReceiptCreateRequest,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    items_data = [item.model_dump() for item in req.items]
    try:
        return await service.record_goods_receipt(
            tenant_id=ctx.tenant_id,
            purchase_order_id=req.purchase_order_id,
            warehouse_id=req.warehouse_id,
            items_data=items_data,
            carrier_name=req.carrier_name,
            tracking_reference=req.tracking_reference,
            notes=req.notes,
            received_by_user_id=ctx.user_id
        )
    except OverReceiptError as e:
        # Invariant: Over-receipt must be strictly rejected
        raise HTTPException(status_code=422, detail=str(e))
    except (PurchaseOrderNotFoundError, ProcurementError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/goods-receipts", response_model=List[GoodsReceiptResponse])
async def list_goods_receipts(
    purchase_order_id: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: SecurityContext = Depends(require_permission("procurement:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    return await service.list_goods_receipts(
        ctx.tenant_id, purchase_order_id=purchase_order_id,
        warehouse_id=warehouse_id, limit=limit, offset=offset
    )


@router.get("/goods-receipts/{receipt_id}", response_model=GoodsReceiptResponse)
async def get_goods_receipt(
    receipt_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.get_goods_receipt(ctx.tenant_id, receipt_id)
    except ProcurementError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# -----------------------------------------------------------------------------
# 5. INTER-WAREHOUSE STOCK TRANSFERS
# -----------------------------------------------------------------------------
@router.post("/transfers", response_model=StockTransferResponse, status_code=status.HTTP_201_CREATED)
async def create_stock_transfer(
    req: StockTransferCreateRequest,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    items_data = [item.model_dump() for item in req.items]
    try:
        return await service.create_stock_transfer(
            tenant_id=ctx.tenant_id,
            source_warehouse_id=req.source_warehouse_id,
            destination_warehouse_id=req.destination_warehouse_id,
            items_data=items_data,
            notes=req.notes,
            created_by_user_id=ctx.user_id
        )
    except ProcurementError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/transfers", response_model=List[StockTransferResponse])
async def list_stock_transfers(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ctx: SecurityContext = Depends(require_permission("procurement:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    return await service.list_stock_transfers(
        ctx.tenant_id, status=status_filter, limit=limit, offset=offset
    )


@router.get("/transfers/{transfer_id}", response_model=StockTransferResponse)
async def get_stock_transfer(
    transfer_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:read")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.get_stock_transfer(ctx.tenant_id, transfer_id)
    except StockTransferNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/transfers/{transfer_id}/approve", response_model=StockTransferResponse)
async def approve_stock_transfer(
    transfer_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.approve_stock_transfer(ctx.tenant_id, transfer_id)
    except StockTransferNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ProcurementError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/transfers/{transfer_id}/ship", response_model=StockTransferResponse)
async def ship_stock_transfer(
    transfer_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.ship_stock_transfer(ctx.tenant_id, transfer_id)
    except InsufficientTransferStockError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except StockTransferNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ProcurementError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/transfers/{transfer_id}/receive", response_model=StockTransferResponse)
async def receive_stock_transfer(
    transfer_id: str,
    ctx: SecurityContext = Depends(require_permission("procurement:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = ProcurementService(db)
    try:
        return await service.receive_stock_transfer(ctx.tenant_id, transfer_id)
    except StockTransferNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ProcurementError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
