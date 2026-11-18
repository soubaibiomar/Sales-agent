"""
Step 02 Security Test Suite: Authentication, Session Lifecycle, RBAC, and Privileged MFA.
Controls: 01-15, 24-26, 41, 44, 48-49, 54-56, 60-63, SAI-02, SAI-04.
"""
import pytest
import time
from datetime import timedelta, datetime, timezone
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from src.backend.main import app
from src.backend.models.entities import Base, Tenant, User, Role, UserRole, SessionRevocation
from src.backend.core.security import SecurityService
from src.backend.core.config import settings

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@asynccontextmanager
async def get_test_auth_db():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        t = Tenant(id="tenant_active", name="Active Tenant", slug="active-tenant", is_active=True)
        t_disabled = Tenant(id="tenant_disabled", name="Disabled Tenant", slug="disabled-tenant", is_active=False)
        session.add_all([t, t_disabled])
        await session.flush()

        role_admin = Role(id="r_admin", name="tenant_admin", is_privileged=True)
        role_rep = Role(id="r_rep", name="sales_representative", is_privileged=False)
        session.add_all([role_admin, role_rep])
        await session.flush()

        # Users
        u_active = User(
            id="u_active",
            tenant_id="tenant_active",
            email="manager@active.com",
            hashed_password=SecurityService.hash_password("ManagerPass123!"),
            full_name="Active Manager",
            is_active=True,
            is_verified=True,
            mfa_enabled=True,
            mfa_secret="JBSWY3DPEHPK3PXP" # RFC 6238 test secret
        )
        u_rep = User(
            id="u_rep",
            tenant_id="tenant_active",
            email="rep@active.com",
            hashed_password=SecurityService.hash_password("RepPass123!"),
            full_name="Sales Rep",
            is_active=True,
            is_verified=True,
            mfa_enabled=False
        )
        u_disabled = User(
            id="u_disabled",
            tenant_id="tenant_active",
            email="disabled@active.com",
            hashed_password=SecurityService.hash_password("DisabledPass123!"),
            full_name="Disabled User",
            is_active=False,
            is_verified=True
        )
        u_in_disabled_tenant = User(
            id="u_in_disabled_tenant",
            tenant_id="tenant_disabled",
            email="orphan@disabled.com",
            hashed_password=SecurityService.hash_password("OrphanPass123!"),
            full_name="Orphan User",
            is_active=True,
            is_verified=True
        )
        session.add_all([u_active, u_rep, u_disabled, u_in_disabled_tenant])
        await session.flush()

        ur1 = UserRole(user_id=u_active.id, role_id=role_admin.id, tenant_id="tenant_active")
        ur2 = UserRole(user_id=u_rep.id, role_id=role_rep.id, tenant_id="tenant_active")
        session.add_all([ur1, ur2])
        await session.commit()

    try:
        yield engine, session_factory
    finally:
        await engine.dispose()

def test_password_hashing_pbkdf2():
    """Validates PBKDF2-HMAC-SHA256 password hashing and constant-time verification."""
    password = "SuperSecretPassword123!"
    hashed = SecurityService.hash_password(password)
    
    assert hashed.startswith("pbkdf2_sha256$600000$")
    assert SecurityService.verify_password(password, hashed) is True
    assert SecurityService.verify_password("WrongPassword!", hashed) is False
    assert SecurityService.verify_password("", hashed) is False

def test_totp_rfc6238_generation_and_drift_verification():
    """Validates RFC 6238 TOTP code generation, verification, and window tolerance."""
    secret = SecurityService.generate_totp_secret()
    assert len(secret) >= 26

    # Test code generation at current time
    code = SecurityService.generate_totp_code(secret)
    assert len(code) == 6
    assert code.isdigit()
    assert SecurityService.verify_totp(secret, code) is True

    # Test invalid code
    assert SecurityService.verify_totp(secret, "000000" if code != "000000" else "111111") is False

    # Test time drift (+25 seconds is within standard 1 window drift)
    future_code = SecurityService.generate_totp_code(secret, timestamp=time.time() + 25)
    assert SecurityService.verify_totp(secret, future_code, allowed_drift_windows=1) is True

    # Drift beyond 2 windows (e.g. +90 seconds) should fail
    far_future_code = SecurityService.generate_totp_code(secret, timestamp=time.time() + 95)
    assert SecurityService.verify_totp(secret, far_future_code, allowed_drift_windows=1) is False

@pytest.mark.asyncio
async def test_auth_missing_or_malformed_header():
    """Missing or non-bearer authorization header fails with 401."""
    async with get_test_auth_db() as (engine, session_factory):
        import src.backend.core.auth_middleware as mw
        import src.backend.core.database as db_mod
        orig_factory = db_mod.AsyncSessionLocal
        db_mod.AsyncSessionLocal = session_factory
        mw.AsyncSessionLocal = session_factory

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # No header
                r1 = await client.get("/api/v1/users/me")
                assert r1.status_code == 401

                # Malformed header
                r2 = await client.get("/api/v1/users/me", headers={"Authorization": "Basic 12345"})
                assert r2.status_code == 401
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory

@pytest.mark.asyncio
async def test_auth_expired_token():
    """Expired JWT token fails with 401."""
    async with get_test_auth_db() as (engine, session_factory):
        expired_token, _, _ = SecurityService.create_access_token(
            user_id="u_active",
            tenant_id="tenant_active",
            email="manager@active.com",
            roles=["tenant_admin"],
            permissions=["users:read"],
            expires_delta=timedelta(seconds=-10) # Expired in past
        )

        import src.backend.core.auth_middleware as mw
        import src.backend.core.database as db_mod
        orig_factory = db_mod.AsyncSessionLocal
        db_mod.AsyncSessionLocal = session_factory
        mw.AsyncSessionLocal = session_factory

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {expired_token}"})
                assert resp.status_code == 401
                assert "expired" in resp.json()["detail"]["error"].lower()
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory

@pytest.mark.asyncio
async def test_immediate_session_revocation_on_logout():
    """
    Control 08, 09:
    Logging out records the token's JTI in session_revocations table.
    Subsequent API calls with the same token must immediately fail with 401.
    """
    async with get_test_auth_db() as (engine, session_factory):
        token, jti, _ = SecurityService.create_access_token(
            user_id="u_active",
            tenant_id="tenant_active",
            email="manager@active.com",
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
                headers = {"Authorization": f"Bearer {token}"}
                
                # 1. Valid call before logout
                r_before = await client.get("/api/v1/users/me", headers=headers)
                assert r_before.status_code == 200

                # 2. Call logout endpoint
                r_logout = await client.post("/api/v1/auth/logout", headers=headers)
                assert r_logout.status_code == 200
                assert r_logout.json()["status"] == "SUCCESS"

                # 3. Subsequent call with same token must fail with 401
                r_after = await client.get("/api/v1/users/me", headers=headers)
                assert r_after.status_code == 401
                assert "revoked" in r_after.json()["detail"]["error"].lower()
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory

@pytest.mark.asyncio
async def test_disabled_user_and_inactive_tenant_denied():
    """Disabled users and users belonging to inactive tenants are rejected with 403."""
    async with get_test_auth_db() as (engine, session_factory):
        token_disabled_user, _, _ = SecurityService.create_access_token(
            user_id="u_disabled",
            tenant_id="tenant_active",
            email="disabled@active.com",
            roles=["sales_representative"],
            permissions=[]
        )
        token_disabled_tenant, _, _ = SecurityService.create_access_token(
            user_id="u_in_disabled_tenant",
            tenant_id="tenant_disabled",
            email="orphan@disabled.com",
            roles=["sales_representative"],
            permissions=[]
        )

        import src.backend.core.auth_middleware as mw
        import src.backend.core.database as db_mod
        orig_factory = db_mod.AsyncSessionLocal
        db_mod.AsyncSessionLocal = session_factory
        mw.AsyncSessionLocal = session_factory

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # Disabled user
                r1 = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token_disabled_user}"})
                assert r1.status_code == 403
                assert "disabled" in r1.json()["detail"]["error"].lower()

                # Disabled tenant
                r2 = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token_disabled_tenant}"})
                assert r2.status_code == 403
                assert "inactive" in r2.json()["detail"]["error"].lower()
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory

@pytest.mark.asyncio
async def test_privileged_role_creation_requires_mfa():
    """
    Control 44, SAI-02:
    Creating a user with privileged roles (e.g. tenant_admin, sales_manager)
    requires the caller to be MFA-verified (mfa_verified=True).
    """
    async with get_test_auth_db() as (engine, session_factory):
        # Token WITHOUT MFA
        token_no_mfa, _, _ = SecurityService.create_access_token(
            user_id="u_active",
            tenant_id="tenant_active",
            email="manager@active.com",
            roles=["tenant_admin"],
            permissions=["users:write"],
            mfa_verified=False
        )
        # Token WITH MFA
        token_with_mfa, _, _ = SecurityService.create_access_token(
            user_id="u_active",
            tenant_id="tenant_active",
            email="manager@active.com",
            roles=["tenant_admin"],
            permissions=["users:write"],
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
                user_payload = {
                    "email": "newadmin@active.com",
                    "password": "SecurePassword123!",
                    "full_name": "New Admin User",
                    "roles": ["tenant_admin"]
                }

                # 1. Attempt with unverified MFA -> 403
                r_fail = await client.post(
                    "/api/v1/users",
                    json=user_payload,
                    headers={"Authorization": f"Bearer {token_no_mfa}"}
                )
                assert r_fail.status_code == 403
                assert "MFA verification required" in r_fail.json()["detail"]["error"]

                # 2. Attempt with verified MFA -> 200 OK
                r_ok = await client.post(
                    "/api/v1/users",
                    json=user_payload,
                    headers={"Authorization": f"Bearer {token_with_mfa}"}
                )
                assert r_ok.status_code == 200
                assert r_ok.json()["email"] == "newadmin@active.com"
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory

@pytest.mark.asyncio
async def test_rbac_least_privilege_enforcement():
    """Sales representative cannot execute privileged admin actions (e.g. creating users)."""
    async with get_test_auth_db() as (engine, session_factory):
        token_rep, _, _ = SecurityService.create_access_token(
            user_id="u_rep",
            tenant_id="tenant_active",
            email="rep@active.com",
            roles=["sales_representative"],
            permissions=["quotes:read", "quotes:create"],
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
                    "/api/v1/users",
                    json={"email": "hacked@active.com", "password": "Password123!", "full_name": "Hacked", "roles": ["sales_representative"]},
                    headers={"Authorization": f"Bearer {token_rep}"}
                )
                assert resp.status_code == 403
                assert "Missing required permission" in resp.json()["detail"]["error"]
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory

def test_mfa_secret_encryption_at_rest_and_rotation():
    """
    Finding IAM-02 Remediation:
    Verifies that TOTP secrets are encrypted at rest using AES-256-GCM with per-record nonces.
    Verifies transparent decryption in verify_totp and seamless key rotation support.
    """
    plain_secret = "JBSWY3DPEHPK3PXP"
    master_key_1 = "first_master_key_minimum_32_chars_long!"
    master_key_2 = "second_rotated_master_key_32_chars_len!"

    # 1. Encrypt secret
    encrypted = SecurityService.encrypt_mfa_secret(plain_secret, key=master_key_1)
    assert encrypted.startswith("v1:")
    parts = encrypted.split(":")
    assert len(parts) == 3
    nonce_hex, ct_hex = parts[1], parts[2]
    assert len(nonce_hex) == 24 # 12 bytes = 24 hex characters
    assert plain_secret not in encrypted # Never plaintext

    # 2. Decrypt secret
    decrypted = SecurityService.decrypt_mfa_secret(encrypted, key=master_key_1)
    assert decrypted == plain_secret

    # 3. Transparent TOTP verification from encrypted secret
    code = SecurityService.generate_totp_code(plain_secret)
    assert SecurityService.verify_totp(encrypted, code, key=master_key_1) is True

    # 3b. Verification with system default master key
    default_enc = SecurityService.encrypt_mfa_secret(plain_secret)
    assert SecurityService.verify_totp(default_enc, code) is True

    # 4. Key rotation test: Decrypt with key 1, re-encrypt with key 2
    rotated_enc = SecurityService.encrypt_mfa_secret(
        SecurityService.decrypt_mfa_secret(encrypted, key=master_key_1),
        key=master_key_2
    )
    assert rotated_enc != encrypted
    assert SecurityService.decrypt_mfa_secret(rotated_enc, key=master_key_2) == plain_secret

@pytest.mark.asyncio
async def test_account_enumeration_timing_defense():
    """
    Finding IAM-01 Remediation:
    Verifies that logging in with a non-existent email executes constant-time dummy verification,
    eliminating timing side-channels that leak account existence.
    """
    from unittest.mock import patch

    async with get_test_auth_db() as (engine, session_factory):
        import src.backend.core.auth_middleware as mw
        import src.backend.core.database as db_mod
        orig_factory = db_mod.AsyncSessionLocal
        db_mod.AsyncSessionLocal = session_factory
        mw.AsyncSessionLocal = session_factory

        try:
            with patch.object(SecurityService, "verify_dummy_password", wraps=SecurityService.verify_dummy_password) as mock_dummy:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/api/v1/auth/login",
                        json={"email": "nonexistent_ghost_user@active.com", "password": "AnyPassword123!"}
                    )
                    assert resp.status_code == 401
                    assert resp.json()["detail"]["error"] == "Invalid email or password"
                    # Dummy PBKDF2 verification was executed
                    mock_dummy.assert_called_once_with("AnyPassword123!")
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory

@pytest.mark.asyncio
async def test_account_lockout_after_five_failed_attempts():
    """
    Finding IAM-01 & Baseline Lockout:
    Verifies that 5 consecutive failed login attempts lock the user account for 15 minutes,
    rejecting subsequent attempts with HTTP 403 Forbidden.
    """
    async with get_test_auth_db() as (engine, session_factory):
        import src.backend.core.auth_middleware as mw
        import src.backend.core.database as db_mod
        orig_factory = db_mod.AsyncSessionLocal
        db_mod.AsyncSessionLocal = session_factory
        mw.AsyncSessionLocal = session_factory

        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                # 4 failed attempts -> 401 Unauthorized
                for i in range(4):
                    resp = await client.post(
                        "/api/v1/auth/login",
                        json={"email": "rep@active.com", "password": f"WrongPass{i}!"}
                    )
                    assert resp.status_code == 401

                # 5th failed attempt -> locks account, returns 401
                resp5 = await client.post(
                    "/api/v1/auth/login",
                    json={"email": "rep@active.com", "password": "WrongPass5!"}
                )
                assert resp5.status_code == 401

                # 6th attempt -> 403 Forbidden (Account locked)
                resp6 = await client.post(
                    "/api/v1/auth/login",
                    json={"email": "rep@active.com", "password": "RepPass123!"} # Even with correct password
                )
                assert resp6.status_code == 403
                assert "Account is temporarily locked" in resp6.json()["detail"]["error"]
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory

@pytest.mark.asyncio
async def test_privileged_actions_require_step_up_mfa():
    """
    Finding IAM-03 Remediation:
    Verifies that privileged operations (tenant creation, disabling administrative users)
    strictly require step-up MFA (mfa_verified=True).
    """
    async with get_test_auth_db() as (engine, session_factory):
        token_no_mfa, _, _ = SecurityService.create_access_token(
            user_id="u_active",
            tenant_id="tenant_active",
            email="manager@active.com",
            roles=["tenant_admin"],
            permissions=["*", "users:write"],
            mfa_verified=False
        )
        token_mfa, _, _ = SecurityService.create_access_token(
            user_id="u_active",
            tenant_id="tenant_active",
            email="manager@active.com",
            roles=["tenant_admin"],
            permissions=["*", "users:write"],
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
                # 1. POST /api/v1/tenants without MFA -> 403
                r_tenant_fail = await client.post(
                    "/api/v1/tenants",
                    json={"name": "New Tenant", "slug": "new-tenant"},
                    headers={"Authorization": f"Bearer {token_no_mfa}"}
                )
                assert r_tenant_fail.status_code == 403
                assert "Step-up MFA verification required" in r_tenant_fail.json()["detail"]["error"]

                # 2. POST /api/v1/tenants with MFA -> 200
                r_tenant_ok = await client.post(
                    "/api/v1/tenants",
                    json={"name": "New Tenant", "slug": "new-tenant"},
                    headers={"Authorization": f"Bearer {token_mfa}"}
                )
                assert r_tenant_ok.status_code == 200
                assert r_tenant_ok.json()["slug"] == "new-tenant"

                # 3. PUT /api/v1/users/{id}/status without MFA -> 403
                r_user_fail = await client.put(
                    "/api/v1/users/u_rep/status",
                    json={"is_active": False},
                    headers={"Authorization": f"Bearer {token_no_mfa}"}
                )
                assert r_user_fail.status_code == 403
                assert "Step-up MFA verification required" in r_user_fail.json()["detail"]["error"]

                # 4. PUT /api/v1/users/{id}/status with MFA -> 200
                r_user_ok = await client.put(
                    "/api/v1/users/u_rep/status",
                    json={"is_active": False},
                    headers={"Authorization": f"Bearer {token_mfa}"}
                )
                assert r_user_ok.status_code == 200
                assert r_user_ok.json()["is_active"] is False
        finally:
            db_mod.AsyncSessionLocal = orig_factory
            mw.AsyncSessionLocal = orig_factory
