"""
Transactional Outbox and Dead-Letter Queue (DLQ) Service.
Ensures zero message loss, resilient provider retries with exponential backoff,
high-priority immediate safety bypass, and administrative DLQ auditing.
(Step 03 Architecture; Baseline Controls 16, 17, 34, 42)
"""
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Callable, Awaitable
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.models.entities import OutboxEvent, AuditEvent

class OutboxStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"

class OutboxService:
    """Enterprise domain service for transactional outbox dispatch and DLQ management."""

    @staticmethod
    async def enqueue_outbound_event(
        session: AsyncSession,
        tenant_id: str,
        channel_type: str,
        recipient_identifier: str,
        event_type: str,
        payload_dict: Dict[str, Any],
        conversation_id: Optional[str] = None,
        is_high_priority: bool = False,
        max_retries: int = 3,
        now: Optional[datetime] = None
    ) -> OutboxEvent:
        """
        Enqueues an outbound event in the same transaction as the domain state mutation.
        High-priority events (STOP notices, safety alerts) are flagged for immediate priority dispatch.
        """
        current_time = now or datetime.now(timezone.utc)
        payload_json = json.dumps(payload_dict, default=str)

        outbox_event = OutboxEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            event_type=event_type,
            channel_type=channel_type,
            recipient_identifier=recipient_identifier,
            payload_json=payload_json,
            status=OutboxStatus.PENDING,
            retry_count=0,
            max_retries=max_retries,
            next_retry_at=current_time,
            last_error=None,
            is_high_priority=is_high_priority,
            created_at=current_time
        )
        session.add(outbox_event)
        await session.flush()
        return outbox_event

    @staticmethod
    async def dispatch_pending_events(
        session: AsyncSession,
        dispatcher_callable: Optional[Callable[[OutboxEvent], Awaitable[bool]]] = None,
        limit: int = 50,
        now: Optional[datetime] = None,
        backoff_base_seconds: int = 2
    ) -> List[OutboxEvent]:
        """
        Fetches and dispatches pending or retriable outbox events.
        Order: High-priority first (bypassing normal delays), then oldest created.
        On failure: increments retry count with exponential backoff (base * 2^retry).
        On max retries: transitions to DEAD_LETTER and emits AuditEvent.
        """
        current_time = now or datetime.now(timezone.utc)

        stmt = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status.in_([OutboxStatus.PENDING, OutboxStatus.FAILED]),
                OutboxEvent.next_retry_at <= current_time
            )
            .order_by(
                OutboxEvent.is_high_priority.desc(),
                OutboxEvent.created_at.asc()
            )
            .limit(limit)
        )
        res = await session.execute(stmt)
        events = list(res.scalars().all())

        for event in events:
            event.status = OutboxStatus.PROCESSING
            await session.flush()

            success = True
            error_msg = None

            if dispatcher_callable:
                try:
                    result = await dispatcher_callable(event)
                    if not result:
                        success = False
                        error_msg = "Dispatcher returned false/unsuccessful"
                except Exception as exc:
                    success = False
                    error_msg = str(exc)
            else:
                # Default simulated dispatch (e.g., in unit testing without external provider)
                success = True

            if success:
                event.status = OutboxStatus.DELIVERED
                event.processed_at = current_time
                event.last_error = None
            else:
                event.retry_count += 1
                event.last_error = error_msg

                if event.retry_count >= event.max_retries:
                    event.status = OutboxStatus.DEAD_LETTER
                    event.processed_at = current_time

                    # Emit AuditEvent for DEAD_LETTER
                    audit = AuditEvent(
                        id=str(uuid.uuid4()),
                        tenant_id=event.tenant_id,
                        actor_id="system_outbox_dispatcher",
                        event_type="OUTBOX_DEAD_LETTER",
                        resource_type="OUTBOX_EVENT",
                        resource_id=event.id,
                        action="DEAD_LETTER_EXHAUSTED",
                        status="FAILURE",
                        payload_json=json.dumps({
                            "error": error_msg,
                            "retry_count": event.retry_count,
                            "channel_type": event.channel_type,
                            "recipient": event.recipient_identifier,
                            "event_type": event.event_type
                        })
                    )
                    session.add(audit)
                else:
                    event.status = OutboxStatus.FAILED
                    delay_seconds = backoff_base_seconds ** event.retry_count
                    event.next_retry_at = current_time + timedelta(seconds=delay_seconds)

        await session.commit()
        return events

    @staticmethod
    async def get_dead_letter_events(
        session: AsyncSession,
        tenant_id: str,
        limit: int = 50
    ) -> List[OutboxEvent]:
        """Lists dead letter events for a given tenant."""
        stmt = (
            select(OutboxEvent)
            .where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.status == OutboxStatus.DEAD_LETTER
            )
            .order_by(OutboxEvent.created_at.desc())
            .limit(limit)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def redrive_dead_letter_event(
        session: AsyncSession,
        tenant_id: str,
        event_id: str,
        now: Optional[datetime] = None
    ) -> OutboxEvent:
        """Manually redrives a DEAD_LETTER event back to PENDING."""
        current_time = now or datetime.now(timezone.utc)
        stmt = select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.id == event_id
        )
        res = await session.execute(stmt)
        event = res.scalars().first()
        if not event:
            raise ValueError(f"Outbox event {event_id} not found in tenant {tenant_id}")

        event.status = OutboxStatus.PENDING
        event.retry_count = 0
        event.next_retry_at = current_time
        event.last_error = None
        event.processed_at = None

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_id="system_outbox_operator",
            event_type="OUTBOX_REDRIVE",
            resource_type="OUTBOX_EVENT",
            resource_id=event.id,
            action="MANUAL_REDRIVE",
            status="SUCCESS",
            payload_json=json.dumps({"event_id": event.id, "channel": event.channel_type})
        )
        session.add(audit)
        await session.commit()
        await session.refresh(event)
        return event
