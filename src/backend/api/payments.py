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
from src.backend.models.entities import PaymentIntent, PaymentTransaction, RefundRequest, TenantChannelIntegration
from src.backend.core.config import settings
from src.backend.core.database import bind_tenant_context
from src.backend.core.step_up import is_step_up_satisfied
from pydantic import BaseModel

router = APIRouter(prefix="/payments", tags=["Payments & Refunds"])



class RefundApproveRequest(BaseModel):
    mfa_code: Optional[str] = None  # TOTP code, verified server-side against the approver's seed


def _parse_signature_headers(x_signature: Optional[str], x_timestamp: Optional[str], stripe_signature: Optional[str]):
    """Returns (signature, timestamp) from either our header pair or a Stripe-style 't=..,v1=..' header."""
    if stripe_signature:
        parts = dict(p.split("=", 1) for p in stripe_signature.split(",") if "=" in p)
        ts = parts.get("t")
        return parts.get("v1"), (int(ts) if ts and ts.isdigit() else None)
    return x_signature, (int(x_timestamp) if x_timestamp and x_timestamp.isdigit() else None)


async def _resolve_payment_webhook_secret(db: AsyncSession, tenant_id: str, provider: str) -> Optional[str]:
    """
    F-02: per-tenant provider secret from tenant_channel_integrations
    (channel_type 'PAYMENT_<PROVIDER>'). The shared configured secret is a
    development-only fallback and is refused in any other environment.
    """
    integration = (await db.execute(select(TenantChannelIntegration).where(and_(
        TenantChannelIntegration.channel_type == f"PAYMENT_{provider.upper()}",
        TenantChannelIntegration.tenant_id == tenant_id,
        TenantChannelIntegration.is_active.is_(True)
    )))).scalars().first()
    if integration and integration.webhook_secret:
        return integration.webhook_secret
    if settings.is_development:
        return settings.payment_webhook_secret
    return None


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
    tenant_id: str = Query(..., description="Target tenant ID (authenticated by the tenant's own webhook secret)"),
    provider: str = Query("STRIPE_SANDBOX"),
    x_signature_sha256: Optional[str] = Header(None, alias="X-Signature-SHA256"),
    x_signature_timestamp: Optional[str] = Header(None, alias="X-Signature-Timestamp"),
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db_session)
):
    signature, timestamp = _parse_signature_headers(x_signature_sha256, x_signature_timestamp, stripe_signature)
    if not signature or timestamp is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook signature or signed timestamp"
        )

    secret = await _resolve_payment_webhook_secret(db, tenant_id, provider)
    if not secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook source not configured for tenant")

    raw_payload_str = (await request.body()).decode("utf-8")
    # The tenant id is only trusted because the payload must verify with THAT tenant's
    # secret; the service verifies the signature before reading any tenant data.
    await bind_tenant_context(db, tenant_id)

    service = PaymentService(db)
    try:
        result = await service.process_webhook_event(
            tenant_id=tenant_id,
            provider=provider,
            raw_payload_str=raw_payload_str,
            signature=signature,
            webhook_secret=secret,
            timestamp=timestamp,
            require_timestamp=True,
            tolerance_seconds=settings.payment_webhook_tolerance_seconds,
            require_amount_match=True
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
        raise HTTPException(status_code=422, detail=str(e))
    except PaymentError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/refunds/{refund_id}/approve", response_model=RefundResponse)
async def approve_refund(
    refund_id: str,
    req: Optional[RefundApproveRequest] = None,
    ctx: SecurityContext = Depends(require_permission("quotes:approve")),
    db: AsyncSession = Depends(get_db_session)
):
    # F-03: MFA is proven server-side (MFA-verified session token or a TOTP code that
    # verifies against the approver's seed) - never by a client header or query flag.
    is_mfa_verified = await is_step_up_satisfied(db, ctx, req.mfa_code if req else None)
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
    except RefundExceedsPaidAmountError as e:
        raise HTTPException(status_code=422, detail=str(e))
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
