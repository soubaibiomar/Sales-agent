"""
Catalog & Price Lists API Endpoints.
(Baseline Controls 16, 17, 33, 51)
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.domains.catalog.service import CatalogService, CatalogDomainError, ProductNotFoundError
from src.backend.schemas.catalog import (
    ProductCreate, ProductResponse,
    ProductVariantCreate, ProductVariantResponse,
    PriceListCreate, PriceListResponse,
    PriceListItemCreate, PriceListItemResponse
)

router = APIRouter(prefix="/catalog", tags=["Products & Price Lists"])

# -----------------------------------------------------------------------------
# 1. PRODUCTS
# -----------------------------------------------------------------------------
@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    req: ProductCreate,
    context: SecurityContext = Depends(require_permission("catalog:write")),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        p = await CatalogService.create_product(
            session=db,
            tenant_id=context.tenant_id,
            sku=req.sku,
            name=req.name,
            base_price_cents=req.base_price_cents,
            cost_cents=req.cost_cents,
            currency=req.currency,
            tax_rate_percent=req.tax_rate_percent,
            min_margin_percent=req.min_margin_percent,
            product_type=req.product_type,
            uom=req.uom,
            category=req.category,
            description=req.description
        )
        return p
    except CatalogDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("/products", response_model=List[ProductResponse])
async def list_products(
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    context: SecurityContext = Depends(require_permission("catalog:read")),
    db: AsyncSession = Depends(get_db_session)
):
    return await CatalogService.list_products(db, context.tenant_id, category=category, is_active=is_active, limit=limit, offset=offset)

@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    context: SecurityContext = Depends(require_permission("catalog:read")),
    db: AsyncSession = Depends(get_db_session)
):
    p = await CatalogService.get_product(db, context.tenant_id, product_id)
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return p

@router.post("/products/{product_id}/variants", response_model=ProductVariantResponse, status_code=status.HTTP_201_CREATED)
async def create_variant(
    product_id: str,
    req: ProductVariantCreate,
    context: SecurityContext = Depends(require_permission("catalog:write")),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        v = await CatalogService.create_variant(
            session=db,
            tenant_id=context.tenant_id,
            product_id=product_id,
            sku_variant=req.sku_variant,
            name=req.name,
            price_adjustment_cents=req.price_adjustment_cents,
            cost_adjustment_cents=req.cost_adjustment_cents
        )
        return v
    except ProductNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except CatalogDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

# -----------------------------------------------------------------------------
# 2. PRICE LISTS
# -----------------------------------------------------------------------------
@router.post("/price-lists", response_model=PriceListResponse, status_code=status.HTTP_201_CREATED)
@router.post("/pricelists", response_model=PriceListResponse, status_code=status.HTTP_201_CREATED)
async def create_price_list(
    req: PriceListCreate,
    context: SecurityContext = Depends(require_permission("catalog:write")),
    db: AsyncSession = Depends(get_db_session)
):
    pl = await CatalogService.create_price_list(
        session=db,
        tenant_id=context.tenant_id,
        name=req.name,
        code=req.code,
        currency=req.currency,
        description=req.description,
        is_default=req.is_default,
        valid_from=req.valid_from,
        valid_to=req.valid_to
    )
    return pl

@router.get("/price-lists/{price_list_id}", response_model=PriceListResponse)
@router.get("/pricelists/{price_list_id}", response_model=PriceListResponse)
async def get_price_list(
    price_list_id: str,
    context: SecurityContext = Depends(require_permission("catalog:read")),
    db: AsyncSession = Depends(get_db_session)
):
    pl = await CatalogService.get_price_list(db, context.tenant_id, price_list_id)
    if not pl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Price list not found")
    return pl

@router.post("/price-lists/{price_list_id}/items", response_model=PriceListItemResponse, status_code=status.HTTP_201_CREATED)
@router.post("/pricelists/{price_list_id}/items", response_model=PriceListItemResponse, status_code=status.HTTP_201_CREATED)
async def set_price_list_item(
    price_list_id: str,
    req: PriceListItemCreate,
    context: SecurityContext = Depends(require_permission("catalog:write")),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        pli = await CatalogService.set_price_list_item(
            session=db,
            tenant_id=context.tenant_id,
            price_list_id=price_list_id,
            product_id=req.product_id,
            unit_price_cents=req.unit_price_cents,
            variant_id=req.variant_id,
            min_quantity=req.min_quantity
        )
        return pli
    except CatalogDomainError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
