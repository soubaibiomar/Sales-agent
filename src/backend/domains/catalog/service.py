"""
Product and Service Catalog Domain Service.
Manages Products, SKU Variants, Units of Measure (UOM), and Price Lists.
(Baseline Controls 16, 17, 33)
"""
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.models.entities import (
    Product, ProductVariant, PriceList, PriceListItem
)

VALID_UOMS = {"UNIT", "HOUR", "DAY", "KG", "METER", "BOX", "PACK", "MONTH", "YEAR"}
VALID_PRODUCT_TYPES = {"PHYSICAL", "SERVICE", "SUBSCRIPTION"}

class CatalogDomainError(Exception):
    pass

class ProductNotFoundError(CatalogDomainError):
    pass

class PriceListNotFoundError(CatalogDomainError):
    pass

class CatalogService:
    """Enterprise domain service for product catalog, SKU variants, and price lists."""

    # -------------------------------------------------------------------------
    # 1. Products Management
    # -------------------------------------------------------------------------
    @staticmethod
    async def create_product(
        session: AsyncSession,
        tenant_id: str,
        sku: str,
        name: str,
        base_price_cents: int,
        cost_cents: int = 0,
        currency: str = "MAD",
        tax_rate_percent: Decimal = Decimal("20.00"),
        min_margin_percent: Decimal = Decimal("15.00"),
        product_type: str = "PHYSICAL",
        uom: str = "UNIT",
        category: Optional[str] = None,
        description: Optional[str] = None,
        metadata_json: Optional[str] = "{}"
    ) -> Product:
        clean_sku = sku.strip().upper()
        if not clean_sku:
            raise CatalogDomainError("Product SKU cannot be empty")
        if base_price_cents < 0:
            raise CatalogDomainError("Product base price cannot be negative")
        if cost_cents < 0:
            raise CatalogDomainError("Product cost cannot be negative")

        clean_type = product_type.upper()
        if clean_type not in VALID_PRODUCT_TYPES:
            raise CatalogDomainError(f"Invalid product type '{product_type}'. Valid: {VALID_PRODUCT_TYPES}")

        clean_uom = uom.upper()
        if clean_uom not in VALID_UOMS:
            raise CatalogDomainError(f"Invalid Unit of Measure (UOM) '{uom}'. Valid: {VALID_UOMS}")

        product = Product(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            sku=clean_sku,
            name=name.strip(),
            description=description,
            product_type=clean_type,
            uom=clean_uom,
            category=category.strip() if category else None,
            base_price_cents=base_price_cents,
            cost_cents=cost_cents,
            currency=currency.upper(),
            tax_rate_percent=tax_rate_percent,
            min_margin_percent=min_margin_percent,
            is_active=True,
            metadata_json=metadata_json or "{}"
        )
        session.add(product)
        await session.flush()
        return product

    @staticmethod
    async def get_product(
        session: AsyncSession,
        tenant_id: str,
        product_id_or_sku: str
    ) -> Optional[Product]:
        stmt = select(Product).where(
            Product.tenant_id == tenant_id,
            (Product.id == product_id_or_sku) | (Product.sku == product_id_or_sku.upper())
        )
        res = await session.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def list_products(
        session: AsyncSession,
        tenant_id: str,
        category: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Product]:
        stmt = select(Product).where(Product.tenant_id == tenant_id)
        if category:
            stmt = stmt.where(Product.category == category)
        if is_active is not None:
            stmt = stmt.where(Product.is_active == is_active)
        stmt = stmt.order_by(Product.name.asc()).limit(limit).offset(offset)
        res = await session.execute(stmt)
        return list(res.scalars().all())

    # -------------------------------------------------------------------------
    # 2. Variants Management
    # -------------------------------------------------------------------------
    @staticmethod
    async def create_variant(
        session: AsyncSession,
        tenant_id: str,
        product_id: str,
        sku_variant: str,
        name: str,
        price_adjustment_cents: int = 0,
        cost_adjustment_cents: int = 0,
        attributes_json: Optional[str] = "{}"
    ) -> ProductVariant:
        product = await CatalogService.get_product(session, tenant_id, product_id)
        if not product:
            raise ProductNotFoundError(f"Product '{product_id}' not found in tenant")

        variant = ProductVariant(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            product_id=product.id,
            sku_variant=sku_variant.strip().upper(),
            name=name.strip(),
            attributes_json=attributes_json or "{}",
            price_adjustment_cents=price_adjustment_cents,
            cost_adjustment_cents=cost_adjustment_cents,
            is_active=True
        )
        session.add(variant)
        await session.flush()
        return variant

    # -------------------------------------------------------------------------
    # 3. Price Lists Management
    # -------------------------------------------------------------------------
    @staticmethod
    async def create_price_list(
        session: AsyncSession,
        tenant_id: str,
        name: str,
        code: str,
        currency: str = "MAD",
        description: Optional[str] = None,
        is_default: bool = False,
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None
    ) -> PriceList:
        price_list = PriceList(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=name.strip(),
            code=code.strip().upper(),
            currency=currency.upper(),
            description=description,
            is_default=is_default,
            is_active=True,
            valid_from=valid_from,
            valid_to=valid_to
        )
        session.add(price_list)
        await session.flush()
        return price_list

    @staticmethod
    async def get_price_list(
        session: AsyncSession,
        tenant_id: str,
        price_list_id_or_code: str
    ) -> Optional[PriceList]:
        stmt = select(PriceList).where(
            PriceList.tenant_id == tenant_id,
            (PriceList.id == price_list_id_or_code) | (PriceList.code == price_list_id_or_code.upper())
        )
        res = await session.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def set_price_list_item(
        session: AsyncSession,
        tenant_id: str,
        price_list_id: str,
        product_id: str,
        unit_price_cents: int,
        variant_id: Optional[str] = None,
        min_quantity: int = 1
    ) -> PriceListItem:
        if unit_price_cents < 0:
            raise CatalogDomainError("Price list item price cannot be negative")
        if min_quantity < 1:
            raise CatalogDomainError("Minimum quantity must be at least 1")

        item = PriceListItem(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            price_list_id=price_list_id,
            product_id=product_id,
            variant_id=variant_id,
            unit_price_cents=unit_price_cents,
            min_quantity=min_quantity
        )
        session.add(item)
        await session.flush()
        return item

    @staticmethod
    async def resolve_unit_price(
        session: AsyncSession,
        tenant_id: str,
        product_id: str,
        variant_id: Optional[str] = None,
        price_list_id: Optional[str] = None,
        quantity: int = 1
    ) -> int:
        """Resolves unit price in cents factoring in price lists and quantity tiers."""
        product = await CatalogService.get_product(session, tenant_id, product_id)
        if not product:
            raise ProductNotFoundError(f"Product '{product_id}' not found")

        unit_price = product.base_price_cents

        if price_list_id:
            stmt = select(PriceListItem).where(
                PriceListItem.tenant_id == tenant_id,
                PriceListItem.price_list_id == price_list_id,
                PriceListItem.product_id == product.id,
                PriceListItem.min_quantity <= quantity
            ).order_by(PriceListItem.min_quantity.desc())
            if variant_id:
                stmt = stmt.where((PriceListItem.variant_id == variant_id) | (PriceListItem.variant_id.is_(None)))
            res = await session.execute(stmt)
            pli = res.scalars().first()
            if pli:
                unit_price = pli.unit_price_cents

        if variant_id and not (price_list_id and pli and pli.variant_id == variant_id):
            v = await CatalogService.get_variant(session, tenant_id, variant_id)
            if v and v.price_adjustment_cents:
                unit_price += v.price_adjustment_cents

        return unit_price
