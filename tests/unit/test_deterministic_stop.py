"""
Unit Tests for Deterministic Multilingual STOP and Consent Opt-Out.
Tests English, French, Standard Arabic, and Moroccan Darija/Arabizi keywords.
(Control 34; SAI-11)
"""
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from src.backend.models.entities import Base, Tenant, Contact, ChannelIdentity, Conversation, AuditEvent
from src.backend.domains.conversations.service import ConversationService, detect_stop_intent
from src.backend.integrations.base import NormalizedInboundEvent

@pytest.mark.parametrize("text,expected_match", [
    ("STOP", True),
    ("stop", True),
    ("Please unsubscribe me from updates", True),
    ("QUIT", True),
    ("CANCEL", True),
    ("Arret des messages", True),
    ("Je souhaite me desabonner", True),
    ("حبس", True),
    ("وقف الرسائل", True),
    ("إلغاء الاشتراك", True),
    ("baraka", True),
    ("safii baraka", True),
    ("stoppi 3afak", True),
    ("7bes", True),
    ("Bonjour, je souhaite acheter un serveur", False),
    ("What are the product specs?", False),
    ("Chhal taman dyal hed l-produit?", False)
])
def test_multilingual_stop_regex_matrix(text, expected_match):
    is_stop, keyword = detect_stop_intent(text)
    assert is_stop is expected_match, f"Failed on text: '{text}' (got {is_stop})"

@pytest.mark.asyncio
async def test_stop_directive_sets_channel_opt_out_and_silences_ai():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tenant_id = "t_stop_test_01"
    async with session_factory() as session:
        t = Tenant(id=tenant_id, name="Test Corp", slug="test-corp")
        session.add(t)
        await session.commit()

        # 1. Normal message first -> Bot active
        event_1 = NormalizedInboundEvent(
            tenant_id=tenant_id,
            channel_type="WHATSAPP",
            provider_event_id="wamid.msg_1",
            sender_identifier="212600112233",
            sender_name="Mohamed",
            content="Salam, chhal l-prix?"
        )
        msg_1 = await ConversationService.process_normalized_event(session, event_1)
        assert msg_1.event_type == "MESSAGE"

        # Check conversation state
        conv = (await session.execute(select(Conversation).where(Conversation.id == msg_1.conversation_id))).scalars().first()
        assert conv.status == "BOT_ACTIVE"
        assert conv.is_ai_silenced is False

        # Check channel identity
        identity = (await session.execute(select(ChannelIdentity).where(ChannelIdentity.identifier == "212600112233"))).scalars().first()
        assert identity.is_opted_out is False

        # 2. Inbound STOP directive in Darija: "baraka"
        event_stop = NormalizedInboundEvent(
            tenant_id=tenant_id,
            channel_type="WHATSAPP",
            provider_event_id="wamid.msg_stop",
            sender_identifier="212600112233",
            sender_name="Mohamed",
            content="safii baraka matb9awch tsifto lia"
        )
        msg_stop = await ConversationService.process_normalized_event(session, event_stop)
        assert msg_stop.event_type == "CONSENT_STOP"

        # Verify ChannelIdentity is permanently opted-out
        await session.refresh(identity)
        assert identity.is_opted_out is True
        assert identity.opt_out_at is not None
        assert "baraka" in identity.opt_out_reason

        # Verify Conversation is silenced
        await session.refresh(conv)
        assert conv.is_ai_silenced is True

        # Verify Audit Log was emitted
        audit = (await session.execute(select(AuditEvent).where(AuditEvent.event_type == "CONSENT_OPT_OUT"))).scalars().first()
        assert audit is not None
        assert audit.action == "STOP_KEYWORD"

    await engine.dispose()
