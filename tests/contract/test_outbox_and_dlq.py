"""
Contract & Integration Tests for Transactional Outbox, Exponential Backoff,
Dead-Letter Queue (DLQ), and High-Priority Safety Bypass.
(Step 03 Architecture; Baseline Controls 16, 17, 34, 42)
"""
import pytest
import uuid
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

from src.backend.models.entities import (
    Base, Tenant, Contact, Conversation, OutboxEvent, AuditEvent
)
from src.backend.domains.conversations.outbox import OutboxService, OutboxStatus

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@asynccontextmanager
async def get_outbox_test_db():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        # Seed test tenant and conversation
        tenant = Tenant(id="tenant_outbox_test", name="Outbox Test Tenant", slug="outbox-tenant")
        contact = Contact(id="contact_outbox_1", tenant_id="tenant_outbox_test", display_name="Test Recipient")
        conv = Conversation(
            id="conv_outbox_1",
            tenant_id="tenant_outbox_test",
            contact_id="contact_outbox_1",
            channel_type="WHATSAPP",
            channel_identifier="+212600000001",
            status="BOT_ACTIVE",
            version=1
        )
        session.add_all([tenant, contact, conv])
        await session.commit()

    async with session_factory() as session:
        yield session

    await engine.dispose()

@pytest.mark.asyncio
async def test_enqueue_and_successful_dispatch():
    """Verifies standard outbox event enqueue and successful delivery."""
    async with get_outbox_test_db() as session:
        event = await OutboxService.enqueue_outbound_event(
            session=session,
            tenant_id="tenant_outbox_test",
            channel_type="WHATSAPP",
            recipient_identifier="+212600000001",
            event_type="DISPATCH_MESSAGE",
            payload_dict={"text": "Hello customer"},
            conversation_id="conv_outbox_1",
            is_high_priority=False
        )
        await session.commit()

        assert event.id is not None
        assert event.status == OutboxStatus.PENDING
        assert event.retry_count == 0
        assert event.is_high_priority is False

        # Dispatch using a simulated successful dispatcher
        async def mock_dispatcher(evt):
            return True

        dispatched = await OutboxService.dispatch_pending_events(
            session=session,
            dispatcher_callable=mock_dispatcher
        )

        assert len(dispatched) == 1
        assert dispatched[0].id == event.id
        assert dispatched[0].status == OutboxStatus.DELIVERED
        assert dispatched[0].processed_at is not None
        assert dispatched[0].last_error is None

@pytest.mark.asyncio
async def test_retry_with_exponential_backoff():
    """Verifies that transient delivery errors trigger retry count increments and exponential backoff."""
    async with get_outbox_test_db() as session:
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        event = await OutboxService.enqueue_outbound_event(
            session=session,
            tenant_id="tenant_outbox_test",
            channel_type="EMAIL",
            recipient_identifier="customer@example.com",
            event_type="DISPATCH_EMAIL",
            payload_dict={"subject": "Quote", "body": "Your quote"},
            max_retries=3,
            now=now
        )
        await session.commit()

        async def failing_dispatcher(evt):
            raise ConnectionError("SMTP gateway 503 Service Unavailable")

        # Attempt 1: First failure
        dispatched = await OutboxService.dispatch_pending_events(
            session=session,
            dispatcher_callable=failing_dispatcher,
            now=now,
            backoff_base_seconds=2
        )

        assert len(dispatched) == 1
        assert dispatched[0].status == OutboxStatus.FAILED
        assert dispatched[0].retry_count == 1
        assert "SMTP gateway 503" in dispatched[0].last_error
        # Backoff: 2^1 = 2 seconds
        expected_retry_1 = now + timedelta(seconds=2)
        assert dispatched[0].next_retry_at == expected_retry_1

        # Before next_retry_at -> Dispatcher skips it
        skip_run = await OutboxService.dispatch_pending_events(
            session=session,
            dispatcher_callable=failing_dispatcher,
            now=now + timedelta(seconds=1)
        )
        assert len(skip_run) == 0

        # Attempt 2: After next_retry_at
        dispatched_2 = await OutboxService.dispatch_pending_events(
            session=session,
            dispatcher_callable=failing_dispatcher,
            now=now + timedelta(seconds=3),
            backoff_base_seconds=2
        )
        assert len(dispatched_2) == 1
        assert dispatched_2[0].retry_count == 2
        # Backoff: 2^2 = 4 seconds from attempt 2
        expected_retry_2 = (now + timedelta(seconds=3)) + timedelta(seconds=4)
        assert dispatched_2[0].next_retry_at == expected_retry_2

@pytest.mark.asyncio
async def test_dead_letter_queue_and_audit_emission():
    """Verifies that exceeding max retries routes event to DEAD_LETTER and emits an AuditEvent."""
    async with get_outbox_test_db() as session:
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        event = await OutboxService.enqueue_outbound_event(
            session=session,
            tenant_id="tenant_outbox_test",
            channel_type="WHATSAPP",
            recipient_identifier="+212600000002",
            event_type="DISPATCH_MESSAGE",
            payload_dict={"text": "Unreachable number"},
            max_retries=1,  # Exhaust on first attempt
            now=now
        )
        await session.commit()

        async def permanent_failure_dispatcher(evt):
            raise ValueError("Invalid recipient destination: 400 Bad Request")

        dispatched = await OutboxService.dispatch_pending_events(
            session=session,
            dispatcher_callable=permanent_failure_dispatcher,
            now=now
        )

        assert len(dispatched) == 1
        dlq_event = dispatched[0]
        assert dlq_event.status == OutboxStatus.DEAD_LETTER
        assert dlq_event.retry_count == 1
        assert "Invalid recipient" in dlq_event.last_error

        # Verify AuditEvent was emitted for Dead Letter Queue
        audit_stmt = select(AuditEvent).where(
            AuditEvent.tenant_id == "tenant_outbox_test",
            AuditEvent.event_type == "OUTBOX_DEAD_LETTER"
        )
        a_res = await session.execute(audit_stmt)
        audits = a_res.scalars().all()
        assert len(audits) == 1
        assert audits[0].resource_id == dlq_event.id
        assert audits[0].status == "FAILURE"

@pytest.mark.asyncio
async def test_high_priority_safety_bypass():
    """
    Verifies that high-priority events (STOP opt-out acknowledgements, safety alerts)
    outrank normal pending events and are dispatched first.
    """
    async with get_outbox_test_db() as session:
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Enqueue older normal message
        normal_event = await OutboxService.enqueue_outbound_event(
            session=session,
            tenant_id="tenant_outbox_test",
            channel_type="WHATSAPP",
            recipient_identifier="+212600000001",
            event_type="DISPATCH_MESSAGE",
            payload_dict={"text": "Promotional follow-up"},
            is_high_priority=False,
            now=now - timedelta(minutes=5)
        )

        # 2. Enqueue newer high-priority safety STOP event
        safety_event = await OutboxService.enqueue_outbound_event(
            session=session,
            tenant_id="tenant_outbox_test",
            channel_type="WHATSAPP",
            recipient_identifier="+212600000001",
            event_type="CONSENT_STOP_ACK",
            payload_dict={"text": "STOP directive received. AI disabled."},
            is_high_priority=True,
            now=now
        )
        await session.commit()

        dispatch_order = []
        async def recording_dispatcher(evt):
            dispatch_order.append(evt.id)
            return True

        await OutboxService.dispatch_pending_events(
            session=session,
            dispatcher_callable=recording_dispatcher,
            now=now
        )

        # Safety event MUST be dispatched first despite being created later
        assert len(dispatch_order) == 2
        assert dispatch_order[0] == safety_event.id
        assert dispatch_order[1] == normal_event.id

@pytest.mark.asyncio
async def test_manual_redrive_from_dead_letter():
    """Verifies that an administrator can inspect and redrive a dead letter outbox event."""
    async with get_outbox_test_db() as session:
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
        event = await OutboxService.enqueue_outbound_event(
            session=session,
            tenant_id="tenant_outbox_test",
            channel_type="EMAIL",
            recipient_identifier="client@domain.ma",
            event_type="DISPATCH_EMAIL",
            payload_dict={"body": "Order Confirmation"},
            max_retries=1,
            now=now
        )
        await session.commit()

        async def fail_fn(evt):
            raise ConnectionResetError("Server dropped connection")

        await OutboxService.dispatch_pending_events(session=session, dispatcher_callable=fail_fn, now=now)

        # Confirm in dead letter list
        dlq_list = await OutboxService.get_dead_letter_events(session=session, tenant_id="tenant_outbox_test")
        assert len(dlq_list) == 1
        assert dlq_list[0].id == event.id

        # Redrive
        redriven = await OutboxService.redrive_dead_letter_event(
            session=session,
            tenant_id="tenant_outbox_test",
            event_id=event.id,
            now=now + timedelta(minutes=10)
        )
        assert redriven.status == OutboxStatus.PENDING
        assert redriven.retry_count == 0
        assert redriven.last_error is None

        # Redrive Audit Event exists
        audit_stmt = select(AuditEvent).where(
            AuditEvent.tenant_id == "tenant_outbox_test",
            AuditEvent.event_type == "OUTBOX_REDRIVE"
        )
        a_res = await session.execute(audit_stmt)
        assert len(a_res.scalars().all()) == 1
