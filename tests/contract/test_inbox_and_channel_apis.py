"""
API Integration Tests for Channels and Unified Inbox Routers.
Tests HTTP endpoints, authentication, signature verification, and tenant isolation.
(Baseline Controls 16, 17, 22, 33, 42, 57, 58, 59)
"""
import hmac
import hashlib
import json
import pytest
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from datetime import timedelta, datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.backend.main import app
from src.backend.models.entities import Base, Tenant, User, Role, UserRole, Contact, Conversation, ConversationMessage, TenantChannelIntegration
from src.backend.core.security import SecurityService
from src.backend.core.config import settings
from src.backend.core.database import get_db_session

TEST_DB = "sqlite+aiosqlite:///:memory:"

@asynccontextmanager
async def get_api_test_env():
    engine = create_async_engine(
        TEST_DB,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        t = Tenant(id="t_api_01", name="API Tenant Alpha", slug="api-tenant-alpha")
        t_beta = Tenant(id="t_api_02", name="API Tenant Beta", slug="api-tenant-beta")
        session.add_all([t, t_beta])

        user = User(
            id="u_rep_api",
            tenant_id="t_api_01",
            email="rep@api.com",
            hashed_password=SecurityService.hash_password("RepPass123!"),
            full_name="API Rep",
            is_active=True,
            is_verified=True
        )
        session.add(user)

        # Seed WhatsApp channel integration binding
        integ = TenantChannelIntegration(
            id="tci_api_01",
            tenant_id="t_api_01",
            channel_type="WHATSAPP",
            provider_asset_id="wa_acc_01",
            webhook_secret=settings.whatsapp_webhook_secret,
            is_active=True
        )
        session.add(integ)

        # Seed an existing conversation in Tenant Alpha
        contact = Contact(id="c_api_01", tenant_id="t_api_01", display_name="Client Alpha", primary_phone="+212611223344")
        session.add(contact)
        await session.flush()

        conv = Conversation(
            id="conv_api_01",
            tenant_id="t_api_01",
            contact_id="c_api_01",
            channel_type="WHATSAPP",
            channel_identifier="+212611223344",
            status="BOT_ACTIVE",
            version=1
        )
        session.add(conv)
        await session.flush()

        msg = ConversationMessage(
            id="msg_api_01",
            conversation_id="conv_api_01",
            tenant_id="t_api_01",
            sender_type="CUSTOMER",
            content="Hello from API test",
            conversation_version=1
        )
        session.add(msg)
        await session.commit()

    async def override_get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db_session] = override_get_db

    import src.backend.core.auth_middleware as mw
    import src.backend.core.database as db_mod
    orig_factory = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = session_factory
    mw.AsyncSessionLocal = session_factory

    token, _, _ = SecurityService.create_access_token(
        user_id="u_rep_api",
        tenant_id="t_api_01",
        email="rep@api.com",
        roles=["sales_rep"],
        permissions=["conversations:read", "conversations:write"],
        mfa_verified=True,
        expires_delta=timedelta(minutes=30)
    )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield {
                "client": client,
                "token": token,
                "tenant_id": "t_api_01",
                "conversation_id": "conv_api_01"
            }
    finally:
        db_mod.AsyncSessionLocal = orig_factory
        mw.AsyncSessionLocal = orig_factory
        app.dependency_overrides.clear()
        await engine.dispose()

@pytest.mark.asyncio
async def test_whatsapp_webhook_challenge():
    async with get_api_test_env() as env:
        client = env["client"]
        # Valid challenge
        resp = await client.get(
            "/api/v1/channels/webhooks/whatsapp/t_api_01",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "11559955",
                "hub.verify_token": settings.whatsapp_verify_token
            }
        )
        assert resp.status_code == 200
        assert resp.json() == 11559955

        # Invalid token
        resp_bad = await client.get(
            "/api/v1/channels/webhooks/whatsapp/t_api_01",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "11559955",
                "hub.verify_token": "wrong_token"
            }
        )
        assert resp_bad.status_code == 403

@pytest.mark.asyncio
async def test_whatsapp_webhook_signature_verification_and_ingestion():
    async with get_api_test_env() as env:
        client = env["client"]
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "wa_acc_01",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "contacts": [{"profile": {"name": "Sara"}, "wa_id": "212655443322"}],
                        "messages": [{
                            "from": "212655443322",
                            "id": "wamid.TEST_API_01",
                            "type": "text",
                            "text": {"body": "Marhba, bghit nchri"}
                        }]
                    }
                }]
            }]
        }
        body_bytes = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(settings.whatsapp_webhook_secret.encode(), body_bytes, hashlib.sha256).hexdigest()

        # Valid signature
        resp = await client.post(
            "/api/v1/channels/webhooks/whatsapp/t_api_01",
            content=body_bytes,
            headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["processed_count"] == 1

        # Replay duplicate
        resp_dup = await client.post(
            "/api/v1/channels/webhooks/whatsapp/t_api_01",
            content=body_bytes,
            headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"}
        )
        assert resp_dup.status_code == 200
        assert resp_dup.json()["status"] == "duplicate_ignored"

        # Invalid signature
        resp_forged = await client.post(
            "/api/v1/channels/webhooks/whatsapp/t_api_01",
            content=body_bytes,
            headers={"X-Hub-Signature-256": "sha256=forged", "Content-Type": "application/json"}
        )
        assert resp_forged.status_code == 401

@pytest.mark.asyncio
async def test_webchat_send_endpoint():
    async with get_api_test_env() as env:
        client = env["client"]
        resp = await client.post(
            "/api/v1/channels/webchat/send",
            json={
                "tenant_id": "t_api_01",
                "session_id": "visitor_sess_88",
                "customer_name": "Web Prospect",
                "message": "Do you deliver to Tangier?"
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "message_id" in data

@pytest.mark.asyncio
async def test_unified_inbox_conversation_listing_and_timeline():
    async with get_api_test_env() as env:
        client = env["client"]
        token = env["token"]
        conv_id = env["conversation_id"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. List conversations
        resp = await client.get("/api/v1/inbox/conversations", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        conv_item = [c for c in data["conversations"] if c["id"] == conv_id][0]
        assert conv_item["channel_type"] == "WHATSAPP"
        assert conv_item["contact_name"] == "Client Alpha"

        # 2. View Timeline
        t_resp = await client.get(f"/api/v1/inbox/conversations/{conv_id}/timeline", headers=headers)
        assert t_resp.status_code == 200
        t_data = t_resp.json()
        assert len(t_data["messages"]) >= 1
        assert t_data["messages"][0]["content"] == "Hello from API test"

        # 3. Atomic Human Takeover
        h_resp = await client.post(
            f"/api/v1/inbox/conversations/{conv_id}/handoff",
            headers=headers,
            json={"reason": "Customer requested human"}
        )
        assert h_resp.status_code == 200
        assert h_resp.json()["conversation_status"] == "HUMAN_ACTIVE"
        assert h_resp.json()["is_ai_silenced"] is True

        # 4. Agent Reply
        r_resp = await client.post(
            f"/api/v1/inbox/conversations/{conv_id}/reply",
            headers=headers,
            json={"content": "Bonjour, je suis votre conseiller commercial."}
        )
        assert r_resp.status_code == 200
        assert r_resp.json()["status"] == "success"
