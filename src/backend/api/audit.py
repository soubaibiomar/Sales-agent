"""
Audit Log Query API Endpoints.
Ensures audit logs are strictly tenant-scoped and immutable.
"""
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import (
    get_security_context, SecurityContext, require_permission
)
from src.backend.schemas.identity import AuditLogResponse
from src.backend.models.entities import AuditEvent

router = APIRouter(prefix="/audit", tags=["Audit"])

@router.get("/logs", response_model=List[AuditLogResponse])
async def get_tenant_audit_logs(
    limit: int = 50,
    context: SecurityContext = Depends(require_permission("audit:read")),
    db: AsyncSession = Depends(get_db_session)
):
    """Retrieves immutable audit events strictly scoped to active tenant."""
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.tenant_id == context.tenant_id)
        .order_by(desc(AuditEvent.timestamp))
        .limit(min(limit, 100))
    )
    res = await db.execute(stmt)
    events = res.scalars().all()

    return [
        AuditLogResponse(
            id=e.id,
            tenant_id=e.tenant_id,
            actor_id=e.actor_id,
            event_type=e.event_type,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
            action=e.action,
            ip_address=e.ip_address,
            status=e.status,
            timestamp=e.timestamp
        )
        for e in events
    ]
