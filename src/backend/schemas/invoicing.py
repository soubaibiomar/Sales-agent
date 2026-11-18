"""
Pydantic schemas for Invoicing and Credit Notes.
Step 05: Sprint 3 - Transact
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class InvoiceItemResponse(BaseModel):
    id: str
    tenant_id: str
    invoice_id: str
    sku: str
    name: str
    quantity: int
    unit_price_cents: int
    discount_cents: int
    tax_rate_percent: float
    tax_cents: int
    subtotal_cents: int
    total_cents: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InvoiceCreateRequest(BaseModel):
    order_id: str
    due_days: int = Field(30, ge=0, le=365)
    notes: Optional[str] = None


class InvoiceResponse(BaseModel):
    id: str
    tenant_id: str
    order_id: str
    invoice_number: str
    status: str
    currency: str
    subtotal_cents: int
    discount_total_cents: int
    tax_total_cents: int
    grand_total_cents: int
    terms_hash: str
    invoice_hash: str
    correction_of_invoice_id: Optional[str] = None
    issued_at: datetime
    due_date: datetime
    paid_at: Optional[datetime] = None
    pdf_storage_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: List[InvoiceItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class CreditNoteCreateRequest(BaseModel):
    original_invoice_id: str
    reason: str = Field(..., min_length=1, max_length=255)
    amount_cents: Optional[int] = Field(None, gt=0, description="Leave None for full credit note")
