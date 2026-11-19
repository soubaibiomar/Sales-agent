"""
API Contract Tests for AI Governance, Model Gateway, RAG and Protected Tools.
Step 08: Model Gateway, RAG, Router, Protected Tools and Output Verification
(Controls 39-40, 49, 63, 65-67; SAI-06 to SAI-12)
"""
import pytest
import uuid
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.backend.main import app
from src.backend.models.entities import Base, Tenant, User, Role, UserRole
from src.backend.core.security import SecurityService
from src.backend.core.database import get_db_session


@asynccontextmanager
async def get_ai_gov_api_env():
    db_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_ai_gov_{db_id}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        t = Tenant(id="tenant-acme-corp", name="Acme Corp", slug="acme-corp")
        session.add(t)

        user = User(
            id="user-ai-gov-01",
            tenant_id="tenant-acme-corp",
            email="admin@acme.corp",
            hashed_password=SecurityService.hash_password("AdminPass123!"),
            full_name="AI Admin",
            is_active=True,
            is_verified=True
        )
        cust_user = User(
            id="cust-01",
            tenant_id="tenant-acme-corp",
            email="customer@client.ma",
            hashed_password=SecurityService.hash_password("CustPass123!"),
            full_name="Customer User",
            is_active=True,
            is_verified=True
        )
        session.add_all([user, cust_user])

        r_admin = Role(id="role_admin_ai", name="tenant_admin", description="Tenant Admin", is_privileged=True)
        r_cust = Role(id="role_cust_ai", name="customer", description="Customer", is_privileged=False)
        session.add_all([r_admin, r_cust])
        session.add(UserRole(tenant_id="tenant-acme-corp", user_id=user.id, role_id=r_admin.id))
        session.add(UserRole(tenant_id="tenant-acme-corp", user_id=cust_user.id, role_id=r_cust.id))
        await session.commit()

    admin_token, _, _ = SecurityService.create_access_token(
        user_id="user-ai-gov-01",
        tenant_id="tenant-acme-corp",
        email="admin@acme.corp",
        roles=["tenant_admin", "sales_manager"],
        permissions=[
            "ai:manage",
            "ai:rag",
            "ai:tools",
            "crm:read",
            "catalog:read",
            "pricing:calculate"
        ],
        mfa_verified=True
    )

    cust_token, _, _ = SecurityService.create_access_token(
        user_id="cust-01",
        tenant_id="tenant-acme-corp",
        email="customer@client.ma",
        roles=["customer"],
        permissions=["ai:tools"],
        mfa_verified=False
    )

    async def override_db():
        async with session_factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_db

    import src.backend.core.auth_middleware as mw
    import src.backend.core.database as db_mod
    orig_factory = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = session_factory
    mw.AsyncSessionLocal = session_factory

    try:
        yield {
            "admin_headers": {"Authorization": f"Bearer {admin_token}"},
            "cust_headers": {"Authorization": f"Bearer {cust_token}"}
        }
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        db_mod.AsyncSessionLocal = orig_factory
        mw.AsyncSessionLocal = orig_factory
        await engine.dispose()


@pytest.mark.asyncio
async def test_ai_health_endpoint():
    """GET /api/v1/ai/health returns health telemetry and model statuses."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/ai/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "HEALTHY"
        assert "primary_llm" in data
        assert "gpu_vram_headroom_mb" in data


@pytest.mark.asyncio
async def test_ai_route_endpoint():
    """POST /api/v1/ai/route evaluates language, intent, and execution class."""
    async with get_ai_gov_api_env() as env:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/v1/ai/route",
                json={"text": "salam khoya, bghit nchouf l-prix dyal l-kit solaire 3afak"},
                headers=env["admin_headers"]
            )
            assert res.status_code == 200
            data = res.json()
            assert data["language"] in ["ary-Latn", "fr-FR", "ary-Arab"]
            assert data["execution_class"] in ["DIRECT_SAFE_READ", "BOUNDED_REASONING_TURN"]
            assert data["is_adversarial"] is False


@pytest.mark.asyncio
async def test_ai_tool_execution_endpoint_authorized():
    """POST /api/v1/ai/tools/execute succeeds for authorized tool in role allowlist."""
    async with get_ai_gov_api_env() as env:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/v1/ai/tools/execute",
                json={
                    "tool_name": "catalog.search",
                    "params": {"query": "panneau"}
                },
                headers=env["admin_headers"]
            )
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "SUCCESS"
            assert "products" in data["result"]


@pytest.mark.asyncio
async def test_ai_tool_execution_endpoint_unauthorized():
    """POST /api/v1/ai/tools/execute rejects tool when caller role lacks permission."""
    async with get_ai_gov_api_env() as env:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Customer tries to execute unlisted tool
            res = await client.post(
                "/api/v1/ai/tools/execute",
                json={
                    "tool_name": "support.create_ticket",
                    "params": {"idempotency_key": "IDEM-TEST-99", "subject": "Sub", "description": "Desc"}
                },
                headers=env["cust_headers"]
            )
            assert res.status_code == 403
            assert "not authorized to invoke tool" in res.json()["detail"]


@pytest.mark.asyncio
async def test_ai_guard_verify_endpoint():
    """POST /api/v1/ai/guard/verify performs claim verification against ground truth."""
    async with get_ai_gov_api_env() as env:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Grounded claim
            res_ok = await client.post(
                "/api/v1/ai/guard/verify",
                json={
                    "text": "Le prix vérifié est de 1250 MAD.",
                    "evidence": {
                        "tenant_id": "tenant-acme-corp",
                        "verified_prices": {"SKU-01": 1250.0},
                        "verified_currency": "MAD"
                    }
                },
                headers=env["admin_headers"]
            )
            assert res_ok.status_code == 200
            data_ok = res_ok.json()
            assert data_ok["is_safe"] is True

            # Ungrounded claim
            res_bad = await client.post(
                "/api/v1/ai/guard/verify",
                json={
                    "text": "Le prix est de 450 MAD avec 40% de remise !",
                    "evidence": {
                        "tenant_id": "tenant-acme-corp",
                        "verified_prices": {"SKU-01": 1250.0},
                        "approved_discounts_percent": [10.0]
                    }
                },
                headers=env["admin_headers"]
            )
            assert res_bad.status_code == 200
            data_bad = res_bad.json()
            assert data_bad["is_safe"] is False
            assert len(data_bad["violations"]) >= 1


@pytest.mark.asyncio
async def test_ai_evaluations_run_endpoint():
    """GET /api/v1/ai/evaluations/run executes the offline evaluation suite."""
    async with get_ai_gov_api_env() as env:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/v1/ai/evaluations/run", headers=env["admin_headers"])
            assert res.status_code == 200
            data = res.json()
            assert data["total_cases"] >= 10
            assert data["accuracy_percent"] == 100.0
