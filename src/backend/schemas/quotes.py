"""
Quotation Pydantic Schemas.
(Baseline Controls 15, 16, 51, 58)
"""
from decimal import Decimal
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class QuoteItemRequest(BaseModel):
    product_id: str
    variant_id: Optional[str] = None
    quantity: int = Field(..., ge=1)
    discount_percent: Decimal = Field(default=Decimal("0.00"), ge=0, le=100)

class QuoteCreateRequest(BaseModel):
    opportunity_id: Optional[str] = None
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    price_list_id: Optional[str] = None
    currency: str = Field(default="MAD", max_length=10)
    payment_terms: str = Field(default="NET_30", max_length=100)
    valid_days: int = Field(default=30, ge=1, le=365)
    notes: Optional[str] = None

class QuoteUpdateRequest(BaseModel):
    items: List[QuoteItemRequest] = Field(..., min_length=1)
    payment_terms: Optional[str] = None
    expected_version: Optional[int] = None

class QuoteItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    quote_id: str
    product_id: Optional[str] = None
    variant_id: Optional[str] = None
    sku_snapshot: str
    name_snapshot: str
    quantity: int
    uom_snapshot: str
    unit_price_cents: int
    unit_cost_cents: int
    discount_percent: Decimal
    discount_cents: int
    tax_rate_percent: Decimal
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    margin_percent: Decimal

class QuoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    quote_number: str
    opportunity_id: Optional[str] = None
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    price_list_id: Optional[str] = None
    currency: str
    status: str
    version: int
    subtotal_cents: int
    discount_total_cents: int
    tax_total_cents: int
    grand_total_cents: int
    margin_percent: Decimal
    requires_approval: bool
    approval_reason: Optional[str] = None
    terms_hash: str
    valid_until: datetime
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    issued_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    created_by_user_id: Optional[str] = None
    items: List[QuoteItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class QuoteSendRequest(BaseModel):
    recipient_identifier: str = Field(..., min_length=1)
    channel_type: str = Field(default="EMAIL")

class QuoteAcceptRequest(BaseModel):
    acceptance_token: str  # signed link token issued when the quote was sent (F-14)
    signature_or_note: Optional[str] = None

class QuoteRejectRequest(BaseModel):
    acceptance_token: str  # same signed link token as for acceptance (F-14)
    reason: Optional[str] = None
