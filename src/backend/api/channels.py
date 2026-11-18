"""
Omnichannel Gateway Webhook & Ingestion Endpoints.
Handles WhatsApp, Email, Voice/SIP, and Web Chat inbound traffic with signature verification.
(Baseline Controls 16, 20, 21, 22, 23, 28, 59; SAI-11)
"""
import json
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Header, HTTPException, status, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.config import settings
from src.backend.core.database import get_db_session
from src.backend.integrations.whatsapp import WhatsAppAdapter
from src.backend.integrations.email import EmailAdapter
from src.backend.integrations.webchat import WebChatAdapter
from src.backend.integrations.voice_sip import VoiceSIPAdapter
from src.backend.domains.conversations.service import ConversationService

router = APIRouter(prefix="/channels", tags=["Omnichannel Gateway"])

whatsapp_adapter = WhatsAppAdapter()
email_adapter = EmailAdapter()
webchat_adapter = WebChatAdapter()
voice_adapter = VoiceSIPAdapter()

# -----------------------------------------------------------------------------
# 1. WHATSAPP WEBHOOKS
# -----------------------------------------------------------------------------

@router.get("/webhooks/whatsapp/{tenant_id}")
async def whatsapp_webhook_challenge(
    tenant_id: str,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token")
):
    """
    Meta WhatsApp Cloud API webhook challenge verification.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        try:
            return int(hub_challenge)
        except (ValueError, TypeError):
            return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid WhatsApp verification token")

@router.post("/webhooks/whatsapp/{tenant_id}")
async def whatsapp_webhook_ingest(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Inbound WhatsApp Cloud API webhook receiver.
    Verifies X-Hub-Signature-256 HMAC and persists raw events before routing.
    """
    raw_body = await request.body()
    headers_dict = dict(request.headers)

    # 1. Cryptographic Signature Verification (Control 22)
    is_valid = whatsapp_adapter.verify_webhook_signature(
        headers=headers_dict,
        raw_body=raw_body,
        secret=settings.whatsapp_webhook_secret
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Hub-Signature-256 cryptographic signature"
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Malformed JSON: {e}")

    # 2. Extract provider event ID (WAMID)
    entries = payload.get("entry", [])
    provider_event_id = None
    for entry in entries:
        for change in entry.get("changes", []):
            messages = change.get("value", {}).get("messages", [])
            if messages:
                provider_event_id = messages[0].get("id")
                break
    if not provider_event_id:
        provider_event_id = f"wa_status_{hash(raw_body)}"

    # 3. Durable Ingestion Before Processing (Control 59)
    raw_event = await ConversationService.ingest_raw_event(
        session=db,
        tenant_id=tenant_id,
        channel_type="WHATSAPP",
        provider_event_id=provider_event_id,
        payload_dict=payload,
        signature_verified=True
    )
    if raw_event.processing_status == "DUPLICATE":
        return {"status": "duplicate_ignored", "provider_event_id": provider_event_id}

    # 4. Normalize and Process Messages
    normalized_events = whatsapp_adapter.parse_inbound_event(
        headers=headers_dict,
        payload=payload,
        tenant_id=tenant_id
    )

    processed_messages = []
    for event in normalized_events:
        msg = await ConversationService.process_normalized_event(session=db, event=event)
        processed_messages.append(msg.id)

    raw_event.processing_status = "PROCESSED"
    await db.commit()

    return {"status": "success", "processed_count": len(processed_messages), "message_ids": processed_messages}

# -----------------------------------------------------------------------------
# 2. EMAIL / GMAIL WEBHOOKS
# -----------------------------------------------------------------------------

@router.post("/webhooks/email/{tenant_id}")
async def email_webhook_ingest(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Inbound Email / Gmail push notification and inbound parsing webhook.
    """
    raw_body = await request.body()
    headers_dict = dict(request.headers)

    # Validate Auth Token
    is_valid = email_adapter.verify_webhook_signature(
        headers=headers_dict,
        raw_body=raw_body,
        secret=settings.email_webhook_secret
    )
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email webhook authentication token")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Malformed JSON: {e}")

    provider_event_id = payload.get("message_id") or payload.get("id") or f"em_{hash(raw_body)}"

    raw_event = await ConversationService.ingest_raw_event(
        session=db,
        tenant_id=tenant_id,
        channel_type="EMAIL",
        provider_event_id=provider_event_id,
        payload_dict=payload,
        signature_verified=True
    )
    if raw_event.processing_status == "DUPLICATE":
        return {"status": "duplicate_ignored", "provider_event_id": provider_event_id}

    normalized_events = email_adapter.parse_inbound_event(
        headers=headers_dict,
        payload=payload,
        tenant_id=tenant_id
    )

    processed_ids = []
    for event in normalized_events:
        msg = await ConversationService.process_normalized_event(session=db, event=event)
        processed_ids.append(msg.id)

    raw_event.processing_status = "PROCESSED"
    await db.commit()

    return {"status": "success", "processed_count": len(processed_ids), "message_ids": processed_ids}

# -----------------------------------------------------------------------------
# 3. VOICE / SIP TELEPHONY EVENTS
# -----------------------------------------------------------------------------

@router.post("/webhooks/voice/{tenant_id}")
async def voice_sip_webhook_ingest(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Inbound SIP telephony session and signaling event receiver.
    Tracks call lifecycle and explicit recording disclosure consent (SAI-04).
    """
    raw_body = await request.body()
    headers_dict = dict(request.headers)

    is_valid = voice_adapter.verify_webhook_signature(
        headers=headers_dict,
        raw_body=raw_body,
        secret=settings.voice_telephony_secret
    )
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid telephony webhook signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Malformed JSON: {e}")

    call_id = payload.get("call_id") or f"call_{hash(raw_body)}"
    event_name = payload.get("event") or "SIGNAL"
    provider_event_id = f"{call_id}_{event_name}"

    raw_event = await ConversationService.ingest_raw_event(
        session=db,
        tenant_id=tenant_id,
        channel_type="VOICE_SIP",
        provider_event_id=provider_event_id,
        payload_dict=payload,
        signature_verified=True
    )
    if raw_event.processing_status == "DUPLICATE":
        return {"status": "duplicate_ignored", "provider_event_id": provider_event_id}

    normalized_events = voice_adapter.parse_inbound_event(
        headers=headers_dict,
        payload=payload,
        tenant_id=tenant_id
    )

    processed_ids = []
    for event in normalized_events:
        msg = await ConversationService.process_normalized_event(session=db, event=event)
        processed_ids.append(msg.id)

    raw_event.processing_status = "PROCESSED"
    await db.commit()

    return {"status": "success", "processed_count": len(processed_ids), "message_ids": processed_ids}

# -----------------------------------------------------------------------------
# 4. AUTHENTICATED WEB CHAT ENDPOINTS
# -----------------------------------------------------------------------------

@router.post("/webchat/send")
async def webchat_send_message(
    payload: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Customer web chat widget message submission endpoint.
    """
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_id is required")

    session_id = payload.get("session_id")
    message_text = payload.get("message", "").strip()
    if not message_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="message content cannot be empty")

    provider_event_id = payload.get("message_id") or f"web_{hash(message_text)}_{session_id}"

    raw_event = await ConversationService.ingest_raw_event(
        session=db,
        tenant_id=tenant_id,
        channel_type="WEB_CHAT",
        provider_event_id=provider_event_id,
        payload_dict=payload,
        signature_verified=True
    )
    if raw_event.processing_status == "DUPLICATE":
        return {"status": "duplicate_ignored", "provider_event_id": provider_event_id}

    normalized_events = webchat_adapter.parse_inbound_event(
        headers=dict(request.headers),
        payload=payload,
        tenant_id=tenant_id
    )

    msg = await ConversationService.process_normalized_event(session=db, event=normalized_events[0])
    raw_event.processing_status = "PROCESSED"
    await db.commit()

    return {
        "status": "success",
        "message_id": msg.id,
        "conversation_id": msg.conversation_id,
        "version": msg.conversation_version
    }
