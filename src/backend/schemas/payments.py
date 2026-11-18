"""
Pydantic schemas for Payments, Payment Intents, Webhooks and Refunds.
Step 05: Sprint 3 - Transact
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class PaymentIntentCreateRequest(BaseModel):
    order_id: str
    provider: str = Field("STRIPE_SANDBOX", description="STRIPE_SANDBOX, CMI_SANDBOX, BANK_TRANSFER")
    idempotency_key: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class PaymentIntentResponse(BaseModel):
    id: str
    tenant_id: str
    order_id: str
    provider: str
    provider_intent_id: str
    client_secret: Optional[str] = None
    amount_cents: int
    currency: str
    status: str
    idempotency_key: Optional[str] = None
    metadata_json: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentConfirmRequest(BaseModel):
    payment_method_type: str = Field("CARD", description="CARD, BANK_TRANSFER, WALLET")
    payment_method_token: Optional[str] = "tok_sandbox_valid_card"
    idempotency_key: Optional[str] = None


class PaymentWebhookPayload(BaseModel):
    event_id: str
    event_type: str  # payment_intent.succeeded, payment_intent.payment_failed, charge.refunded
    provider: str = "STRIPE_SANDBOX"
    provider_intent_id: str
    amount_cents: int
    currency: str
    status: str
    raw_payload: Optional[Dict[str, Any]] = None


class RefundCreateRequest(BaseModel):
    order_id: str
    amount_cents: int = Field(..., gt=0)
    reason: str = Field(..., min_length=1, max_length=255)
    idempotency_key: Optional[str] = None


class RefundResponse(BaseModel):
    id: str
    tenant_id: str
    order_id: str
    payment_intent_id: Optional[str] = None
    amount_cents: int
    currency: str
    reason: str
    status: str
    provider_refund_id: Optional[str] = None
    requested_by_user_id: Optional[str] = None
    approved_by_user_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentTransactionResponse(BaseModel):
    id: str
    tenant_id: str
    payment_intent_id: str
    order_id: str
    transaction_type: str
    amount_cents: int
    currency: str
    provider_transaction_id: str
    payment_method_type: str
    status: str
    receipt_url: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
