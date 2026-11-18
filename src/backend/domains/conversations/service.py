"""
Omnichannel Conversation Domain Service.
Manages durable raw event ingestion, deterministic contact resolution,
monotonically versioned conversation state machine, human handoff, and multilingual STOP enforcement.
(Baseline Controls 16, 17, 19, 33, 34, 35, 42, 57, 58, 59; SAI-11)
"""
import re
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.models.entities import (
    Contact, ChannelIdentity, Conversation, InboundRawEvent,
    ConversationMessage, MessageAttachment, AuditEvent, User
)
from src.backend.integrations.base import NormalizedInboundEvent
from src.backend.core.media_security import validate_attachment_metadata

# Multilingual STOP Regex Patterns (English, French, Standard Arabic, Moroccan Darija/Arabizi)
STOP_PATTERNS = [
    # English
    r"\b(stop|unsubscribe|quit|cancel|end)\b",
    # French
    r"\b(stop|arret|arr[eê]ter|desabonner|desinscription|annuler)\b",
    # Standard Arabic
    r"(حبس|وقف|إلغاء|الغاء|توقف)",
    # Moroccan Darija / Arabizi
    r"\b(baraka|safii?\s+baraka|stoppi|habess?|wqf|7bes)\b",
]

COMPILED_STOP_REGEX = [re.compile(p, re.IGNORECASE) for p in STOP_PATTERNS]

# PII Redaction Regexes (Credit Cards, Phone/National ID patterns)
CREDIT_CARD_REGEX = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")
PIN_PASSWORD_REGEX = re.compile(r"\b(pin|password|mot de passe|mdp)[:= ]+\S+\b", re.IGNORECASE)

class ConversationDomainError(Exception):
    pass

class DuplicateEventError(ConversationDomainError):
    pass

class StaleTurnError(ConversationDomainError):
    pass

class OptedOutChannelError(ConversationDomainError):
    pass

def redact_pii(text: str) -> str:
    """Redacts sensitive payment credentials, PINs, and passwords from message content."""
    if not text:
        return ""
    clean = CREDIT_CARD_REGEX.sub("[REDACTED_CARD]", text)
    clean = PIN_PASSWORD_REGEX.sub("[REDACTED_SECRET]", clean)
    return clean

def detect_stop_intent(text: str) -> Tuple[bool, Optional[str]]:
    """
    Deterministically evaluates whether the inbound text expresses a STOP/opt-out directive.
    Outranks any LLM agent or prompt interpretation.
    """
    if not text:
        return False, None
    clean_text = text.strip()
    for regex in COMPILED_STOP_REGEX:
        match = regex.search(clean_text)
        if match:
            return True, match.group(0)
    return False, None

class ConversationService:
    """Enterprise domain service for omnichannel ingestion and conversation state."""

    @staticmethod
    async def ingest_raw_event(
        session: AsyncSession,
        tenant_id: str,
        channel_type: str,
        provider_event_id: str,
        payload_dict: Dict[str, Any],
        signature_verified: bool = True
    ) -> InboundRawEvent:
        """
        DURABLE INGEST: Persists raw webhook event before any batching, routing, or debounce.
        Enforces idempotency using (tenant_id, channel_type, provider_event_id).
        """
        # Check for existing duplicate event
        stmt = select(InboundRawEvent).where(
            InboundRawEvent.tenant_id == tenant_id,
            InboundRawEvent.channel_type == channel_type,
            InboundRawEvent.provider_event_id == provider_event_id
        )
        res = await session.execute(stmt)
        existing = res.scalars().first()
        if existing:
            # Mark as DUPLICATE and return
            existing.processing_status = "DUPLICATE"
            await session.commit()
            return existing

        payload_json = json.dumps(payload_dict, default=str)
        raw_event = InboundRawEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            channel_type=channel_type,
            provider_event_id=provider_event_id,
            payload_json=payload_json,
            signature_verified=signature_verified,
            processing_status="PENDING",
            created_at=datetime.now(timezone.utc)
        )
        session.add(raw_event)
        await session.commit()
        await session.refresh(raw_event)
        return raw_event

    @staticmethod
    async def resolve_or_create_contact(
        session: AsyncSession,
        tenant_id: str,
        channel_type: str,
        identifier: str,
        sender_name: Optional[str] = None
    ) -> Tuple[Contact, ChannelIdentity]:
        """
        Resolves or creates contact by verified channel identifier.
        Strictly prevents unverified auto-merge across distinct identifiers.
        """
        # 1. Look for existing ChannelIdentity for this tenant
        stmt = select(ChannelIdentity).where(
            ChannelIdentity.tenant_id == tenant_id,
            ChannelIdentity.channel_type == channel_type,
            ChannelIdentity.identifier == identifier
        )
        res = await session.execute(stmt)
        channel_id = res.scalars().first()

        if channel_id:
            contact_stmt = select(Contact).where(
                Contact.tenant_id == tenant_id,
                Contact.id == channel_id.contact_id
            )
            c_res = await session.execute(contact_stmt)
            contact = c_res.scalars().first()
            if contact:
                return contact, channel_id

        # 2. No matching identity found -> Create new Contact and ChannelIdentity
        display_name = sender_name or f"{channel_type.capitalize()} User ({identifier})"
        contact = Contact(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            display_name=display_name,
            primary_phone=identifier if channel_type in ("WHATSAPP", "VOICE_SIP") else None,
            primary_email=identifier if channel_type == "EMAIL" else None,
            is_verified=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(contact)
        await session.flush()

        channel_id = ChannelIdentity(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            contact_id=contact.id,
            channel_type=channel_type,
            identifier=identifier,
            is_opted_out=False,
            consent_given_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc)
        )
        session.add(channel_id)
        await session.flush()
        return contact, channel_id

    @staticmethod
    async def process_normalized_event(
        session: AsyncSession,
        event: NormalizedInboundEvent
    ) -> ConversationMessage:
        """
        Processes normalized message event into tenant conversation timeline with state machine updates.
        Enforces STOP directives, monotonic conversation versions, and PII redaction.
        """
        contact, identity = await ConversationService.resolve_or_create_contact(
            session=session,
            tenant_id=event.tenant_id,
            channel_type=event.channel_type,
            identifier=event.sender_identifier,
            sender_name=event.sender_name
        )

        # 1. Deterministic Multilingual STOP / Opt-Out Check
        is_stop, matched_keyword = detect_stop_intent(event.content)
        if is_stop:
            identity.is_opted_out = True
            identity.opt_out_at = datetime.now(timezone.utc)
            identity.opt_out_reason = f"Keyword detected: {matched_keyword}"
            await session.flush()

            # Record Audit Event
            audit = AuditEvent(
                id=str(uuid.uuid4()),
                tenant_id=event.tenant_id,
                actor_id=contact.id,
                event_type="CONSENT_OPT_OUT",
                resource_type="CHANNEL_IDENTITY",
                resource_id=identity.id,
                action="STOP_KEYWORD",
                status="SUCCESS",
                payload_json=json.dumps({"keyword": matched_keyword, "channel": event.channel_type})
            )
            session.add(audit)

        # 2. Find or Create Active Conversation
        conv_stmt = select(Conversation).where(
            Conversation.tenant_id == event.tenant_id,
            Conversation.contact_id == contact.id,
            Conversation.channel_type == event.channel_type,
            Conversation.status.in_(["BOT_ACTIVE", "HUMAN_PENDING", "HUMAN_ACTIVE"])
        ).order_by(Conversation.created_at.desc())
        conv_res = await session.execute(conv_stmt)
        conversation = conv_res.scalars().first()

        now = datetime.now(timezone.utc)
        if not conversation:
            conversation = Conversation(
                id=str(uuid.uuid4()),
                tenant_id=event.tenant_id,
                contact_id=contact.id,
                channel_type=event.channel_type,
                channel_identifier=event.sender_identifier,
                status="BOT_ACTIVE",
                version=1,
                is_ai_silenced=identity.is_opted_out,
                unread_count=1,
                last_message_at=now,
                created_at=now,
                updated_at=now
            )
            session.add(conversation)
            await session.flush()
        else:
            conversation.version += 1
            conversation.unread_count += 1
            conversation.last_message_at = now
            conversation.updated_at = now
            if identity.is_opted_out:
                conversation.is_ai_silenced = True

        # 3. Create Conversation Message
        redacted = redact_pii(event.content)
        msg_type = "CONSENT_STOP" if is_stop else ("ATTACHMENT" if event.attachments else event.event_type)

        msg = ConversationMessage(
            id=str(uuid.uuid4()),
            conversation_id=conversation.id,
            tenant_id=event.tenant_id,
            sender_type="CUSTOMER",
            content=event.content,
            content_redacted=redacted,
            event_type=msg_type,
            conversation_version=conversation.version,
            attachments_json=json.dumps(event.attachments),
            created_at=now
        )
        session.add(msg)
        await session.flush()

        # 4. Attachments Validation & Storage
        for att in event.attachments:
            file_name = att.get("file_name", "attachment")
            mime_type = att.get("mime_type", "application/octet-stream")
            file_size = att.get("file_size", 1024)
            try:
                validate_attachment_metadata(file_name, mime_type, file_size)
                is_safe = True
            except Exception:
                is_safe = False

            attachment = MessageAttachment(
                id=str(uuid.uuid4()),
                message_id=msg.id,
                tenant_id=event.tenant_id,
                file_name=file_name,
                content_type=mime_type,
                file_size_bytes=file_size,
                storage_path=att.get("url") or f"attachments/{event.tenant_id}/{msg.id}/{file_name}",
                is_safe=is_safe,
                created_at=now
            )
            session.add(attachment)

        # 5. If STOP occurred, also append a SYSTEM notice
        if is_stop:
            sys_msg = ConversationMessage(
                id=str(uuid.uuid4()),
                conversation_id=conversation.id,
                tenant_id=event.tenant_id,
                sender_type="SYSTEM",
                content=f"Consent STOP directive received ('{matched_keyword}'). Automated AI messaging is permanently halted on this channel.",
                content_redacted="Consent STOP directive received. Automated AI messaging is permanently halted on this channel.",
                event_type="CONSENT_STOP",
                conversation_version=conversation.version,
                created_at=now
            )
            session.add(sys_msg)

        await session.commit()
        await session.refresh(msg)
        return msg

    @staticmethod
    async def transfer_to_human(
        session: AsyncSession,
        tenant_id: str,
        conversation_id: str,
        operator_id: str,
        reason: str = "Operator Takeover"
    ) -> Conversation:
        """
        ATOMIC HUMAN HANDOFF: Transitions conversation to HUMAN_ACTIVE, assigns operator,
        silences AI responses, and monotonically increments version.
        (Baseline Controls 57, 58; SAI-11)
        """
        stmt = select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.id == conversation_id
        )
        res = await session.execute(stmt)
        conv = res.scalars().first()
        if not conv:
            raise ConversationDomainError(f"Conversation {conversation_id} not found in tenant {tenant_id}")

        now = datetime.now(timezone.utc)
        conv.status = "HUMAN_ACTIVE"
        conv.assigned_user_id = operator_id
        conv.is_ai_silenced = True
        conv.version += 1
        conv.updated_at = now

        # Add system event to message timeline
        handoff_msg = ConversationMessage(
            id=str(uuid.uuid4()),
            conversation_id=conv.id,
            tenant_id=tenant_id,
            sender_type="SYSTEM",
            sender_id=operator_id,
            content=f"Conversation transferred to human operator ({operator_id}). Reason: {reason}. AI bot is silenced.",
            content_redacted=f"Conversation transferred to human operator. Reason: {reason}.",
            event_type="HANDOFF",
            conversation_version=conv.version,
            created_at=now
        )
        session.add(handoff_msg)

        # Audit Event
        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id=operator_id,
            event_type="HUMAN_HANDOFF",
            resource_type="CONVERSATION",
            resource_id=conv.id,
            action="TAKEOVER",
            status="SUCCESS",
            payload_json=json.dumps({"reason": reason, "version": conv.version})
        )
        session.add(audit)

        await session.commit()
        await session.refresh(conv)
        return conv

    @staticmethod
    async def release_to_bot(
        session: AsyncSession,
        tenant_id: str,
        conversation_id: str,
        operator_id: str
    ) -> Conversation:
        """
        Releases conversation back to automated AI bot handling.
        """
        stmt = select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.id == conversation_id
        )
        res = await session.execute(stmt)
        conv = res.scalars().first()
        if not conv:
            raise ConversationDomainError(f"Conversation {conversation_id} not found")

        now = datetime.now(timezone.utc)
        conv.status = "BOT_ACTIVE"
        conv.assigned_user_id = None
        conv.is_ai_silenced = False
        conv.version += 1
        conv.updated_at = now

        sys_msg = ConversationMessage(
            id=str(uuid.uuid4()),
            conversation_id=conv.id,
            tenant_id=tenant_id,
            sender_type="SYSTEM",
            sender_id=operator_id,
            content="Conversation released back to automated AI bot handling.",
            event_type="STATUS_CHANGE",
            conversation_version=conv.version,
            created_at=now
        )
        session.add(sys_msg)
        await session.commit()
        await session.refresh(conv)
        return conv

    @staticmethod
    async def post_ai_reply(
        session: AsyncSession,
        tenant_id: str,
        conversation_id: str,
        expected_version: int,
        content: str
    ) -> ConversationMessage:
        """
        STALE TURN & HUMAN TAKEOVER GUARD:
        AI can only submit a reply IF AND ONLY IF:
        1. Conversation is not silenced (human does not own it).
        2. Current conversation.version exactly matches expected_version from turn dispatch.
        """
        stmt = select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.id == conversation_id
        )
        res = await session.execute(stmt)
        conv = res.scalars().first()
        if not conv:
            raise ConversationDomainError(f"Conversation {conversation_id} not found")

        if conv.is_ai_silenced:
            raise StaleTurnError("AI reply rejected: Conversation is owned by a human operator (AI is silenced)")

        if conv.version != expected_version:
            raise StaleTurnError(
                f"AI reply rejected: Conversation version conflict (expected {expected_version}, current {conv.version}). "
                "Inbound message race cancelled stale AI turn."
            )

        now = datetime.now(timezone.utc)
        conv.version += 1
        conv.last_message_at = now
        conv.updated_at = now

        msg = ConversationMessage(
            id=str(uuid.uuid4()),
            conversation_id=conv.id,
            tenant_id=tenant_id,
            sender_type="AI_BOT",
            sender_id="sales_ai_bot",
            content=content,
            content_redacted=redact_pii(content),
            event_type="MESSAGE",
            conversation_version=conv.version,
            created_at=now
        )
        session.add(msg)
        await session.commit()
        await session.refresh(msg)
        return msg

    @staticmethod
    async def post_agent_reply(
        session: AsyncSession,
        tenant_id: str,
        conversation_id: str,
        agent_user_id: str,
        content: str,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> ConversationMessage:
        """
        Submits reply from human sales representative or support agent.
        """
        stmt = select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.id == conversation_id
        )
        res = await session.execute(stmt)
        conv = res.scalars().first()
        if not conv:
            raise ConversationDomainError(f"Conversation {conversation_id} not found")

        now = datetime.now(timezone.utc)
        conv.version += 1
        conv.unread_count = 0  # Agent read all messages
        conv.last_message_at = now
        conv.updated_at = now

        msg = ConversationMessage(
            id=str(uuid.uuid4()),
            conversation_id=conv.id,
            tenant_id=tenant_id,
            sender_type="AGENT",
            sender_id=agent_user_id,
            content=content,
            content_redacted=redact_pii(content),
            event_type="MESSAGE",
            conversation_version=conv.version,
            attachments_json=json.dumps(attachments or []),
            created_at=now
        )
        session.add(msg)
        await session.commit()
        await session.refresh(msg)
        return msg
