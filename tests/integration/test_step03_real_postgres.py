"""
Integration Test Suite: Real PostgreSQL 16 Omnichannel Durability & Security Validation.
Executes against live PostgreSQL container (sales-ai-postgres) on 127.0.0.1:5432
under the unprivileged 'sales_app_user' account with FORCE ROW LEVEL SECURITY.

Verifies:
1. Finding P0-1: Webhook ingestion with PostgreSQL RLS tenant context activation & 404 on invalid tenant.
2. Finding P0-1: Domain operations (ingest, handoff, release, replies) execute without post-commit refresh crashes.
3. Finding P1-1: Outbox concurrency with SKIP LOCKED and claim leasing prevents duplicate dispatches.
4. Finding P1-1: Stale claim lease recovery by subsequent workers.
5. Finding P1-2: STOP directive purges/cancels pre-queued marketing outbox records.
6. Finding P1-2: Pre-dispatch opt-out guard in OutboxService suppresses promotional messages.
7. Finding P2-1: Concurrent inbound bursts serialize monotonic conversation version increments.
8. Finding P2-2: RBAC authorization on Human Inbox operations (Customer 403, Staff 200).
9. Standing OutboxWorkerDaemon background polling and draining.
"""
import sys
import asyncio
import uuid
import json
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
import psycopg
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, text

if sys.platform == "win32" and sys.version_info < (3, 14):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from src.backend.main import app
from src.backend.core.config import settings
from src.backend.core.database import get_db_session, current_tenant_id_ctx
import src.backend.core.database as db_mod
import src.backend.core.auth_middleware as mw_mod
from src.backend.core.security import SecurityService
from src.backend.models.entities import (
    Tenant, User, Contact, ChannelIdentity, Conversation, ConversationMessage,
    OutboxEvent, AuditEvent, InboundRawEvent
)
from src.backend.domains.conversations.service import ConversationService
from src.backend.domains.conversations.outbox import OutboxService, OutboxStatus, OutboxWorkerDaemon
from src.backend.integrations.base import NormalizedInboundEvent

PG_REAL_URL = "postgresql+psycopg://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"
def _admin_conn_str() -> str:
    """Superuser connection for test setup/teardown only; the app role cannot delete tenants (F-12)."""
    import re
    from pathlib import Path
    compose = (Path(__file__).resolve().parents[2] / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    pw = re.search(r"POSTGRES_PASSWORD:-([^}]+)\}", compose).group(1)
    return f"postgresql://postgres:{pw}@127.0.0.1:5432/sales_ai_db"


PG_SYNC_CONN = "postgresql://sales_app_user:sales_app_dev_password@127.0.0.1:5432/sales_ai_db"

@pytest.fixture(scope="module")
def seed_real_pg_tenant():
    """Sets up an active and an inactive tenant, plus users in live PostgreSQL."""
    t_active = f"t_pg_{uuid.uuid4().hex[:8]}"
    t_inactive = f"t_pg_inact_{uuid.uuid4().hex[:8]}"
    cust_id = f"cust_{uuid.uuid4().hex[:8]}"
    rep_id = f"rep_{uuid.uuid4().hex[:8]}"

    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            # 1. Tenants
            cur.execute(
                "INSERT INTO tenants (id, name, slug, is_active) VALUES (%s, %s, %s, %s), (%s, %s, %s, %s);",
                (t_active, "Real Postgres Tenant", f"slug-{t_active}", True,
                 t_inactive, "Inactive Tenant", f"slug-{t_inactive}", False)
            )
            # 2. Users under active tenant
            cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (t_active,))
            cur.execute(
                "INSERT INTO users (id, tenant_id, email, hashed_password, full_name, is_active, mfa_enabled) VALUES (%s, %s, %s, %s, %s, %s, %s), (%s, %s, %s, %s, %s, %s, %s);",
                (cust_id, t_active, f"customer_{cust_id}@test.com", "hash", "Customer User", True, False,
                 rep_id, t_active, f"rep_{rep_id}@test.com", "hash", "Rep User", True, True)
            )
            # 3. Channel Integration for WhatsApp pn_1
            cur.execute(
                "INSERT INTO tenant_channel_integrations (id, tenant_id, channel_type, provider_asset_id, webhook_secret, is_active) VALUES (%s, %s, %s, %s, %s, %s);",
                (f"tci_{uuid.uuid4().hex[:8]}", t_active, "WHATSAPP", "pn_1", settings.whatsapp_webhook_secret, True)
            )
            conn.commit()

    yield {
        "active_tenant_id": t_active,
        "inactive_tenant_id": t_inactive,
        "customer_user_id": cust_id,
        "rep_user_id": rep_id
    }

    with psycopg.connect(_admin_conn_str()) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id IN (%s, %s);", (t_active, t_inactive))
            conn.commit()

@asynccontextmanager
async def real_pg_session_factory():
    engine = create_async_engine(PG_REAL_URL, pool_size=10, max_overflow=10, echo=False)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False
    )
    orig_db_factory = db_mod.AsyncSessionLocal
    orig_mw_factory = mw_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = factory
    mw_mod.AsyncSessionLocal = factory

    async def override_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db_session] = override_db

    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        db_mod.AsyncSessionLocal = orig_db_factory
        mw_mod.AsyncSessionLocal = orig_mw_factory
        await engine.dispose()

@pytest.mark.asyncio
async def test_real_pg_webhook_ingest_rls_success_and_duplicates(seed_real_pg_tenant):
    """Finding P0-1: Webhook ingestion sets RLS context, handles duplicates, rejects inactive/unknown tenants."""
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    rep_id = seed_real_pg_tenant["rep_user_id"]
    inactive_id = seed_real_pg_tenant["inactive_tenant_id"]

    async with real_pg_session_factory() as session_factory:
        wamid = f"wamid_real_pg_{uuid.uuid4().hex[:12]}"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "entry_1",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "+212600000000", "phone_number_id": "pn_1"},
                        "contacts": [{"profile": {"name": "Mehdi Bennani"}, "wa_id": "212611223344"}],
                        "messages": [{
                            "from": "212611223344",
                            "id": wamid,
                            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                            "text": {"body": "Salam, je veux un devis pour vos serveurs"},
                            "type": "text"
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        sig = hmac.new(settings.whatsapp_webhook_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={sig}"
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Unknown tenant -> 404
            r_unknown = await client.post("/api/v1/channels/webhooks/whatsapp/t_nonexistent_999", content=body_bytes, headers=headers)
            assert r_unknown.status_code == 404, f"Expected 404 for nonexistent tenant, got {r_unknown.status_code}"

            # 2. Inactive tenant -> 404
            r_inact = await client.post(f"/api/v1/channels/webhooks/whatsapp/{inactive_id}", content=body_bytes, headers=headers)
            assert r_inact.status_code == 404, f"Expected 404 for inactive tenant, got {r_inact.status_code}"

            # 3. Active tenant with RLS -> 200 OK (no InsufficientPrivilege error)
            resp = await client.post(f"/api/v1/channels/webhooks/whatsapp/{tenant_id}", content=body_bytes, headers=headers)
            assert resp.status_code == 200, f"Webhook ingest failed with status {resp.status_code}: {resp.text}"
            data = resp.json()
            assert data["status"] == "success"
            assert data["processed_count"] == 1

            # 4. Duplicate replay -> 200 OK duplicate_ignored
            r_dup = await client.post(f"/api/v1/channels/webhooks/whatsapp/{tenant_id}", content=body_bytes, headers=headers)
            assert r_dup.status_code == 200
            assert r_dup.json()["status"] == "duplicate_ignored"

@pytest.mark.asyncio
async def test_real_pg_domain_operations_without_refresh_crash(seed_real_pg_tenant):
    """Finding P0-1: Verifies domain service lifecycle executes without refresh crashes on real PostgreSQL."""
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    rep_id = seed_real_pg_tenant["rep_user_id"]

    async with real_pg_session_factory() as session_factory:
        async with session_factory() as session:
            # 1. Ingest raw event
            raw = await ConversationService.ingest_raw_event(
                session=session,
                tenant_id=tenant_id,
                channel_type="WHATSAPP",
                provider_event_id=f"evt_pg_{uuid.uuid4().hex[:8]}",
                payload_dict={"msg": "Test lifecycle"}
            )
            assert raw.id is not None
            assert raw.processing_status == "PENDING"

            # 2. Process normalized event
            norm = NormalizedInboundEvent(
                tenant_id=tenant_id,
                channel_type="WHATSAPP",
                provider_event_id=f"norm_pg_{uuid.uuid4().hex[:8]}",
                sender_identifier="+212699887766",
                sender_name="Karim Tazi",
                content="Je suis interesse par votre offre",
                event_type="MESSAGE",
                attachments=[],
                raw_payload={},
                timestamp=datetime.now(timezone.utc)
            )
            msg = await ConversationService.process_normalized_event(session=session, event=norm)
            assert msg.id is not None
            conv_id = msg.conversation_id
            assert msg.conversation_version == 1

            # 3. Transfer to human operator (Atomic Takeover)
            conv = await ConversationService.transfer_to_human(
                session=session,
                tenant_id=tenant_id,
                conversation_id=conv_id,
                operator_id=rep_id,
                reason="Customer high value request"
            )
            assert conv.status == "HUMAN_ACTIVE"
            assert conv.is_ai_silenced is True
            assert conv.version == 2

            # 4. Release back to AI bot
            conv = await ConversationService.release_to_bot(
                session=session,
                tenant_id=tenant_id,
                conversation_id=conv_id,
                operator_id=rep_id
            )
            assert conv.status == "BOT_ACTIVE"
            assert conv.is_ai_silenced is False
            assert conv.version == 3

            # 5. Post AI reply
            ai_msg = await ConversationService.post_ai_reply(
                session=session,
                tenant_id=tenant_id,
                conversation_id=conv_id,
                expected_version=3,
                content="Voici les specifications techniques demandees."
            )
            assert ai_msg.id is not None
            assert ai_msg.conversation_version == 4

            # 6. Post human agent reply
            agent_msg = await ConversationService.post_agent_reply(
                session=session,
                tenant_id=tenant_id,
                conversation_id=conv_id,
                agent_user_id=rep_id,
                content="Je reste a votre disposition pour toute question."
            )
            assert agent_msg.id is not None
            assert agent_msg.conversation_version == 5

@pytest.mark.asyncio
async def test_real_pg_outbox_skip_locked_concurrency(seed_real_pg_tenant):
    """Finding P1-1: Concurrent workers using SKIP LOCKED claim disjoint batches without overlap."""
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    rep_id = seed_real_pg_tenant["rep_user_id"]

    async with real_pg_session_factory() as session_factory:
        # Seed 6 pending outbox events
        event_ids = []
        async with session_factory() as session:
            for i in range(6):
                ev = await OutboxService.enqueue_outbound_event(
                    session=session,
                    tenant_id=tenant_id,
                    channel_type="WHATSAPP",
                    recipient_identifier=f"+21260000000{i}",
                    event_type="DISPATCH_MESSAGE",
                    payload_dict={"text": f"Batch message {i}"}
                )
                event_ids.append(ev.id)
            await session.commit()

        # Dispatched tracking
        worker_1_dispatched = []
        worker_2_dispatched = []

        async def worker_1_dispatch(ev: OutboxEvent) -> bool:
            worker_1_dispatched.append(ev.id)
            await asyncio.sleep(0.05)
            return True

        async def worker_2_dispatch(ev: OutboxEvent) -> bool:
            worker_2_dispatched.append(ev.id)
            await asyncio.sleep(0.05)
            return True

        async def run_worker_1():
            async with session_factory() as s1:
                return await OutboxService.dispatch_pending_events(
                    session=s1,
                    tenant_id=tenant_id,
                    dispatcher_callable=worker_1_dispatch,
                    limit=3,
                    worker_id="worker_1"
                )

        async def run_worker_2():
            async with session_factory() as s2:
                return await OutboxService.dispatch_pending_events(
                    session=s2,
                    tenant_id=tenant_id,
                    dispatcher_callable=worker_2_dispatch,
                    limit=3,
                    worker_id="worker_2"
                )

        # Run simultaneously
        res1, res2 = await asyncio.gather(run_worker_1(), run_worker_2())

        claimed_1 = set(worker_1_dispatched)
        claimed_2 = set(worker_2_dispatched)

        # Strict disjointness invariant
        overlap = claimed_1.intersection(claimed_2)
        assert len(overlap) == 0, f"Concurrency violation: Workers processed identical events: {overlap}"
        assert len(claimed_1) + len(claimed_2) == 6, f"Expected all 6 events claimed, got {len(claimed_1) + len(claimed_2)}"

@pytest.mark.asyncio
async def test_real_pg_outbox_stale_claim_recovery(seed_real_pg_tenant):
    """Finding P1-1: Stale lease recovery when a previous worker process crashes."""
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    rep_id = seed_real_pg_tenant["rep_user_id"]

    now = datetime.now(timezone.utc)
    expired_lease = now - timedelta(seconds=120)

    # Seed an event stuck in PROCESSING by a crashed worker
    stale_event_id = str(uuid.uuid4())
    async with real_pg_session_factory() as session_factory:
        async with session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            stale_ev = OutboxEvent(
                id=stale_event_id,
                tenant_id=tenant_id,
                channel_type="EMAIL",
                recipient_identifier="stale@example.com",
                event_type="DISPATCH_MESSAGE",
                payload_json=json.dumps({"text": "Stale recovery test"}),
                status=OutboxStatus.PROCESSING,
                claimed_by="crashed_worker_dead",
                claim_expires_at=expired_lease,
                created_at=now - timedelta(minutes=5),
                next_retry_at=now - timedelta(minutes=5)
            )
            session.add(stale_ev)
            await session.commit()

        # Recovery worker runs
        recovered_dispatches = []
        async def recovery_dispatcher(ev: OutboxEvent) -> bool:
            recovered_dispatches.append(ev.id)
            return True

        async with session_factory() as session:
            events = await OutboxService.dispatch_pending_events(
                session=session,
                tenant_id=tenant_id,
                dispatcher_callable=recovery_dispatcher,
                worker_id="healthy_recovery_worker",
                now=now
            )
            assert stale_event_id in recovered_dispatches

        # Verify event is now DELIVERED and lease cleared
        async with session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            res = await session.execute(select(OutboxEvent).where(OutboxEvent.id == stale_event_id))
            ev = res.scalars().first()
            assert ev.status == OutboxStatus.DELIVERED
            assert ev.claimed_by is None
            assert ev.claim_expires_at is None

@pytest.mark.asyncio
async def test_real_pg_stop_cancels_pre_queued_marketing_outbox(seed_real_pg_tenant):
    """Finding P1-2: Multilingual STOP cancels pre-queued promotional outbox events."""
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    rep_id = seed_real_pg_tenant["rep_user_id"]
    recipient = "+212677112233"

    async with real_pg_session_factory() as session_factory:
        # 1. Customer initiates contact and gets an initial conversation
        norm = NormalizedInboundEvent(
            tenant_id=tenant_id,
            channel_type="WHATSAPP",
            provider_event_id=f"evt_init_{uuid.uuid4().hex[:8]}",
            sender_identifier=recipient,
            sender_name="Said Chraibi",
            content="Salam, marhba",
            event_type="MESSAGE",
            attachments=[],
            raw_payload={},
            timestamp=datetime.now(timezone.utc)
        )
        async with session_factory() as session:
            await ConversationService.process_normalized_event(session=session, event=norm)

        # 2. Marketing campaign enqueues 2 promotional messages + 1 transactional order receipt
        promo_ids = []
        async with session_factory() as session:
            for i in range(2):
                ev = await OutboxService.enqueue_outbound_event(
                    session=session,
                    tenant_id=tenant_id,
                    channel_type="WHATSAPP",
                    recipient_identifier=recipient,
                    event_type="PROMOTIONAL_OFFER",
                    payload_dict={"text": f"Remise speciale {i+1}0% sur les serveurs"},
                    is_high_priority=False,
                    message_class="MARKETING"
                )
                promo_ids.append(ev.id)

            # Transactional notification (invoice/order)
            tx_ev = await OutboxService.enqueue_outbound_event(
                session=session,
                tenant_id=tenant_id,
                channel_type="WHATSAPP",
                recipient_identifier=recipient,
                event_type="ORDER_CONFIRMATION",
                payload_dict={"order_id": "ord_12345", "amount": 15000},
                is_high_priority=False,
                message_class="TRANSACTIONAL"
            )
            tx_id = tx_ev.id
            await session.commit()

        # 3. Customer sends STOP in Moroccan Darija: "baraka 3afak"
        stop_event = NormalizedInboundEvent(
            tenant_id=tenant_id,
            channel_type="WHATSAPP",
            provider_event_id=f"evt_stop_{uuid.uuid4().hex[:8]}",
            sender_identifier=recipient,
            sender_name="Said Chraibi",
            content="baraka 3afak",
            event_type="MESSAGE",
            attachments=[],
            raw_payload={},
            timestamp=datetime.now(timezone.utc)
        )
        async with session_factory() as session:
            await ConversationService.process_normalized_event(session=session, event=stop_event)
            await session.commit()

        # 4. Verify promotional outbox events are CANCELLED, but TRANSACTIONAL remains PENDING
        async with session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            res = await session.execute(select(OutboxEvent).where(OutboxEvent.id.in_(promo_ids)))
            cancelled = res.scalars().all()
            for ev in cancelled:
                assert ev.status == OutboxStatus.CANCELLED
                assert "Suppressed due to STOP" in ev.last_error

            res_tx = await session.execute(select(OutboxEvent).where(OutboxEvent.id == tx_id))
            tx_event = res_tx.scalars().first()
            assert tx_event is not None
            assert tx_event.status == OutboxStatus.PENDING, "Transactional notification must NOT be cancelled on STOP!"

            # 5. Verify high-priority STOP ACK exists
            res_ack = await session.execute(
                select(OutboxEvent).where(
                    OutboxEvent.tenant_id == tenant_id,
                    OutboxEvent.recipient_identifier == recipient,
                    OutboxEvent.event_type == "CONSENT_STOP_ACK",
                    OutboxEvent.is_high_priority == True
                )
            )
            ack_event = res_ack.scalars().first()
            assert ack_event is not None
            assert ack_event.status == OutboxStatus.PENDING

@pytest.mark.asyncio
async def test_real_pg_outbox_pre_dispatch_opt_out_suppression(seed_real_pg_tenant):
    """Finding P1-2: Pre-dispatch check suppresses non-priority events for opted-out users."""
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    rep_id = seed_real_pg_tenant["rep_user_id"]
    recipient = "+212688001122"

    async with real_pg_session_factory() as session_factory:
        async with session_factory() as session:
            # Resolve contact and mark opted out
            contact, identity = await ConversationService.resolve_or_create_contact(
                session=session,
                tenant_id=tenant_id,
                channel_type="WHATSAPP",
                identifier=recipient
            )
            identity.is_opted_out = True
            identity.opt_out_at = datetime.now(timezone.utc)
            await session.commit()

            # Enqueue a message directly
            ev = await OutboxService.enqueue_outbound_event(
                session=session,
                tenant_id=tenant_id,
                channel_type="WHATSAPP",
                recipient_identifier=recipient,
                event_type="NEWSLETTER",
                payload_dict={"text": "Monthly newsletter"},
                is_high_priority=False,
                message_class="MARKETING"
            )
            await session.commit()
            ev_id = ev.id

        dispatched = []
        async def test_dispatcher(e: OutboxEvent) -> bool:
            dispatched.append(e.id)
            return True

        async with session_factory() as session:
            await OutboxService.dispatch_pending_events(
                session=session,
                tenant_id=tenant_id,
                dispatcher_callable=test_dispatcher
            )

        # Must NOT have dispatched externally
        assert ev_id not in dispatched

        # Must be marked CANCELLED
        async with session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            res = await session.execute(select(OutboxEvent).where(OutboxEvent.id == ev_id))
            ev = res.scalars().first()
            assert ev.status == OutboxStatus.CANCELLED
            assert "recipient has opted out" in ev.last_error

@pytest.mark.asyncio
async def test_real_pg_concurrent_inbound_bursts_version_serialization(seed_real_pg_tenant):
    """Finding P2-1: Concurrent inbound bursts serialize monotonic version increments via row locks."""
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    rep_id = seed_real_pg_tenant["rep_user_id"]
    recipient = f"+2126{uuid.uuid4().int % 100000000:08d}"

    async with real_pg_session_factory() as session_factory:
        # Initial inbound message establishes Conversation with version 1
        norm1 = NormalizedInboundEvent(
            tenant_id=tenant_id,
            channel_type="WHATSAPP",
            provider_event_id=f"burst_init_{uuid.uuid4().hex[:8]}",
            sender_identifier=recipient,
            sender_name="Burst Tester",
            content="First message",
            event_type="MESSAGE",
            attachments=[],
            raw_payload={},
            timestamp=datetime.now(timezone.utc)
        )
        async with session_factory() as session:
            msg1 = await ConversationService.process_normalized_event(session=session, event=norm1)
            await session.commit()
            conv_id = msg1.conversation_id
            assert msg1.conversation_version == 1

        # Two concurrent messages arrive simultaneously in separate transactions
        norm2 = NormalizedInboundEvent(
            tenant_id=tenant_id,
            channel_type="WHATSAPP",
            provider_event_id=f"burst_ev2_{uuid.uuid4().hex[:8]}",
            sender_identifier=recipient,
            sender_name="Burst Tester",
            content="Burst concurrent message A",
            event_type="MESSAGE",
            attachments=[],
            raw_payload={},
            timestamp=datetime.now(timezone.utc)
        )
        norm3 = NormalizedInboundEvent(
            tenant_id=tenant_id,
            channel_type="WHATSAPP",
            provider_event_id=f"burst_ev3_{uuid.uuid4().hex[:8]}",
            sender_identifier=recipient,
            sender_name="Burst Tester",
            content="Burst concurrent message B",
            event_type="MESSAGE",
            attachments=[],
            raw_payload={},
            timestamp=datetime.now(timezone.utc)
        )

        async def proc_burst(event):
            async with session_factory() as s:
                res = await ConversationService.process_normalized_event(session=s, event=event)
                await s.commit()
                return res

        msg_a, msg_b = await asyncio.gather(proc_burst(norm2), proc_burst(norm3))

        # Invariant: The versions must be distinct (2 and 3) and monotonically increasing, never both 2
        versions = {msg_a.conversation_version, msg_b.conversation_version}
        assert versions == {2, 3}, f"Version race condition detected! Versions were: {msg_a.conversation_version}, {msg_b.conversation_version}"

        # Verify conversation row in database has version 3
        async with session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            res = await session.execute(select(Conversation).where(Conversation.id == conv_id))
            conv = res.scalars().first()
            assert conv.version == 3

@pytest.mark.asyncio
async def test_real_pg_inbox_rbac_enforcement(seed_real_pg_tenant):
    """Finding P2-2: Human Inbox operations strictly reject Customer role (403) and grant Staff (200)."""
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    rep_id = seed_real_pg_tenant["rep_user_id"]
    cust_user_id = seed_real_pg_tenant["customer_user_id"]
    rep_user_id = seed_real_pg_tenant["rep_user_id"]

    async with real_pg_session_factory() as session_factory:
        # Create an initial conversation in real PostgreSQL
        async with session_factory() as session:
            contact, _ = await ConversationService.resolve_or_create_contact(
                session=session,
                tenant_id=tenant_id,
                channel_type="WHATSAPP",
                identifier="+212612345678"
            )
            conv = Conversation(
                id=f"conv_rbac_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                contact_id=contact.id,
                channel_type="WHATSAPP",
                channel_identifier="+212612345678",
                status="BOT_ACTIVE",
                version=1
            )
            session.add(conv)
            await session.commit()
            conv_id = conv.id

        customer_token, _, _ = SecurityService.create_access_token(
            user_id=cust_user_id,
            tenant_id=tenant_id,
            email=f"customer_{cust_user_id}@test.com",
            roles=["customer"],
            permissions=["portal:access"]
        )

        staff_token, _, _ = SecurityService.create_access_token(
            user_id=rep_user_id,
            tenant_id=tenant_id,
            email=f"rep_{rep_user_id}@test.com",
            roles=["sales_representative"],
            permissions=[]
        )

        cust_headers = {"Authorization": f"Bearer {customer_token}"}
        staff_headers = {"Authorization": f"Bearer {staff_token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Customer listing conversations -> 403 Forbidden
            r1 = await client.get("/api/v1/inbox/conversations", headers=cust_headers)
            assert r1.status_code == 403, f"Expected 403 for Customer on /conversations, got {r1.status_code}"

            # 2. Staff listing conversations -> 200 OK
            r2 = await client.get("/api/v1/inbox/conversations", headers=staff_headers)
            assert r2.status_code == 200

            # 3. Customer handoff -> 403 Forbidden
            r3 = await client.post(f"/api/v1/inbox/conversations/{conv_id}/handoff", headers=cust_headers, json={"reason": "Attacking handoff"})
            assert r3.status_code == 403, f"Expected 403 for Customer on /handoff, got {r3.status_code}"

            # 4. Customer reply -> 403 Forbidden
            r4 = await client.post(f"/api/v1/inbox/conversations/{conv_id}/reply", headers=cust_headers, json={"content": "Impersonated reply"})
            assert r4.status_code == 403, f"Expected 403 for Customer on /reply, got {r4.status_code}"

            # 5. Staff handoff -> 200 OK
            r5 = await client.post(f"/api/v1/inbox/conversations/{conv_id}/handoff", headers=staff_headers, json={"reason": "Legitimate rep handoff"})
            assert r5.status_code == 200
            assert r5.json()["conversation_status"] == "HUMAN_ACTIVE"

            # 6. Staff reply -> 200 OK
            r6 = await client.post(f"/api/v1/inbox/conversations/{conv_id}/reply", headers=staff_headers, json={"content": "Bonjour, je suis votre commercial."})
            assert r6.status_code == 200
            assert r6.json()["status"] == "success"

@pytest.mark.asyncio
async def test_real_pg_standing_outbox_worker_daemon(seed_real_pg_tenant):
    """Finding 6.3: Verifies standing background OutboxWorkerDaemon drains pending queue."""
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    rep_id = seed_real_pg_tenant["rep_user_id"]

    dispatched = []
    async def daemon_dispatch(ev: OutboxEvent) -> bool:
        dispatched.append(ev.id)
        return True

    async with real_pg_session_factory() as session_factory:
        daemon = OutboxWorkerDaemon(
            session_factory=session_factory,
            dispatcher_callable=daemon_dispatch,
            poll_interval_seconds=0.1
        )

        # Seed an event
        async with session_factory() as session:
            ev = await OutboxService.enqueue_outbound_event(
                session=session,
                tenant_id=tenant_id,
                channel_type="EMAIL",
                recipient_identifier="daemon@test.com",
                event_type="NOTIFICATION",
                payload_dict={"subject": "Daemon test"}
            )
            await session.commit()
            ev_id = ev.id

        # Start daemon
        daemon.start()
        try:
            # Wait up to 3 seconds for daemon to process
            for _ in range(30):
                if ev_id in dispatched:
                    break
                await asyncio.sleep(0.1)

            assert ev_id in dispatched, f"Daemon did not process event {ev_id} within 3s"

            # Verify status in DB
            async with session_factory() as session:
                await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
                res = await session.execute(select(OutboxEvent).where(OutboxEvent.id == ev_id))
                ev_db = res.scalars().first()
                assert ev_db.status == OutboxStatus.DELIVERED
        finally:
            await daemon.stop()


# =============================================================================
# ROUND 2 SECURITY & DURABILITY REMEDIATION TEST SUITE
# =============================================================================

@pytest.mark.asyncio
async def test_real_pg_crit01_cross_tenant_url_swap_rejected_403(seed_real_pg_tenant):
    """
    CRIT-01: Verifies that swapped route parameter (/webhooks/whatsapp/{tenant_B})
    with Tenant A's signed payload and provider asset is rejected with 403 Forbidden.
    """
    tenant_a = seed_real_pg_tenant["active_tenant_id"]
    tenant_b = f"t_pg_b_{uuid.uuid4().hex[:8]}"

    # Seed Tenant B in live database
    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (id, name, slug, is_active) VALUES (%s, %s, %s, %s);",
                (tenant_b, "Tenant Bravo", f"slug-{tenant_b}", True)
            )
            conn.commit()

    try:
        # Payload containing Tenant A's asset ('pn_1')
        wamid = f"wamid_swap_{uuid.uuid4().hex[:12]}"
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "entry_swap",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "+212600000000", "phone_number_id": "pn_1"},
                        "contacts": [{"profile": {"name": "Hacker Cross"}, "wa_id": "212699887766"}],
                        "messages": [{
                            "from": "212699887766",
                            "id": wamid,
                            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                            "text": {"body": "Inject into Tenant B"},
                            "type": "text"
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        sig = hmac.new(settings.whatsapp_webhook_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={sig}"
        }

        async with real_pg_session_factory() as session_factory:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # POST to Tenant B's webhook URL
                resp = await client.post(f"/api/v1/channels/webhooks/whatsapp/{tenant_b}", content=body_bytes, headers=headers)
                assert resp.status_code == 403, f"Expected 403 Forbidden for cross-tenant swap, got {resp.status_code}: {resp.text}"
                assert "Cross-tenant injection rejected" in resp.json()["detail"]

            # Verify zero rows in Tenant B
            async with session_factory() as session:
                await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_b})
                raws = (await session.execute(select(InboundRawEvent).where(InboundRawEvent.tenant_id == tenant_b))).scalars().all()
                assert len(raws) == 0, "No raw events should be created in Tenant B"
                convs = (await session.execute(select(Conversation).where(Conversation.tenant_id == tenant_b))).scalars().all()
                assert len(convs) == 0, "No conversations should be created in Tenant B"
    finally:
        with psycopg.connect(_admin_conn_str()) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tenants WHERE id = %s;", (tenant_b,))
                conn.commit()


@pytest.mark.asyncio
async def test_real_pg_crit01_unknown_provider_asset_rejected_404(seed_real_pg_tenant):
    """
    CRIT-01: Verifies that a webhook with an unregistered provider asset ID returns 404 Not Found.
    """
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    wamid = f"wamid_unk_{uuid.uuid4().hex[:12]}"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "entry_unk",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "+212600000000", "phone_number_id": "pn_nonexistent_999"},
                    "contacts": [{"profile": {"name": "Anon"}, "wa_id": "212699887766"}],
                    "messages": [{
                        "from": "212699887766",
                        "id": wamid,
                        "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                        "text": {"body": "Unknown asset text"},
                        "type": "text"
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = hmac.new(settings.whatsapp_webhook_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={sig}"
    }

    async with real_pg_session_factory() as session_factory:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/v1/channels/webhooks/whatsapp/{tenant_id}", content=body_bytes, headers=headers)
            assert resp.status_code == 404, f"Expected 404 for unknown asset, got {resp.status_code}: {resp.text}"
            assert "No integration registered" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_real_pg_crit01_deactivated_integration_rejected_403(seed_real_pg_tenant):
    """
    CRIT-01: Verifies that a webhook targeting a deactivated channel integration returns 403 Forbidden.
    """
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    deact_asset = f"pn_deact_{uuid.uuid4().hex[:6]}"

    with psycopg.connect(PG_SYNC_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenant_channel_integrations (id, tenant_id, channel_type, provider_asset_id, webhook_secret, is_active) VALUES (%s, %s, %s, %s, %s, %s);",
                (f"tci_{uuid.uuid4().hex[:8]}", tenant_id, "WHATSAPP", deact_asset, settings.whatsapp_webhook_secret, False)
            )
            conn.commit()

    wamid = f"wamid_deact_{uuid.uuid4().hex[:12]}"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "entry_deact",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "+212600000000", "phone_number_id": deact_asset},
                    "contacts": [{"profile": {"name": "Anon"}, "wa_id": "212699887766"}],
                    "messages": [{
                        "from": "212699887766",
                        "id": wamid,
                        "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                        "text": {"body": "Deactivated asset text"},
                        "type": "text"
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = hmac.new(settings.whatsapp_webhook_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={sig}"
    }

    async with real_pg_session_factory() as session_factory:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/v1/channels/webhooks/whatsapp/{tenant_id}", content=body_bytes, headers=headers)
            assert resp.status_code == 403, f"Expected 403 for deactivated integration, got {resp.status_code}: {resp.text}"
            assert "deactivated" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_real_pg_crit02_connection_pool_zero_leakage_after_webhook(seed_real_pg_tenant):
    """
    CRIT-02: Verifies that after a webhook sets app.current_tenant_id, connection checkin
    completely resets the GUC parameter so subsequent checkouts have zero tenant context leakage.
    """
    tenant_id = seed_real_pg_tenant["active_tenant_id"]

    # 1. Send legitimate webhook that sets tenant context
    wamid = f"wamid_leaktest_{uuid.uuid4().hex[:12]}"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "entry_leak",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "+212600000000", "phone_number_id": "pn_1"},
                    "contacts": [{"profile": {"name": "Pool Tester"}, "wa_id": "212611998877"}],
                    "messages": [{
                        "from": "212611998877",
                        "id": wamid,
                        "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                        "text": {"body": "Check connection pool reset"},
                        "type": "text"
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = hmac.new(settings.whatsapp_webhook_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={sig}"
    }

    async with real_pg_session_factory() as session_factory:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/v1/channels/webhooks/whatsapp/{tenant_id}", content=body_bytes, headers=headers)
            assert resp.status_code == 200

        # 2. Check out connection directly from engine pool WITHOUT setting tenant context
        async with session_factory() as session:
            # Query setting
            res = await session.execute(text("SELECT current_setting('app.current_tenant_id', true)"))
            val = res.scalar()
            assert val in (None, ""), f"Connection pool leaked tenant context! Expected empty, got: {val!r}"

            # Query contacts under RLS - must return 0 rows
            contacts = (await session.execute(select(Contact))).scalars().all()
            assert len(contacts) == 0, f"RLS leakage! Unauthenticated session read {len(contacts)} contacts from pool connection!"


@pytest.mark.asyncio
async def test_real_pg_high01_stop_cancels_only_marketing_preserves_transactional(seed_real_pg_tenant):
    """
    HIGH-01: Verifies that STOP directive cancels ONLY MARKETING messages.
    TRANSACTIONAL (invoices, order status) and SECURITY (PIN) messages are strictly preserved and delivered.
    """
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    recipient = f"+2126{uuid.uuid4().int % 100000000:08d}"

    async with real_pg_session_factory() as session_factory:
        # 1. Enqueue 3 messages with different classes
        async with session_factory() as session:
            mkt_ev = await OutboxService.enqueue_outbound_event(
                session=session,
                tenant_id=tenant_id,
                channel_type="WHATSAPP",
                recipient_identifier=recipient,
                event_type="PROMOTIONAL_OFFER",
                payload_dict={"offer": "50% off"},
                is_high_priority=False,
                message_class="MARKETING"
            )
            tx_ev = await OutboxService.enqueue_outbound_event(
                session=session,
                tenant_id=tenant_id,
                channel_type="WHATSAPP",
                recipient_identifier=recipient,
                event_type="ORDER_INVOICE",
                payload_dict={"invoice_id": "inv_999", "amount": 2500},
                is_high_priority=False,
                message_class="TRANSACTIONAL"
            )
            sec_ev = await OutboxService.enqueue_outbound_event(
                session=session,
                tenant_id=tenant_id,
                channel_type="WHATSAPP",
                recipient_identifier=recipient,
                event_type="SECURITY_ALERT",
                payload_dict={"alert": "Password changed"},
                is_high_priority=False,
                message_class="SECURITY"
            )
            await session.commit()
            mkt_id, tx_id, sec_id = mkt_ev.id, tx_ev.id, sec_ev.id

        # 2. Inbound STOP directive in French ("ARRET")
        stop_event = NormalizedInboundEvent(
            tenant_id=tenant_id,
            channel_type="WHATSAPP",
            provider_event_id=f"evt_stop_fr_{uuid.uuid4().hex[:8]}",
            sender_identifier=recipient,
            sender_name="Karim Tazi",
            content="ARRET s'il vous plait",
            event_type="MESSAGE",
            attachments=[],
            raw_payload={},
            timestamp=datetime.now(timezone.utc)
        )
        async with session_factory() as session:
            await ConversationService.process_normalized_event(session=session, event=stop_event)
            await session.commit()

        # 3. Assert outbox states: MARKETING is CANCELLED; TRANSACTIONAL and SECURITY are PENDING
        async with session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})

            mkt = (await session.execute(select(OutboxEvent).where(OutboxEvent.id == mkt_id))).scalars().first()
            assert mkt.status == OutboxStatus.CANCELLED, f"MARKETING message should be CANCELLED, got {mkt.status}"

            tx = (await session.execute(select(OutboxEvent).where(OutboxEvent.id == tx_id))).scalars().first()
            assert tx.status == OutboxStatus.PENDING, f"TRANSACTIONAL message must remain PENDING, got {tx.status}"

            sec = (await session.execute(select(OutboxEvent).where(OutboxEvent.id == sec_id))).scalars().first()
            assert sec.status == OutboxStatus.PENDING, f"SECURITY message must remain PENDING, got {sec.status}"

        # 4. Dispatch pending events - TRANSACTIONAL and SECURITY must be DELIVERED!
        dispatched_ids = []
        async def mock_dispatcher(ev: OutboxEvent) -> bool:
            dispatched_ids.append(ev.id)
            return True

        async with session_factory() as session:
            dispatched = await OutboxService.dispatch_pending_events(
                session=session,
                tenant_id=tenant_id,
                dispatcher_callable=mock_dispatcher
            )

        assert mkt_id not in dispatched_ids
        assert tx_id in dispatched_ids
        assert sec_id in dispatched_ids


@pytest.mark.asyncio
async def test_real_pg_med01_outbox_three_phase_claim_commit_before_network_io(seed_real_pg_tenant):
    """
    MED-01: Verifies that Phase A commits claims and releases DB row locks BEFORE
    external provider network calls (dispatcher_callable) execute.
    """
    tenant_id = seed_real_pg_tenant["active_tenant_id"]

    async with real_pg_session_factory() as session_factory:
        async with session_factory() as session:
            ev = await OutboxService.enqueue_outbound_event(
                session=session,
                tenant_id=tenant_id,
                channel_type="EMAIL",
                recipient_identifier="fast_claim@test.com",
                event_type="DISPATCH_MESSAGE",
                payload_dict={"text": "Test 3-phase lease"}
            )
            await session.commit()
            ev_id = ev.id

        phase_b_db_asserted = False

        async def slow_network_call_dispatcher(event: OutboxEvent) -> bool:
            nonlocal phase_b_db_asserted
            # Inspect database from a separate connection during network I/O
            with psycopg.connect(PG_SYNC_CONN) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
                    cur.execute(
                        "SELECT status, claimed_by, claim_token FROM outbox_events WHERE id = %s;",
                        (event.id,)
                    )
                    row = cur.fetchone()
                    assert row is not None
                    status, claimed_by, claim_token = row
                    # Row must already be PROCESSING with claim_token committed in DB!
                    assert status == "PROCESSING", f"Expected PROCESSING in DB during Phase B, got {status}"
                    assert claimed_by is not None
                    assert claim_token is not None
                    phase_b_db_asserted = True
            await asyncio.sleep(0.05)
            return True

        async with session_factory() as session:
            dispatched = await OutboxService.dispatch_pending_events(
                session=session,
                tenant_id=tenant_id,
                dispatcher_callable=slow_network_call_dispatcher,
                worker_id="phase_test_worker"
            )

        assert phase_b_db_asserted, "Phase B DB inspection did not execute!"
        assert any(d.id == ev_id for d in dispatched)

        # In DB, verify finalized DELIVERED status and cleared claims
        async with session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            res = await session.execute(select(OutboxEvent).where(OutboxEvent.id == ev_id))
            ev_final = res.scalars().first()
            assert ev_final.status == OutboxStatus.DELIVERED
            assert ev_final.claim_token is None
            assert ev_final.claimed_by is None


@pytest.mark.asyncio
async def test_real_pg_med01_stale_worker_fencing_token_rejection(seed_real_pg_tenant):
    """
    MED-01: Verifies fencing token protection. If Worker 1 takes too long and Worker 2
    re-claims the expired lease, Worker 1's stale finalize is rejected.
    """
    tenant_id = seed_real_pg_tenant["active_tenant_id"]

    async with real_pg_session_factory() as session_factory:
        # 1. Enqueue outbox event
        async with session_factory() as session:
            ev = await OutboxService.enqueue_outbound_event(
                session=session,
                tenant_id=tenant_id,
                channel_type="EMAIL",
                recipient_identifier="fencing@test.com",
                event_type="NOTIFICATION",
                payload_dict={"text": "Fencing token test"}
            )
            await session.commit()
            ev_id = ev.id

        # 2. Worker 1 claims with short lease (1 second)
        now = datetime.now(timezone.utc)
        worker_1_token = None

        async def worker_1_slow_dispatcher(event: OutboxEvent) -> bool:
            nonlocal worker_1_token
            worker_1_token = event.claim_token
            # Simulate worker 1 hanging while lease expires and worker 2 takes over
            with psycopg.connect(PG_SYNC_CONN) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
                    # Force lease expiration and re-claim by Worker 2
                    cur.execute(
                        "UPDATE outbox_events SET claimed_by = 'worker_2', claim_token = 'token_w2_active' WHERE id = %s;",
                        (event.id,)
                    )
                    conn.commit()
            return True

        # Dispatch via Worker 1
        async with session_factory() as session:
            dispatched = await OutboxService.dispatch_pending_events(
                session=session,
                tenant_id=tenant_id,
                dispatcher_callable=worker_1_slow_dispatcher,
                worker_id="worker_1"
            )

        # Worker 1's finalization matched 0 rows because claim_token was overwritten by Worker 2!
        # Verify Worker 2's token and state was NOT overwritten by Worker 1
        with psycopg.connect(PG_SYNC_CONN) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.current_tenant_id', %s, true);", (tenant_id,))
                cur.execute(
                    "SELECT status, claimed_by, claim_token FROM outbox_events WHERE id = %s;",
                    (ev_id,)
                )
                row = cur.fetchone()
                assert row is not None
                status, claimed_by, claim_token = row
                assert claim_token == "token_w2_active", "Worker 1 stale update overwrote Worker 2's active claim!"
                assert claimed_by == "worker_2"


@pytest.mark.asyncio
async def test_real_pg_med02_domain_service_composable_transaction_rollback(seed_real_pg_tenant):
    """
    MED-02: Verifies that ConversationService methods do not prematurely commit,
    enabling atomic multi-step operations that rollback cleanly on failure.
    """
    tenant_id = seed_real_pg_tenant["active_tenant_id"]
    recipient = f"+2126{uuid.uuid4().int % 100000000:08d}"

    event = NormalizedInboundEvent(
        tenant_id=tenant_id,
        channel_type="WHATSAPP",
        provider_event_id=f"evt_rollback_{uuid.uuid4().hex[:8]}",
        sender_identifier=recipient,
        sender_name="Rollback Tester",
        content="Should be rolled back",
        event_type="MESSAGE",
        attachments=[],
        raw_payload={},
        timestamp=datetime.now(timezone.utc)
    )

    async with real_pg_session_factory() as session_factory:
        async with session_factory() as session:
            # 1. Process event inside transaction
            msg = await ConversationService.process_normalized_event(session=session, event=event)
            assert msg.id is not None
            conv_id = msg.conversation_id

            # 2. Rollback the transaction explicitly (simulating caller error or downstream failure)
            await session.rollback()

        # 3. In a fresh transaction, verify NOTHING was persisted to PostgreSQL
        async with session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            res_conv = await session.execute(select(Conversation).where(Conversation.id == conv_id))
            assert res_conv.scalars().first() is None, "Conversation was committed prematurely! Rollback failed."

            res_msg = await session.execute(select(ConversationMessage).where(ConversationMessage.id == msg.id))
            assert res_msg.scalars().first() is None, "Message was committed prematurely! Rollback failed."

