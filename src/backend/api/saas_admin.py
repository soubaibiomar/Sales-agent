"""
SaaS Administration & Tenant Quota API Router.
Exposes endpoints for subscription plan details, usage metering, quota limit tracking,
and noisy-neighbor policy enforcement.
(Controls 05-07, 33-35, 42-43, 49; Invariants 2, 4)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Body, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext
from src.backend.domains.saas.service import SaaSAdminService, QuotaExhaustedError

router = APIRouter(prefix="/saas", tags=["SaaS Administration"])


class QuotaAdjustmentRequest(BaseModel):
    monthly_token_limit: Optional[int] = Field(None, ge=100000)
    monthly_voice_minutes_limit: Optional[int] = Field(None, ge=10)
    monthly_api_call_limit: Optional[int] = Field(None, ge=1000)
    max_seats: Optional[int] = Field(None, ge=1)


@router.get("/subscription")
async def get_tenant_subscription(
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns the tenant's current active SaaS subscription and plan entitlements."""
    service = SaaSAdminService(db, ctx.tenant_id)
    sub = await service.get_or_create_subscription()
    return {
        "tenant_id": ctx.tenant_id,
        "plan_id": sub.plan_id,
        "status": sub.status,
        "current_period_start": sub.current_period_start.isoformat(),
        "current_period_end": sub.current_period_end.isoformat(),
        "limits": {
            "monthly_token_limit": sub.monthly_token_limit,
            "monthly_voice_minutes_limit": sub.monthly_voice_minutes_limit,
            "monthly_api_call_limit": sub.monthly_api_call_limit,
            "max_seats": sub.max_seats
        },
        "features": sub.features_json
    }


@router.get("/usage")
async def get_tenant_usage(
    period_month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$", description="Month in YYYY-MM format"),
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns consumption meters for the specified month."""
    service = SaaSAdminService(db, ctx.tenant_id)
    meter = await service.get_or_create_monthly_meter(period_month=period_month)
    return {
        "tenant_id": ctx.tenant_id,
        "period_month": meter.period_month,
        "llm_input_tokens": meter.llm_input_tokens,
        "llm_output_tokens": meter.llm_output_tokens,
        "total_tokens": meter.total_tokens,
        "voice_seconds": meter.voice_seconds,
        "voice_minutes": meter.voice_seconds // 60,
        "api_requests_count": meter.api_requests_count,
        "storage_bytes_used": meter.storage_bytes_used,
        "active_users_count": meter.active_users_count,
        "last_updated_at": meter.last_updated_at.isoformat()
    }


@router.get("/quotas")
async def get_quota_dashboard(
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns complete quota consumption breakdown, percentages, and exhaustion states."""
    service = SaaSAdminService(db, ctx.tenant_id)
    return await service.get_usage_summary()


@router.post("/quotas/adjust")
async def adjust_tenant_quotas(
    payload: QuotaAdjustmentRequest,
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Allows tenant administrators to upgrade or customize resource quotas."""
    service = SaaSAdminService(db, ctx.tenant_id)
    sub = await service.get_or_create_subscription()

    if payload.monthly_token_limit is not None:
        sub.monthly_token_limit = payload.monthly_token_limit
    if payload.monthly_voice_minutes_limit is not None:
        sub.monthly_voice_minutes_limit = payload.monthly_voice_minutes_limit
    if payload.monthly_api_call_limit is not None:
        sub.monthly_api_call_limit = payload.monthly_api_call_limit
    if payload.max_seats is not None:
        sub.max_seats = payload.max_seats

    await db.commit()
    return {
        "status": "SUCCESS",
        "tenant_id": ctx.tenant_id,
        "updated_limits": {
            "monthly_token_limit": sub.monthly_token_limit,
            "monthly_voice_minutes_limit": sub.monthly_voice_minutes_limit,
            "monthly_api_call_limit": sub.monthly_api_call_limit,
            "max_seats": sub.max_seats
        }
    }
