"""
Sales Workspace Unified Inbox API Endpoints.
Provides omnichannel conversation queues, timelines, atomic handoff, and agent replies.
(Baseline Controls 16, 17, 33, 42, 57, 58)
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext
from src.backend.models.entities import Conversation, ConversationMessage, Contact
from src.backend.domains.conversations.service import ConversationService, ConversationDomainError

router = APIRouter(prefix="/inbox", tags=["Unified Inbox"])

class AgentReplyRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    attachments: Optional[List[Dict[str, Any]]] = Field(default_factory=list)

class HandoffRequest(BaseModel):
    reason: Optional[str] = "Operator Takeover"

@router.get("/conversations")
async def list_conversations(
    channel_type: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    assigned_to_me: bool = False,
    limit: int = 50,
    offset: int = 0,
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Lists tenant-isolated conversations for the Sales Workspace unified inbox.
    """
    stmt = (
        select(Conversation, Contact.display_name)
        .join(Contact, Conversation.contact_id == Contact.id)
        .where(Conversation.tenant_id == context.tenant_id)
    )

    if channel_type:
        stmt = stmt.where(Conversation.channel_type == channel_type.upper())
    if status_filter:
        stmt = stmt.where(Conversation.status == status_filter.upper())
    if assigned_to_me:
        stmt = stmt.where(Conversation.assigned_user_id == context.user_id)

    stmt = stmt.order_by(Conversation.last_message_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    rows = res.all()

    items = []
    for conv, contact_name in rows:
        items.append({
            "id": conv.id,
            "tenant_id": conv.tenant_id,
            "contact_id": conv.contact_id,
            "contact_name": contact_name,
            "channel_type": conv.channel_type,
            "channel_identifier": conv.channel_identifier,
            "status": conv.status,
            "assigned_user_id": conv.assigned_user_id,
            "version": conv.version,
            "is_ai_silenced": conv.is_ai_silenced,
            "unread_count": conv.unread_count,
            "last_message_at": conv.last_message_at.isoformat(),
            "created_at": conv.created_at.isoformat()
        })

    return {"conversations": items, "total": len(items)}

@router.get("/conversations/{conversation_id}/timeline")
async def get_conversation_timeline(
    conversation_id: str,
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Returns full chronological message timeline for a conversation.
    Enforces strict tenant scoping (IDOR / BOLA prevention).
    """
    # 1. Verify conversation ownership
    conv_stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == context.tenant_id
    )
    c_res = await db.execute(conv_stmt)
    conv = c_res.scalars().first()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # 2. Fetch messages
    msg_stmt = (
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.tenant_id == context.tenant_id
        )
        .order_by(ConversationMessage.created_at.asc())
    )
    m_res = await db.execute(msg_stmt)
    messages = m_res.scalars().all()

    timeline = []
    for m in messages:
        timeline.append({
            "id": m.id,
            "conversation_id": m.conversation_id,
            "sender_type": m.sender_type,
            "sender_id": m.sender_id,
            "content": m.content,
            "content_redacted": m.content_redacted,
            "event_type": m.event_type,
            "conversation_version": m.conversation_version,
            "attachments_json": m.attachments_json,
            "created_at": m.created_at.isoformat()
        })

    return {
        "conversation": {
            "id": conv.id,
            "status": conv.status,
            "version": conv.version,
            "assigned_user_id": conv.assigned_user_id,
            "is_ai_silenced": conv.is_ai_silenced
        },
        "messages": timeline
    }

@router.post("/conversations/{conversation_id}/handoff")
async def handoff_conversation(
    conversation_id: str,
    req: HandoffRequest,
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Atomic human operator handoff endpoint.
    Transitions status to HUMAN_ACTIVE, silences AI, and increments version.
    """
    try:
        conv = await ConversationService.transfer_to_human(
            session=db,
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            operator_id=context.user_id,
            reason=req.reason or "Operator Takeover"
        )
        return {
            "status": "success",
            "conversation_id": conv.id,
            "conversation_status": conv.status,
            "version": conv.version,
            "is_ai_silenced": conv.is_ai_silenced,
            "assigned_user_id": conv.assigned_user_id
        }
    except ConversationDomainError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.post("/conversations/{conversation_id}/release")
async def release_conversation(
    conversation_id: str,
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Releases conversation back to automated AI bot management.
    """
    try:
        conv = await ConversationService.release_to_bot(
            session=db,
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            operator_id=context.user_id
        )
        return {
            "status": "success",
            "conversation_id": conv.id,
            "conversation_status": conv.status,
            "version": conv.version,
            "is_ai_silenced": conv.is_ai_silenced
        }
    except ConversationDomainError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.post("/conversations/{conversation_id}/reply")
async def agent_reply(
    conversation_id: str,
    req: AgentReplyRequest,
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Sends an agent reply on the conversation timeline.
    """
    try:
        msg = await ConversationService.post_agent_reply(
            session=db,
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            agent_user_id=context.user_id,
            content=req.content,
            attachments=req.attachments
        )
        return {
            "status": "success",
            "message_id": msg.id,
            "conversation_id": msg.conversation_id,
            "version": msg.conversation_version,
            "created_at": msg.created_at.isoformat()
        }
    except ConversationDomainError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
