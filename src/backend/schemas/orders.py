"""
Pydantic schemas for Sales Orders and Order Items.
Step 05: Sprint 3 - Transact
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class OrderItemRequest(BaseModel):
    sku: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    uom: str = "UNIT"
    unit_price_cents: int = Field(..., ge=0)
    unit_cost_cents: int = Field(0, ge=0)
    discount_percent: float = Field(0.0, ge=0.0, le=100.0)
    tax_rate_percent: float = Field(20.0, ge=0.0, le=100.0)
    product_id: Optional[str] = None
    variant_id: Optional[str] = None


class OrderItemResponse(BaseModel):
    id: str
    tenant_id: str
    order_id: str
    product_id: Optional[str] = None
    variant_id: Optional[str] = None
    sku: str
    name: str
    quantity: int
    uom: str
    unit_price_cents: int
    unit_cost_cents: int
    discount_percent: float
    discount_cents: int
    tax_rate_percent: float
    tax_cents: int
    subtotal_cents: int
    total_cents: int
    fulfillment_status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderCreateRequest(BaseModel):
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    currency: str = Field("USD", min_length=3, max_length=10)
    items: List[OrderItemRequest] = Field(..., min_length=1)
    shipping_address_json: Optional[str] = "{}"
    billing_address_json: Optional[str] = "{}"
    idempotency_key: Optional[str] = None


class QuoteAcceptOrderRequest(BaseModel):
    quote_id: str
    expected_quote_version: int
    shipping_address_json: Optional[str] = "{}"
    billing_address_json: Optional[str] = "{}"
    idempotency_key: Optional[str] = None


class OrderResponse(BaseModel):
    id: str
    tenant_id: str
    order_number: str
    quote_id: Optional[str] = None
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    status: str
    version: int
    currency: str
    subtotal_cents: int
    discount_total_cents: int
    tax_total_cents: int
    grand_total_cents: int
    terms_hash: str
    payment_status: str
    fulfillment_status: str
    shipping_address_json: str
    billing_address_json: str
    idempotency_key: Optional[str] = None
    created_by_user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class OrderCancelRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=255)
    expected_version: int
