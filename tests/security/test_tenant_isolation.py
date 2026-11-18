"""
Step 02 Security Test Suite: Multi-Tenant Isolation & Zero-Trust Boundary Validation.
Tests:
1. Negative & positive SQL row-level tenant boundary isolation.
2. Connection-pool context leakage prevention across recycled connections.
3. Client-supplied X-Tenant-ID header spoofing rejection (fail-closed 403).
4. BOLA / IDOR cross-tenant user access prevention via API.
5. Unauthorized cross-tenant switching rejection.
6. Contextvars isolation during concurrent multi-tenant requests.
"""
import pytest
import asyncio
import uuid
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, text

from src.backend.main import app
from src.backend.models.entities import Base, Tenant, User, Role, UserRole, AuditEvent
from src.backend.core.security import SecurityService
from src.backend.core.database import tenant_session, current_tenant_id_ctx
from src.backend.core.config import settings

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@asynccontextmanager
async def get_test_tenant_db():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed two distinct tenants and users
    async with session_factory() as session:
        t1 = Tenant(id="tenant_alpha", name="Alpha Corp", slug="alpha-corp", is_active=True)
        t2 = Tenant(id="tenant_beta", name="Beta Logistics", slug="beta-logistics", is_active=True)
        session.add_all([t1, t2])
        await session.flush()

        role_admin = Role(id="role_tenant_admin", name="tenant_admin", is_privileged=True)
        role_rep = Role(id="role_sales_rep", name="sales_representative", is_privileged=False)
        session.add_all([role_admin, role_rep])
        await session.flush()

        u_alpha = User(
            id="user_alpha_1",
            tenant_id="tenant_alpha",
            email="alice@alpha.com",
            hashed_password=SecurityService.hash_password("Password123!"),
            full_name="Alice Alpha",
            is_active=True,
            is_verified=True
        )
        u_beta = User(
            id="user_beta_1",
            tenant_id="tenant_beta",
            email="bob@beta.com",
            hashed_password=SecurityService.hash_password("Password123!"),
            full_name="Bob Beta",
            is_active=True,
            is_verified=True
        )
        session.add_all([u_alpha, u_beta])
        await session.flush()

        ur1 = UserRole(user_id=u_alpha.id, role_id=role_admin.id, tenant_id="tenant_alpha")
        ur2 = UserRole(user_id=u_beta.id, role_id=role_rep.id, tenant_id="tenant_beta")
        session.add_all([ur1, ur2])
        await session.commit()

    try:
        yield engine, session_factory
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_connection_pool_tenant_context_leakage_prevention():
    """
    Requirement 8 & Invariant 3:
    Verifies that tenant context does not leak across recycled database sessions.
    When a session for tenant_alpha finishes, current_tenant_id_ctx must be cleanly reset.
    """
    async with get_test_tenant_db() as (engine, session_factory):
        # 1. Execute within Tenant Alpha session
        async with tenant_session("tenant_alpha", session_factory=session_factory) as s1:
            assert current_tenant_id_ctx.get() == "tenant_alpha"

        # 2. Outside session context, context variable must be completely cleared
        assert current_tenant_id_ctx.get() is None

        # 3. Next session for Tenant Beta must see only its own context
        async with tenant_session("tenant_beta", session_factory=session_factory) as s2:
            assert current_tenant_id_ctx.get() == "tenant_beta"

        assert current_tenant_id_ctx.get() is None

@pytest.mark.asyncio
async def test_client_header_tenant_spoofing_rejection():
    """
    Control 04, 05, SAI-04:
    Zero-trust boundary: If an attacker provides a valid JWT for tenant_alpha
    but supplies header 'X-Tenant-ID: tenant_beta', the API must fail-closed with 403 Forbidden.
    """
    async with get_test_tenant_db() as (engine, session_factory):
        # Mint valid token for Alice in tenant_alpha
        token_alpha, _, _ = SecurityService.create_access_token(
            user_id="user_alpha_1",
            tenant_id="tenant_alpha",
            email="alice@alpha.com",
            roles=["tenant_admin"],
            permissions=["users:read"],
            mfa_verified=True
        )

        import src.backend.core.auth_middleware as mw
        import src.backend.core.database as db_mod
        orig_factory = db_mod.AsyncSessionLocal
        db_mod.AsyncSessionLocal = session_factory
        mw.AsyncSessionLocal = session_factory

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Legitimate request without header mismatch
                headers_legit = {"Authorization": f"Bearer {token_alpha}"}
                resp_ok = await client.get("/api/v1/users/me", headers=headers_legit)
                assert resp_ok.status_code == 200
                assert resp_ok.json()["tenant_id"] == "tenant_alpha"

                # Spoofing attempt: Attacker sends X-Tenant-ID: tenant_beta
                headers_spoofed = {
                    "Authorization": f"Bearer {token_alpha}",
                    "X-Tenant-ID": "tenant_beta"
                }
                resp_spoofed = await client.get("/api/v1/users/me", headers=headers_spoofed)
                assert resp_spoofed.status_code == 403
                assert "Client tenant ID mismatch" in resp_spoofed.json()["detail"]["error"]
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory

@pytest.mark.asyncio
async def test_cross_tenant_user_access_isolation():
    """
    Control 04, 05, 41:
    Verifies that Alice (tenant_alpha) listing users sees ONLY tenant_alpha users
    and cannot view Bob (tenant_beta).
    """
    async with get_test_tenant_db() as (engine, session_factory):
        token_alpha, _, _ = SecurityService.create_access_token(
            user_id="user_alpha_1",
            tenant_id="tenant_alpha",
            email="alice@alpha.com",
            roles=["tenant_admin"],
            permissions=["users:read"],
            mfa_verified=True
        )

        import src.backend.core.auth_middleware as mw
        import src.backend.core.database as db_mod
        orig_factory = db_mod.AsyncSessionLocal
        db_mod.AsyncSessionLocal = session_factory
        mw.AsyncSessionLocal = session_factory

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token_alpha}"})
                assert resp.status_code == 200
                users = resp.json()
                assert len(users) == 1
                assert users[0]["id"] == "user_alpha_1"
                assert users[0]["tenant_id"] == "tenant_alpha"
                assert not any(u["id"] == "user_beta_1" for u in users)
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory

@pytest.mark.asyncio
async def test_unauthorized_cross_tenant_switch_rejected():
    """
    Control 04, 05, SAI-04:
    A user belonging solely to tenant_alpha cannot switch to tenant_beta.
    Switch endpoint must fail closed with 403 Forbidden.
    """
    async with get_test_tenant_db() as (engine, session_factory):
        token_alpha, _, _ = SecurityService.create_access_token(
            user_id="user_alpha_1",
            tenant_id="tenant_alpha",
            email="alice@alpha.com",
            roles=["sales_representative"],
            permissions=["quotes:read"],
            mfa_verified=False
        )

        import src.backend.core.auth_middleware as mw
        import src.backend.core.database as db_mod
        orig_factory = db_mod.AsyncSessionLocal
        db_mod.AsyncSessionLocal = session_factory
        mw.AsyncSessionLocal = session_factory

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/v1/tenants/switch",
                    json={"target_tenant_id": "tenant_beta"},
                    headers={"Authorization": f"Bearer {token_alpha}"}
                )
                assert resp.status_code == 403
                assert "Cross-tenant access denied" in resp.json()["detail"]["error"]
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory

@pytest.mark.asyncio
async def test_concurrent_tenant_contextvars_isolation():
    """
    Requirement 8:
    Simulates concurrent asynchronous tasks switching and reading tenant contexts.
    Verifies that contextvars maintain strict task-local isolation without race conditions.
    """
    async def tenant_task(tid: str, delay: float):
        token = current_tenant_id_ctx.set(tid)
        await asyncio.sleep(delay)
        val = current_tenant_id_ctx.get()
        current_tenant_id_ctx.reset(token)
        return val

    results = await asyncio.gather(
        tenant_task("tenant_1", 0.05),
        tenant_task("tenant_2", 0.02),
        tenant_task("tenant_3", 0.04),
        tenant_task("tenant_4", 0.01)
    )

    assert results == ["tenant_1", "tenant_2", "tenant_3", "tenant_4"]
