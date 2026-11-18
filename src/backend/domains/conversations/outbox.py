"""
Transactional Outbox and Dead-Letter Queue (DLQ) Service.
Ensures zero message loss, resilient provider retries with exponential backoff,
high-priority immediate safety bypass, and administrative DLQ auditing.
(Step 03 Architecture; Baseline Controls 16, 17, 34, 42)
"""
import json
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Callable, Awaitable
from sqlalchemy import select, or_, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import engine, AsyncSessionLocal
from src.backend.models.entities import OutboxEvent, AuditEvent, ChannelIdentity, Tenant

class OutboxStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"

class OutboxMessageClass:
    MARKETING = "MARKETING"
    TRANSACTIONAL = "TRANSACTIONAL"
    SERVICE = "SERVICE"
    SECURITY = "SECURITY"

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
        message_class: str = OutboxMessageClass.TRANSACTIONAL,
        max_retries: int = 3,
        now: Optional[datetime] = None
    ) -> OutboxEvent:
        """
        Enqueues an outbound event in the same transaction as the domain state mutation.
        High-priority events (STOP notices, safety alerts) are flagged for immediate priority dispatch.
        """
        current_time = now or datetime.now(timezone.utc)
        payload_json = json.dumps(payload_dict, default=str)

        bind = session.bind or engine
        if bind and getattr(bind.dialect, "name", None) == "postgresql":
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :t, true)"),
                {"t": str(tenant_id)}
            )

        outbox_event = OutboxEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            event_type=event_type,
            channel_type=channel_type,
            message_class=message_class,
            recipient_identifier=recipient_identifier,
            payload_json=payload_json,
            status=OutboxStatus.PENDING,
            retry_count=0,
            max_retries=max_retries,
            next_retry_at=current_time,
            last_error=None,
            is_high_priority=is_high_priority,
            claim_token=None,
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
        backoff_base_seconds: int = 2,
        worker_id: Optional[str] = None,
        lease_duration_seconds: int = 60,
        tenant_id: Optional[str] = None
    ) -> List[OutboxEvent]:
        """
        Three-Phase Leased Outbox Dispatcher with Fencing Tokens (MED-01, HIGH-01, CRIT-02).
        
        Phase A (Claim & Commit in short DB Tx):
          - Locks eligible rows with FOR UPDATE SKIP LOCKED.
          - Assigns a cryptographic claim_token, lease expiration, and PROCESSING status.
          - Commits immediately, releasing all DB locks and connection before network I/O.
          
        Phase B (Network I/O with ZERO held DB locks):
          - Pre-dispatch opt-out suppression check (only suppresses MARKETING class messages!).
          - Dispatches via external provider callable without any active database transaction.
          
        Phase C (Finalize & Commit with Fencing Token in short DB Tx):
          - In a new short transaction, updates rows matching WHERE id = :id AND claim_token = :token.
          - Transitions to DELIVERED or schedules exponential backoff / DEAD_LETTER.
          - Fencing token rejects stale worker commits if lease expired and was re-claimed.
        """
        current_time = now or datetime.now(timezone.utc)
        worker = worker_id or f"outbox_worker_{uuid.uuid4().hex[:8]}"
        lease_expires = current_time + timedelta(seconds=lease_duration_seconds)
        bind = session.bind or engine

        # -------------------------------------------------------------
        # PHASE A: Claim & Commit in short DB transaction
        # -------------------------------------------------------------
        if tenant_id and bind and getattr(bind.dialect, "name", None) == "postgresql":
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :t, true)"),
                {"t": str(tenant_id)}
            )

        eligibility = or_(
            and_(
                OutboxEvent.status.in_([OutboxStatus.PENDING, OutboxStatus.FAILED]),
                OutboxEvent.next_retry_at <= current_time
            ),
            and_(
                OutboxEvent.status == OutboxStatus.PROCESSING,
                OutboxEvent.claim_expires_at <= current_time
            )
        )

        stmt = (
            select(OutboxEvent)
            .where(eligibility)
            .order_by(
                OutboxEvent.is_high_priority.desc(),
                OutboxEvent.created_at.asc()
            )
            .limit(limit)
        )

        if tenant_id:
            stmt = stmt.where(OutboxEvent.tenant_id == tenant_id)

        if bind and getattr(bind.dialect, "name", None) == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)

        res = await session.execute(stmt)
        claimed_events = list(res.scalars().all())

        if not claimed_events:
            return []

        # Assign fencing tokens and claim leases
        claimed_data = []
        for ev in claimed_events:
            token = str(uuid.uuid4())
            ev.status = OutboxStatus.PROCESSING
            ev.claimed_by = worker
            ev.claim_token = token
            ev.claim_expires_at = lease_expires
            claimed_data.append((ev.id, token, ev))

        await session.flush()
        await session.commit()  # Locks released before network calls!

        # -------------------------------------------------------------
        # PHASE B: External Network I/O (NO DB LOCKS / TRANSACTIONS HELD)
        # -------------------------------------------------------------
        results = []
        for event_id, token, ev in claimed_data:
            is_suppressed = False
            # Check opt-out: only suppress MARKETING messages (HIGH-01)
            if ev.message_class == OutboxMessageClass.MARKETING:
                if tenant_id and bind and getattr(bind.dialect, "name", None) == "postgresql":
                    await session.execute(
                        text("SELECT set_config('app.current_tenant_id', :t, true)"),
                        {"t": str(ev.tenant_id)}
                    )
                id_stmt = select(ChannelIdentity).where(
                    ChannelIdentity.tenant_id == ev.tenant_id,
                    ChannelIdentity.channel_type == ev.channel_type,
                    ChannelIdentity.identifier == ev.recipient_identifier
                )
                id_res = await session.execute(id_stmt)
                identity = id_res.scalars().first()
                if identity and identity.is_opted_out:
                    is_suppressed = True

            if is_suppressed:
                results.append((event_id, token, OutboxStatus.CANCELLED, "Suppressed: recipient has opted out (STOP directive)", True))
                continue

            success = True
            error_msg = None
            if dispatcher_callable:
                try:
                    res_bool = await dispatcher_callable(ev)
                    if not res_bool:
                        success = False
                        error_msg = "Dispatcher returned false/unsuccessful"
                except Exception as exc:
                    success = False
                    error_msg = str(exc)
            else:
                success = True

            if success:
                results.append((event_id, token, OutboxStatus.DELIVERED, None, False))
            else:
                results.append((event_id, token, OutboxStatus.FAILED, error_msg, False))

        # -------------------------------------------------------------
        # PHASE C: Finalize State with Fencing Token in short DB Tx
        # -------------------------------------------------------------
        if tenant_id and bind and getattr(bind.dialect, "name", None) == "postgresql":
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :t, true)"),
                {"t": str(tenant_id)}
            )

        finalized_events = []
        for event_id, token, outcome_status, error_msg, is_suppressed in results:
            fetch_stmt = select(OutboxEvent).where(
                OutboxEvent.id == event_id,
                OutboxEvent.claim_token == token
            )
            if bind and getattr(bind.dialect, "name", None) == "postgresql":
                fetch_stmt = fetch_stmt.with_for_update()

            fetch_res = await session.execute(fetch_stmt)
            event_row = fetch_res.scalars().first()

            if not event_row:
                # Fencing token mismatch / lease expired and re-claimed by another worker!
                # Discard stale result to prevent overwriting active owner
                continue

            event_row.claimed_by = None
            event_row.claim_token = None
            event_row.claim_expires_at = None

            if is_suppressed:
                event_row.status = OutboxStatus.CANCELLED
                event_row.last_error = error_msg
                event_row.processed_at = current_time
            elif outcome_status == OutboxStatus.DELIVERED:
                event_row.status = OutboxStatus.DELIVERED
                event_row.processed_at = current_time
                event_row.last_error = None
            else:
                event_row.retry_count += 1
                event_row.last_error = error_msg
                if event_row.retry_count >= event_row.max_retries:
                    event_row.status = OutboxStatus.DEAD_LETTER
                    event_row.processed_at = current_time

                    audit = AuditEvent(
                        id=str(uuid.uuid4()),
                        tenant_id=event_row.tenant_id,
                        actor_id="system_outbox_dispatcher",
                        event_type="OUTBOX_DEAD_LETTER",
                        resource_type="OUTBOX_EVENT",
                        resource_id=event_row.id,
                        action="DEAD_LETTER_EXHAUSTED",
                        status="FAILURE",
                        payload_json=json.dumps({
                            "error": error_msg,
                            "retry_count": event_row.retry_count,
                            "channel_type": event_row.channel_type,
                            "recipient": event_row.recipient_identifier,
                            "event_type": event_row.event_type
                        })
                    )
                    session.add(audit)
                else:
                    event_row.status = OutboxStatus.FAILED
                    delay_seconds = backoff_base_seconds ** event_row.retry_count
                    event_row.next_retry_at = current_time + timedelta(seconds=delay_seconds)

            finalized_events.append(event_row)

        await session.flush()
        await session.commit()
        return finalized_events

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
        await session.flush()
        await session.commit()
        return event

class OutboxWorkerDaemon:
    """
    Background worker daemon for continuous asynchronous outbox event draining.
    (Baseline Control 16, 17, 34; Step 03 Reliability)
    """
    def __init__(
        self,
        session_factory: Optional[Callable[[], AsyncSession]] = None,
        dispatcher_callable: Optional[Callable[[OutboxEvent], Awaitable[bool]]] = None,
        poll_interval_seconds: float = 2.0,
        worker_id: Optional[str] = None
    ):
        self.session_factory = session_factory or AsyncSessionLocal
        self.dispatcher_callable = dispatcher_callable
        self.poll_interval = poll_interval_seconds
        self.worker_id = worker_id or f"daemon_{uuid.uuid4().hex[:8]}"
        self.running = False
        self._task: Optional[asyncio.Task] = None

    async def run_once(self, tenant_id: Optional[str] = None, limit: int = 50) -> int:
        """Executes a single draining iteration with strict multi-tenant context handling."""
        async with self.session_factory() as session:
            if tenant_id:
                events = await OutboxService.dispatch_pending_events(
                    session=session,
                    tenant_id=tenant_id,
                    dispatcher_callable=self.dispatcher_callable,
                    limit=limit,
                    worker_id=self.worker_id
                )
                return len(events)
            else:
                t_res = await session.execute(select(Tenant.id).where(Tenant.is_active == True))
                active_tenants = [row[0] for row in t_res.all()]
                total = 0
                for t_id in active_tenants:
                    events = await OutboxService.dispatch_pending_events(
                        session=session,
                        tenant_id=t_id,
                        dispatcher_callable=self.dispatcher_callable,
                        limit=limit,
                        worker_id=self.worker_id
                    )
                    total += len(events)
                return total

    async def _loop(self):
        while self.running:
            try:
                await self.run_once()
            except Exception:
                pass
            await asyncio.sleep(self.poll_interval)

    def start(self):
        if not self.running:
            self.running = True
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
