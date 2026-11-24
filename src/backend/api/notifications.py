"""
Notifications & Opt-Out Management API Routes.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import (
    get_optional_security_context,
    require_permission,
    SecurityContext
)
from src.backend.models.entities import NotificationTemplate, NotificationLog
from src.backend.schemas.notifications import (
    NotificationTemplateCreateRequest,
    NotificationTemplateResponse,
    NotificationSendRequest,
    NotificationLogResponse,
    OptOutRequest
)
from src.backend.notifications.orchestrator import NotificationOrchestrator

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


@router.post("/send", response_model=NotificationLogResponse, status_code=status.HTTP_201_CREATED)
async def send_notification(
    req: NotificationSendRequest,
    ctx: SecurityContext = Depends(require_permission("notifications:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Sends or enqueues a notification governed by Moroccan quiet hours, multi-script STOP opt-out, and frequency caps.
    """
    tenant_id = ctx.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    orchestrator = NotificationOrchestrator(db)
    log = await orchestrator.dispatch_notification(
        tenant_id=tenant_id,
        recipient_identifier=req.recipient_identifier,
        channel_type=req.channel_type.upper(),
        message_class=req.message_class.upper(),
        template_code=req.template_code,
        subject=req.subject,
        content=req.content,
        variables=req.variables,
        language=req.language
    )
    await db.commit()
    await db.refresh(log)
    return log


@router.get("/history", response_model=List[NotificationLogResponse])
async def list_notification_history(
    recipient: Optional[str] = None,
    channel_type: Optional[str] = None,
    message_class: Optional[str] = None,
    status_filter: Optional[str] = None,
    ctx: SecurityContext = Depends(require_permission("notifications:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    tenant_id = ctx.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    stmt = select(NotificationLog).where(NotificationLog.tenant_id == tenant_id)
    if recipient:
        stmt = stmt.where(NotificationLog.recipient_identifier == recipient)
    if channel_type:
        stmt = stmt.where(NotificationLog.channel_type == channel_type.upper())
    if message_class:
        stmt = stmt.where(NotificationLog.message_class == message_class.upper())
    if status_filter:
        stmt = stmt.where(NotificationLog.status == status_filter.upper())

    stmt = stmt.order_by(NotificationLog.created_at.desc()).limit(100)
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.get("/templates", response_model=List[NotificationTemplateResponse])
async def list_templates(
    channel_type: Optional[str] = None,
    ctx: SecurityContext = Depends(require_permission("notifications:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    tenant_id = ctx.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    stmt = select(NotificationTemplate).where(NotificationTemplate.tenant_id == tenant_id)
    if channel_type:
        stmt = stmt.where(NotificationTemplate.channel_type == channel_type.upper())

    stmt = stmt.order_by(NotificationTemplate.template_code.asc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post("/templates", response_model=NotificationTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    req: NotificationTemplateCreateRequest,
    ctx: SecurityContext = Depends(require_permission("notifications:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    tenant_id = ctx.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    import uuid
    template = NotificationTemplate(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        template_code=req.template_code.upper(),
        channel_type=req.channel_type.upper(),
        message_class=req.message_class.upper(),
        language=req.language,
        subject_template=req.subject_template,
        body_template=req.body_template,
        variables_json=req.variables or [],
        is_active=req.is_active
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@router.post("/opt-out", response_model=Dict[str, Any])
async def process_opt_out(
    req: OptOutRequest,
    ctx: SecurityContext = Depends(require_permission("notifications:manage")),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Registers an explicit STOP / opt-out directive across French, English, Darija, or Arabic.
    """
    tenant_id = ctx.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    from src.backend.notifications.orchestrator import MultiScriptOptOutManager
    is_opt, matched_kw = MultiScriptOptOutManager.is_opt_out_phrase(req.directive)
    orchestrator = NotificationOrchestrator(db)
    success = await orchestrator.register_opt_out(
        tenant_id=tenant_id,
        channel_type=req.channel_type.upper(),
        recipient_identifier=req.recipient_identifier,
        directive_text=req.directive
    )
    await db.commit()

    return {
        "opted_out": success,
        "matched_keyword": matched_kw,
        "channel_type": req.channel_type.upper(),
        "recipient_identifier": req.recipient_identifier,
        "directive": req.directive
    }
