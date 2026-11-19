"""
API Contract Tests for Agent Ecosystem & Sales Representative Copilot Routes.
Step 09: Complete 18-Role Agent Ecosystem & Sales Representative Copilot
(Controls 40, 63, 65, 66, 67; Invariants 1, 2, 4)
"""
import pytest
import uuid
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import src.backend.models.entities
from src.backend.main import app
from src.backend.models.entities import Base, Tenant, User, Role, UserRole, SessionRevocation
from src.backend.core.security import SecurityService
from src.backend.core.database import get_db_session


@asynccontextmanager
async def get_agent_api_env():
    db_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_agent_api_{db_id}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        t = Tenant(id="tenant-agent-api", name="Agent Test Corp", slug="agent-test-corp")
        session.add(t)

        user = User(
            id="user-agent-api-01",
            tenant_id="tenant-agent-api",
            email="rep@agentcorp.ma",
            hashed_password=SecurityService.hash_password("RepPass123!"),
            full_name="Sales Rep Hassan",
            is_active=True,
            is_verified=True
        )
        session.add(user)

        r_rep = Role(id="role_rep_agent", name="sales_rep", description="Sales Representative", is_privileged=False)
        session.add(r_rep)
        session.add(UserRole(tenant_id="tenant-agent-api", user_id=user.id, role_id=r_rep.id))
        await session.commit()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db

    token, _, _ = SecurityService.create_access_token(
        user_id=user.id,
        tenant_id="tenant-agent-api",
        email="rep@agentcorp.ma",
        roles=["sales_rep", "customer"],
        permissions=["crm:read", "crm:write", "ai:agents", "ai:copilot", "orders:read"]
    )

    import src.backend.core.auth_middleware as mw
    import src.backend.core.database as db_mod
    orig_factory = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = session_factory
    mw.AsyncSessionLocal = session_factory

    headers = {"Authorization": f"Bearer {token}"}

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, headers
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        db_mod.AsyncSessionLocal = orig_factory
        mw.AsyncSessionLocal = orig_factory
        await engine.dispose()


@pytest.mark.asyncio
async def test_api_list_agent_catalog():
    """Validates GET /api/v1/agents returns the full capability catalog."""
    async with get_agent_api_env() as (client, headers):
        resp = await client.get("/api/v1/agents", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 18
        roles = {r["role_id"] for r in data}
        assert "conversation_supervisor" in roles
        assert "sales_copilot" in roles
        assert "qualification_crm" in roles


@pytest.mark.asyncio
async def test_api_get_agent_definition():
    """Validates GET /api/v1/agents/{role_id} returns single role definition."""
    async with get_agent_api_env() as (client, headers):
        resp = await client.get("/api/v1/agents/sales_copilot", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["role_id"] == "sales_copilot"
        assert data["role_group"] == "COPILOT"
        assert "copilot.generate_brief" in data["allowed_tools"]

        # 404 for unknown role
        resp_404 = await client.get("/api/v1/agents/unknown_role", headers=headers)
        assert resp_404.status_code == 404


@pytest.mark.asyncio
async def test_api_execute_conversation_turn():
    """Validates POST /api/v1/agents/turn executes authoritative turn."""
    async with get_agent_api_env() as (client, headers):
        payload = {
            "conversation_id": "conv-api-01",
            "turn_id": "turn-api-01",
            "user_prompt": "Bonjour, pouvez-vous me donner des informations sur vos panneaux solaires ?",
            "channel": "WEBCHAT",
            "expected_turn_version": 0
        }
        resp = await client.post("/api/v1/agents/turn", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert len(data["response_text"]) > 0


@pytest.mark.asyncio
async def test_api_human_takeover_and_release():
    """Validates POST /api/v1/agents/takeover to claim and release conversation ownership."""
    async with get_agent_api_env() as (client, headers):
        conv_id = "conv-takeover-api"
        # Claim takeover
        claim_resp = await client.post(
            "/api/v1/agents/takeover",
            json={"conversation_id": conv_id, "action": "TAKEOVER"},
            headers=headers
        )
        assert claim_resp.status_code == 200
        assert claim_resp.json()["is_human_owned"] is True

        # Subsequent turn is silenced
        turn_resp = await client.post(
            "/api/v1/agents/turn",
            json={
                "conversation_id": conv_id,
                "user_prompt": "Bonjour ?",
                "expected_turn_version": 0
            },
            headers=headers
        )
        assert turn_resp.status_code == 200
        assert turn_resp.json()["status"] == "SILENCED_TAKEOVER"

        # Release takeover
        rel_resp = await client.post(
            "/api/v1/agents/takeover",
            json={"conversation_id": conv_id, "action": "RELEASE"},
            headers=headers
        )
        assert rel_resp.status_code == 200
        assert rel_resp.json()["is_human_owned"] is False


@pytest.mark.asyncio
async def test_api_copilot_brief_and_approval():
    """Validates POST /api/v1/agents/copilot/brief and /approve."""
    async with get_agent_api_env() as (client, headers):
        brief_payload = {
            "conversation_id": "conv-copilot-api-01",
            "customer_id": "cust-copilot-01",
            "transcript_snippet": "Client wants 10 panels and asks for discount"
        }
        resp = await client.post("/api/v1/agents/copilot/brief", json=brief_payload, headers=headers)
        assert resp.status_code == 200
        brief = resp.json()
        assert "brief_id" in brief
        assert "customer_summary" in brief
        assert len(brief["proposed_actions"]) > 0

        # Test approving proposal
        prop = brief["proposed_actions"][0]
        appr_payload = {
            "brief_id": brief["brief_id"],
            "proposal_id": prop["proposal_id"]
        }
        appr_resp = await client.post("/api/v1/agents/copilot/approve", json=appr_payload, headers=headers)
        assert appr_resp.status_code == 200
        assert appr_resp.json()["status"] == "APPROVED_BY_HUMAN_REPRESENTATIVE"
