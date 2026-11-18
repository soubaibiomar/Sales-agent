"""
Catalog & Price Lists Pydantic Schemas.
(Baseline Controls 15, 16, 51)
"""
from decimal import Decimal
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    product_type: str = Field(default="PHYSICAL", max_length=50)
    uom: str = Field(default="UNIT", max_length=50)
    category: Optional[str] = None
    base_price_cents: int = Field(..., ge=0)
    cost_cents: int = Field(default=0, ge=0)
    currency: str = Field(default="MAD", max_length=10)
    tax_rate_percent: Decimal = Field(default=Decimal("20.00"), ge=0, le=100)
    min_margin_percent: Decimal = Field(default=Decimal("15.00"), ge=0, le=100)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    sku: str
    name: str
    description: Optional[str] = None
    product_type: str
    uom: str
    category: Optional[str] = None
    base_price_cents: int
    cost_cents: int
    currency: str
    tax_rate_percent: Decimal
    min_margin_percent: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

class ProductVariantCreate(BaseModel):
    sku_variant: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    price_adjustment_cents: int = Field(default=0)
    cost_adjustment_cents: int = Field(default=0)
    attributes: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ProductVariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    product_id: str
    sku_variant: str
    name: str
    price_adjustment_cents: int
    cost_adjustment_cents: int
    is_active: bool
    created_at: datetime

class PriceListCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=1, max_length=50)
    currency: str = Field(default="MAD", max_length=10)
    description: Optional[str] = None
    is_default: bool = False
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

class PriceListItemCreate(BaseModel):
    product_id: str
    unit_price_cents: int = Field(..., ge=0)
    variant_id: Optional[str] = None
    min_quantity: int = Field(default=1, ge=1)

class PriceListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    price_list_id: str
    product_id: str
    variant_id: Optional[str] = None
    unit_price_cents: int
    min_quantity: int
    created_at: datetime

class PriceListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    code: str
    currency: str
    description: Optional[str] = None
    is_default: bool
    is_active: bool
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
