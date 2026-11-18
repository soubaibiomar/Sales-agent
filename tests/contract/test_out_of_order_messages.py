"""
Tests for Out-of-Order Message Ingestion, Monotonic Versioning,
Chronological Timeline Integrity, and Stale AI Response Rejection.
(Step 03 Architecture; Baseline Controls 16, 17, 34, 42, 57, 58)
"""
import pytest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

from src.backend.models.entities import (
    Base, Tenant, Contact, Conversation, ConversationMessage
)
from src.backend.integrations.base import NormalizedInboundEvent
from src.backend.domains.conversations.service import (
    ConversationService, StaleTurnError, OptedOutChannelError, ensure_utc
)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@asynccontextmanager
async def get_order_test_db():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        tenant = Tenant(id="tenant_order_test", name="Order Test Tenant", slug="order-tenant")
        session.add(tenant)
        await session.commit()

    async with session_factory() as session:
        yield session

    await engine.dispose()

@pytest.mark.asyncio
async def test_out_of_order_message_timeline_sorting():
    """
    Simulates Message 2 arriving BEFORE Message 1 due to network jitter or webhook retries.
    Verifies that the chronological timeline correctly orders Message 1 before Message 2,
    and last_message_at does not regress backwards.
    """
    async with get_order_test_db() as session:
        t0 = datetime(2026, 3, 30, 10, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(minutes=5)   # 10:05 (Message 1 was sent)
        t2 = t0 + timedelta(minutes=10)  # 10:10 (Message 2 was sent)

        # Inbound Event 2 arrives FIRST
        event_2 = NormalizedInboundEvent(
            tenant_id="tenant_order_test",
            channel_type="WHATSAPP",
            provider_event_id="wamid_msg_002",
            sender_identifier="+212611223344",
            sender_name="Karim Tazi",
            content="I also need 5 units of product B.",
            timestamp=t2
        )
        msg_2 = await ConversationService.process_normalized_event(session, event_2)

        # Inbound Event 1 arrives LATER (delayed in network)
        event_1 = NormalizedInboundEvent(
            tenant_id="tenant_order_test",
            channel_type="WHATSAPP",
            provider_event_id="wamid_msg_001",
            sender_identifier="+212611223344",
            sender_name="Karim Tazi",
            content="Hello, what is the price for product A?",
            timestamp=t1
        )
        msg_1 = await ConversationService.process_normalized_event(session, event_1)

        # Query the conversation state
        conv_stmt = select(Conversation).where(
            Conversation.tenant_id == "tenant_order_test",
            Conversation.channel_identifier == "+212611223344"
        )
        c_res = await session.execute(conv_stmt)
        conv = c_res.scalars().first()
        assert conv is not None

        # Version monotonically incremented from 1 to 2
        assert conv.version == 2
        assert conv.unread_count == 2
        # last_message_at must reflect t2 (the latest physical timestamp), not regressed to t1
        assert ensure_utc(conv.last_message_at) == t2

        # Query chronological timeline
        timeline_stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conv.id)
            .order_by(ConversationMessage.created_at.asc())
        )
        t_res = await session.execute(timeline_stmt)
        timeline = list(t_res.scalars().all())

        # Message 1 (10:05) must appear FIRST in timeline, Message 2 (10:10) SECOND
        assert len(timeline) == 2
        assert timeline[0].id == msg_1.id
        assert timeline[0].content == "Hello, what is the price for product A?"
        assert ensure_utc(timeline[0].created_at) == t1

        assert timeline[1].id == msg_2.id
        assert timeline[1].content == "I also need 5 units of product B."
        assert ensure_utc(timeline[1].created_at) == t2

@pytest.mark.asyncio
async def test_stale_ai_turn_rejected_when_out_of_order_message_intervenes():
    """
    Verifies that when an out-of-order or concurrent message arrives while an AI turn is computing,
    the conversation version increments and the stale AI response is strictly rejected (StaleTurnError).
    """
    async with get_order_test_db() as session:
        t0 = datetime(2026, 3, 30, 11, 0, 0, tzinfo=timezone.utc)

        # Initial Customer Message
        event_init = NormalizedInboundEvent(
            tenant_id="tenant_order_test",
            channel_type="WEB_CHAT",
            provider_event_id="web_evt_001",
            sender_identifier="session_web_001",
            sender_name="Visitor",
            content="Can you give me a discount?",
            timestamp=t0
        )
        await ConversationService.process_normalized_event(session, event_init)

        conv_stmt = select(Conversation).where(Conversation.channel_identifier == "session_web_001")
        c_res = await session.execute(conv_stmt)
        conv = c_res.scalars().first()
        assert conv.version == 1

        # AI turn starts reasoning based on version 1
        expected_ai_version = conv.version  # 1

        # While AI is reasoning, customer sends an out-of-order correction/update
        event_late = NormalizedInboundEvent(
            tenant_id="tenant_order_test",
            channel_type="WEB_CHAT",
            provider_event_id="web_evt_002",
            sender_identifier="session_web_001",
            sender_name="Visitor",
            content="Actually, never mind about discount, I need rush shipping.",
            timestamp=t0 + timedelta(seconds=15)
        )
        await ConversationService.process_normalized_event(session, event_late)

        # Conversation version has now advanced to 2
        await session.refresh(conv)
        assert conv.version == 2

        # AI attempts to post its response based on old version 1
        with pytest.raises(StaleTurnError) as exc_info:
            await ConversationService.post_ai_reply(
                session=session,
                tenant_id="tenant_order_test",
                conversation_id=conv.id,
                expected_version=expected_ai_version,
                content="We can offer you a 5% discount."
            )

        assert "Conversation version conflict" in str(exc_info.value)

@pytest.mark.asyncio
async def test_out_of_order_stop_silences_conversation_and_cancels_ai():
    """
    Verifies that an out-of-order STOP directive halts AI messaging immediately,
    sets is_ai_silenced=True, and rejects any in-flight AI turn.
    """
    async with get_order_test_db() as session:
        t0 = datetime(2026, 3, 30, 14, 0, 0, tzinfo=timezone.utc)

        event_msg = NormalizedInboundEvent(
            tenant_id="tenant_order_test",
            channel_type="WHATSAPP",
            provider_event_id="wamid_stop_1",
            sender_identifier="+212699887766",
            content="Please send catalogue.",
            timestamp=t0
        )
        await ConversationService.process_normalized_event(session, event_msg)

        # STOP arrives
        event_stop = NormalizedInboundEvent(
            tenant_id="tenant_order_test",
            channel_type="WHATSAPP",
            provider_event_id="wamid_stop_2",
            sender_identifier="+212699887766",
            content="STOP",
            timestamp=t0 + timedelta(seconds=5)
        )
        await ConversationService.process_normalized_event(session, event_stop)

        conv_stmt = select(Conversation).where(Conversation.channel_identifier == "+212699887766")
        c_res = await session.execute(conv_stmt)
        conv = c_res.scalars().first()
        assert conv.is_ai_silenced is True

        # Attempting to post AI reply should fail because AI is silenced
        with pytest.raises(StaleTurnError) as exc_info:
            await ConversationService.post_ai_reply(
                session=session,
                tenant_id="tenant_order_test",
                conversation_id=conv.id,
                expected_version=conv.version,
                content="Here is our catalogue."
            )

        assert "AI is silenced" in str(exc_info.value)
