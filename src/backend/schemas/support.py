"""
Support Tickets, Warranties & Return Authorizations (RMA) Pydantic Schemas.
Step 06: Sprint 3 - Operate
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# 1. Support Tickets
class TicketMessageCreateRequest(BaseModel):
    sender_type: str = Field("CUSTOMER", max_length=20)  # CUSTOMER, AGENT, SYSTEM
    message_text: str = Field(..., min_length=1)
    attachments_json: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class TicketMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    ticket_id: str
    sender_type: str
    sender_user_id: Optional[str] = None
    message_text: str
    attachments_json: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class SupportTicketCreateRequest(BaseModel):
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    order_id: Optional[str] = None
    priority: str = Field("MEDIUM", max_length=20)  # LOW, MEDIUM, HIGH, URGENT
    category: str = Field("GENERAL", max_length=50)  # SHIPPING_DELAY, DAMAGED_GOODS, WARRANTY_CLAIM, BILLING, GENERAL
    subject: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)


class SupportTicketUpdateRequest(BaseModel):
    status: Optional[str] = None  # OPEN, IN_PROGRESS, PENDING_CUSTOMER, RESOLVED, CLOSED
    priority: Optional[str] = None
    assigned_user_id: Optional[str] = None


class SupportTicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    ticket_number: str
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    order_id: Optional[str] = None
    priority: str
    category: str
    status: str
    subject: str
    description: str
    assigned_user_id: Optional[str] = None
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    messages: List[TicketMessageResponse] = Field(default_factory=list)


# 2. Warranty Claims
class WarrantyClaimCreateRequest(BaseModel):
    order_id: str
    order_item_id: str
    sku: str
    serial_number: Optional[str] = None
    ticket_id: Optional[str] = None
    claim_reason: str = Field(..., min_length=1)


class WarrantyClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    claim_number: str
    order_id: str
    order_item_id: str
    ticket_id: Optional[str] = None
    sku: str
    serial_number: Optional[str] = None
    status: str
    warranty_valid_until: datetime
    claim_reason: str
    inspection_notes: Optional[str] = None
    resolved_by_user_id: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# 3. Return Authorizations (RMA)
class ReturnItemRequest(BaseModel):
    order_item_id: str
    sku: str
    quantity_requested: int = Field(..., ge=1)
    condition: Optional[str] = Field("UNOPENED", max_length=50)


class ReturnAuthorizationCreateRequest(BaseModel):
    order_id: str
    ticket_id: Optional[str] = None
    reason: str = Field(..., min_length=1)
    requested_action: str = Field("REFUND", max_length=30)  # REFUND, REPLACEMENT, STORE_CREDIT
    destination_warehouse_id: Optional[str] = None
    items: List[ReturnItemRequest] = Field(..., min_length=1)


class ReturnItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    rma_id: str
    order_item_id: str
    sku: str
    quantity_requested: int
    quantity_received: int
    condition: Optional[str] = None
    created_at: datetime


class ReturnInspectionRequest(BaseModel):
    inspection_outcome: str = Field(..., max_length=30)  # RESTOCK, QUARANTINE, SCRAP, REJECT
    inspection_notes: str = Field(..., min_length=1)
    quantity_received_map: Dict[str, int] = Field(..., description="Map of return_item_id -> quantity_received")
    refund_amount_cents: Optional[int] = Field(0, ge=0)


class ReturnAuthorizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    rma_number: str
    order_id: str
    ticket_id: Optional[str] = None
    status: str
    reason: str
    requested_action: str
    inspection_outcome: Optional[str] = None
    inspection_notes: Optional[str] = None
    refund_amount_cents: int
    destination_warehouse_id: Optional[str] = None
    authorized_by_user_id: Optional[str] = None
    inspected_by_user_id: Optional[str] = None
    authorized_at: Optional[datetime] = None
    inspected_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    items: List[ReturnItemResponse] = Field(default_factory=list)
