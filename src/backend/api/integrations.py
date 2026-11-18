"""
External Integrations & n8n Peripheral Barrier API Routes.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import (
    get_optional_security_context,
    get_security_context,
    require_permission,
    SecurityContext
)
from src.backend.models.entities import OutboxEvent, TenantChannelIntegration
from src.backend.domains.conversations.outbox import OutboxStatus
from src.backend.integrations.n8n import N8NIntegrationGateway, N8NSecurityViolationError

router = APIRouter(prefix="/api/v1/integrations", tags=["Integrations & n8n"])


@router.get("/status", response_model=Dict[str, Any])
async def get_integrations_and_outbox_health(
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Returns health status of tenant integrations, outbox pending backlog, and DLQ counts.
    """
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    # Query outbox metrics
    pending_cnt = (await db.execute(
        select(func.count(OutboxEvent.id)).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.status.in_([OutboxStatus.PENDING, OutboxStatus.PROCESSING])
        )
    )).scalar() or 0

    dlq_cnt = (await db.execute(
        select(func.count(OutboxEvent.id)).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.status == OutboxStatus.DEAD_LETTER
        )
    )).scalar() or 0

    # Query active channel integrations
    active_int_cnt = (await db.execute(
        select(func.count(TenantChannelIntegration.id)).where(
            TenantChannelIntegration.tenant_id == tenant_id,
            TenantChannelIntegration.is_active == True
        )
    )).scalar() or 0

    return {
        "tenant_id": tenant_id,
        "outbox_pending_count": pending_cnt,
        "dead_letter_queue_count": dlq_cnt,
        "active_integrations_count": active_int_cnt,
        "n8n_integration_mode": "RESTRICTED_PERIPHERAL",
        "n8n_security_barrier": "ENFORCED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "HEALTHY" if dlq_cnt == 0 else "WARNING"
    }


@router.get("/outbox/dlq", response_model=List[Dict[str, Any]])
async def list_dead_letter_queue(
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Returns items quarantined in the Outbox Dead-Letter Queue (DLQ).
    """
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    stmt = select(OutboxEvent).where(
        OutboxEvent.tenant_id == tenant_id,
        OutboxEvent.status == OutboxStatus.DEAD_LETTER
    ).order_by(OutboxEvent.created_at.desc()).limit(100)

    events = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": ev.id,
            "tenant_id": ev.tenant_id,
            "event_type": ev.event_type,
            "channel_type": ev.channel_type,
            "recipient_identifier": ev.recipient_identifier,
            "retry_count": ev.retry_count,
            "max_retries": ev.max_retries,
            "last_error": ev.last_error,
            "created_at": ev.created_at.isoformat()
        }
        for ev in events
    ]


@router.post("/outbox/dlq/{event_id}/retry", response_model=Dict[str, Any])
async def retry_dead_letter_event(
    event_id: str,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Requeues a dead-letter event for fresh dispatch attempts.
    """
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    stmt = select(OutboxEvent).where(
        OutboxEvent.tenant_id == tenant_id,
        OutboxEvent.id == event_id,
        OutboxEvent.status == OutboxStatus.DEAD_LETTER
    )
    ev = (await db.execute(stmt)).scalars().first()
    if not ev:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"DLQ event '{event_id}' not found.")

    ev.status = OutboxStatus.PENDING
    ev.retry_count = 0
    ev.last_error = "Re-queued by administrator"
    ev.next_retry_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "event_id": ev.id,
        "status": "RE_QUEUED",
        "message": "Event returned to PENDING outbox dispatch queue."
    }


@router.post("/n8n/dispatch", response_model=Dict[str, Any])
async def dispatch_n8n_event(
    event_type: str,
    webhook_url: str,
    payload: Dict[str, Any],
    secret_key: Optional[str] = "test_n8n_hmac_secret",
    idempotency_key: Optional[str] = None
):
    """
    Dispatches an event to an external peripheral n8n webhook with cryptographic HMAC signature.
    """
    import uuid
    idemp = idempotency_key or str(uuid.uuid4())
    result = await N8NIntegrationGateway.dispatch_event_to_n8n(
        webhook_url=webhook_url,
        secret_key=secret_key or "default_secret",
        event_type=event_type,
        payload=payload,
        idempotency_key=idemp
    )
    return result


from pydantic import BaseModel

class VerifyBarrierRequest(BaseModel):
    action: str
    roles: Optional[List[str]] = None
    role: Optional[str] = None


@router.post("/n8n/verify-barrier", response_model=Dict[str, Any])
async def verify_n8n_security_barrier(req: VerifyBarrierRequest):
    """
    Security check: Demonstrates that an n8n peripheral integration role is denied commercial mutations.
    """
    effective_roles = req.roles or ([req.role] if req.role else ["peripheral_integration"])
    try:
        N8NIntegrationGateway.assert_action_permitted(effective_roles, req.action)
        return {"allowed": True, "permitted": True, "action": req.action, "roles": effective_roles}
    except N8NSecurityViolationError as e:
        return {"allowed": False, "permitted": False, "action": req.action, "roles": effective_roles, "detail": str(e.detail)}
