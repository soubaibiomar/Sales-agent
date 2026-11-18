"""
Payment API Endpoints.
Payment Intents, Sandbox Confirmation, Signed Webhook Processing, and Refund Workflows.
(Controls 31, 32, 48, 57, 58, 59; SAI-07, SAI-08)
Step 05: Sprint 3 - Transact
"""
import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Header, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext, require_permission
from src.backend.domains.payments.service import (
    PaymentService, PaymentError, InvalidWebhookSignatureError,
    DuplicateWebhookEventError, PaymentFailedError, RefundExceedsPaidAmountError,
    UnauthorizedRefundError
)
from src.backend.schemas.payments import (
    PaymentIntentCreateRequest, PaymentIntentResponse,
    PaymentConfirmRequest, PaymentTransactionResponse,
    RefundCreateRequest, RefundResponse
)
from src.backend.models.entities import PaymentIntent, PaymentTransaction, RefundRequest

router = APIRouter(prefix="/payments", tags=["Payments & Refunds"])

DEFAULT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET", "whsec_test_secret_for_sales_ai_sandbox_hmac_256")


@router.post("/intents", response_model=PaymentIntentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment_intent(
    req: PaymentIntentCreateRequest,
    ctx: SecurityContext = Depends(require_permission("orders:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = PaymentService(db)
    try:
        intent = await service.create_payment_intent(
            tenant_id=ctx.tenant_id,
            order_id=req.order_id,
            provider=req.provider,
            idempotency_key=req.idempotency_key,
            metadata=req.metadata
        )
        return intent
    except PaymentError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/intents/{intent_id}/confirm", response_model=PaymentTransactionResponse)
async def confirm_payment_intent(
    intent_id: str,
    req: PaymentConfirmRequest,
    ctx: SecurityContext = Depends(require_permission("orders:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = PaymentService(db)
    try:
        tx = await service.confirm_payment_intent(
            tenant_id=ctx.tenant_id,
            intent_id=intent_id,
            payment_method_token=req.payment_method_token or "tok_sandbox_valid_card",
            payment_method_type=req.payment_method_type,
            idempotency_key=req.idempotency_key
        )
        return tx
    except PaymentFailedError as e:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(e))
    except PaymentError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/webhook")
async def process_payment_webhook(
    request: Request,
    tenant_id: str = Query(..., description="Target tenant ID"),
    provider: str = Query("STRIPE_SANDBOX"),
    x_signature_sha256: Optional[str] = Header(None, alias="X-Signature-SHA256"),
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db_session)
):
    signature = x_signature_sha256 or stripe_signature
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required cryptographic webhook signature (X-Signature-SHA256 or Stripe-Signature)"
        )

    raw_body_bytes = await request.body()
    raw_payload_str = raw_body_bytes.decode("utf-8")

    service = PaymentService(db)
    try:
        result = await service.process_webhook_event(
            tenant_id=tenant_id,
            provider=provider,
            raw_payload_str=raw_payload_str,
            signature=signature,
            webhook_secret=DEFAULT_WEBHOOK_SECRET
        )
        return result
    except InvalidWebhookSignatureError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except PaymentError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/refunds", response_model=RefundResponse, status_code=status.HTTP_201_CREATED)
async def create_refund_request(
    req: RefundCreateRequest,
    ctx: SecurityContext = Depends(require_permission("orders:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    service = PaymentService(db)
    try:
        refund = await service.create_refund_request(
            tenant_id=ctx.tenant_id,
            order_id=req.order_id,
            amount_cents=req.amount_cents,
            reason=req.reason,
            requested_by_user_id=ctx.user_id,
            idempotency_key=req.idempotency_key
        )
        return refund
    except RefundExceedsPaidAmountError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except PaymentError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/refunds/{refund_id}/approve", response_model=RefundResponse)
async def approve_refund(
    refund_id: str,
    x_mfa_verified: Optional[str] = Header(None, alias="X-MFA-Verified"),
    mfa_verified: bool = Query(False, description="MFA step-up verification token"),
    ctx: SecurityContext = Depends(require_permission("quotes:approve")),
    db: AsyncSession = Depends(get_db_session)
):
    is_mfa_verified = (x_mfa_verified == "true") or mfa_verified
    service = PaymentService(db)
    try:
        refund = await service.approve_and_process_refund(
            tenant_id=ctx.tenant_id,
            refund_id=refund_id,
            approved_by_user_id=ctx.user_id,
            step_up_mfa_verified=is_mfa_verified
        )
        return refund
    except UnauthorizedRefundError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except PaymentError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/transactions", response_model=List[PaymentTransactionResponse])
async def list_transactions(
    order_id: Optional[str] = None,
    ctx: SecurityContext = Depends(require_permission("orders:read")),
    db: AsyncSession = Depends(get_db_session)
):
    stmt = select(PaymentTransaction).where(PaymentTransaction.tenant_id == ctx.tenant_id)
    if order_id:
        stmt = stmt.where(PaymentTransaction.order_id == order_id)
    stmt = stmt.order_by(PaymentTransaction.created_at.desc())
    res = await db.execute(stmt)
    return list(res.scalars().all())
