"""
Concurrency and Race Condition Tests for Conversations.
Tests monotonic version increments, stale AI turn cancellation, and human takeover overrides.
(Baseline Controls 57, 58)
"""
import pytest
import asyncio
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from src.backend.models.entities import Base, Tenant, User, Conversation, ConversationMessage
from src.backend.domains.conversations.service import (
    ConversationService, StaleTurnError, ConversationDomainError
)
from src.backend.integrations.base import NormalizedInboundEvent

@asynccontextmanager
async def get_race_test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        t = Tenant(id="t_race_01", name="Race Test Tenant", slug="race-tenant")
        u = User(
            id="u_rep_01", tenant_id="t_race_01", email="rep@race.ma",
            hashed_password="pw", full_name="Sales Representative"
        )
        session.add(t)
        session.add(u)
        await session.commit()

    async with session_factory() as session:
        yield session

    await engine.dispose()

@pytest.mark.asyncio
async def test_monotonic_version_increments():
    async with get_race_test_db() as session:
        # Message 1 -> Version 1
        ev1 = NormalizedInboundEvent(
            tenant_id="t_race_01", channel_type="WEB_CHAT",
            provider_event_id="ev_01", sender_identifier="web_user_1",
            content="First message"
        )
        msg1 = await ConversationService.process_normalized_event(session, ev1)
        assert msg1.conversation_version == 1

        # Message 2 -> Version 2
        ev2 = NormalizedInboundEvent(
            tenant_id="t_race_01", channel_type="WEB_CHAT",
            provider_event_id="ev_02", sender_identifier="web_user_1",
            content="Second message"
        )
        msg2 = await ConversationService.process_normalized_event(session, ev2)
        assert msg2.conversation_version == 2

        conv = (await session.execute(select(Conversation).where(Conversation.id == msg1.conversation_id))).scalars().first()
        assert conv.version == 2

@pytest.mark.asyncio
async def test_stale_ai_turn_rejected_on_inbound_customer_message_race():
    async with get_race_test_db() as session:
        # 1. Customer sends message 1 -> conversation created at version 1
        ev1 = NormalizedInboundEvent(
            tenant_id="t_race_01", channel_type="WHATSAPP",
            provider_event_id="wamid.turn1", sender_identifier="212611223344",
            content="Chhal l-prix dyal 10 serveurs?"
        )
        msg1 = await ConversationService.process_normalized_event(session, ev1)
        conv_id = msg1.conversation_id
        
        # Simulated AI background worker dispatched at version 1
        expected_ai_version = 1

        # 2. Inbound customer message 2 arrives BEFORE AI finishes generating
        ev2 = NormalizedInboundEvent(
            tenant_id="t_race_01", channel_type="WHATSAPP",
            provider_event_id="wamid.turn2", sender_identifier="212611223344",
            content="W 3afak zid m3ahom garantie 3 ans"
        )
        await ConversationService.process_normalized_event(session, ev2)
        # Conversation version is now 2!

        # 3. AI attempts to submit its reply calculated against stale version 1
        with pytest.raises(StaleTurnError) as exc_info:
            await ConversationService.post_ai_reply(
                session=session,
                tenant_id="t_race_01",
                conversation_id=conv_id,
                expected_version=expected_ai_version,
                content="Le prix pour 10 serveurs est 150,000 MAD."
            )
        assert "version conflict" in str(exc_info.value).lower()

@pytest.mark.asyncio
async def test_human_takeover_cancels_in_flight_ai_turn():
    async with get_race_test_db() as session:
        # 1. Initial message at version 1
        ev1 = NormalizedInboundEvent(
            tenant_id="t_race_01", channel_type="WEB_CHAT",
            provider_event_id="web_race_01", sender_identifier="web_client_99",
            content="I need urgent assistance with billing"
        )
        msg1 = await ConversationService.process_normalized_event(session, ev1)
        conv_id = msg1.conversation_id

        # AI turn starts generating at version 1
        in_flight_ai_version = 1

        # 2. Human agent takes over conversation atomically
        conv = await ConversationService.transfer_to_human(
            session=session,
            tenant_id="t_race_01",
            conversation_id=conv_id,
            operator_id="u_rep_01",
            reason="Billing Escalation"
        )
        assert conv.status == "HUMAN_ACTIVE"
        assert conv.is_ai_silenced is True
        assert conv.version == 2

        # 3. AI finishes and tries to post reply
        with pytest.raises(StaleTurnError) as exc_info:
            await ConversationService.post_ai_reply(
                session=session,
                tenant_id="t_race_01",
                conversation_id=conv_id,
                expected_version=in_flight_ai_version,
                content="Our billing department is available weekdays."
            )
        assert "ai is silenced" in str(exc_info.value).lower() or "version conflict" in str(exc_info.value).lower()

@pytest.mark.asyncio
async def test_inbound_burst_handling():
    async with get_race_test_db() as session:
        events = [
            NormalizedInboundEvent(
                tenant_id="t_race_01", channel_type="WHATSAPP",
                provider_event_id=f"burst_msg_{i}", sender_identifier="212699887766",
                content=f"Burst message part {i}"
            )
            for i in range(1, 6)
        ]

        # Process burst sequentially through durable domain pipeline
        processed_messages = []
        for ev in events:
            msg = await ConversationService.process_normalized_event(session, ev)
            processed_messages.append(msg)

        assert len(processed_messages) == 5
        versions = [m.conversation_version for m in processed_messages]
        assert versions == [1, 2, 3, 4, 5]

        conv = (await session.execute(select(Conversation).where(Conversation.id == processed_messages[0].conversation_id))).scalars().first()
        assert conv.version == 5
        assert conv.unread_count == 5
