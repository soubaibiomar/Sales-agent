"""
Authentication & Session Lifecycle API Endpoints.
Covers: Login, Step-up MFA, Session Refresh, and Immediate JTI Revocation on Logout.
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.config import settings
from src.backend.core.security import SecurityService
from src.backend.core.database import (
    get_db_session, current_tenant_id_ctx, bind_tenant_context, resolve_login_tenants
)
from src.backend.core.policy_service import policy_service
from src.backend.core.auth_middleware import (
    get_security_context, SecurityContext, get_correlation_id
)
from src.backend.schemas.auth import (
    LoginRequest, MFAVerifyRequest, MFASetupResponse, TokenResponse,
    RefreshTokenRequest, UserSummary
)
from src.backend.models.entities import (
    User, Tenant, UserRole, Role, SessionRevocation, AuditEvent
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    correlation_id: str = Depends(get_correlation_id)
):
    """
    Authenticates user credentials.
    If privileged role or MFA enabled, requires step-up MFA verification before issuing full access token.
    """
    # F-09: resolve the tenant through the RLS-compatible pre-auth lookup, then bind it
    # so the remaining queries run under Row-Level Security as the least-privileged role.
    user = None
    candidate_tenants = await resolve_login_tenants(db, req.email, req.tenant_id)
    if len(candidate_tenants) == 1:
        login_tenant_id = candidate_tenants[0]
        await bind_tenant_context(db, login_tenant_id)
        stmt = select(User).where(User.email == req.email, User.tenant_id == login_tenant_id)
        res = await db.execute(stmt)
        user = res.scalars().first()
    # Zero matches, or an email registered in several tenants without tenant_id:
    # same generic failure as a wrong password (no account enumeration).

    if not user or not user.is_active:
        SecurityService.verify_dummy_password(req.password)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid email or password", "correlation_id": correlation_id}
        )

    # Check account lockout
    if user.locked_until:
        locked_time = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
        if locked_time > datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "Account is temporarily locked due to multiple failed login attempts.", "correlation_id": correlation_id}
            )

    # Verify password
    if not SecurityService.verify_password(req.password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= 5:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid email or password", "correlation_id": correlation_id}
        )

    # Reset failed attempts
    user.failed_login_attempts = 0
    await db.commit()
    await bind_tenant_context(db, user.tenant_id)  # GUC is transaction-local

    # Fetch user roles
    role_stmt = (
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id, UserRole.tenant_id == user.tenant_id)
    )
    role_res = await db.execute(role_stmt)
    roles = [r[0] for r in role_res.all()]
    if not roles:
        roles = ["sales_representative"]

    # Load effective permissions
    permissions = await policy_service.get_user_permissions_from_db(db, user.id, user.tenant_id)

    # Check if privileged role or MFA required
    is_privileged = policy_service.has_privileged_role(roles)
    requires_mfa = settings.enforce_mfa_for_managers and (is_privileged or user.mfa_enabled)

    if requires_mfa:
        # Issue temporary verification token valid for 5 minutes
        temp_token, _, _ = SecurityService.create_access_token(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            roles=roles,
            permissions=[],
            mfa_verified=False,
            expires_delta=timedelta(minutes=5)
        )
        return TokenResponse(
            access_token="",
            token_type="Bearer",
            expires_in=300,
            mfa_required=True,
            temp_token=temp_token,
            user=UserSummary(
                id=user.id,
                tenant_id=user.tenant_id,
                email=user.email,
                full_name=user.full_name,
                roles=roles,
                mfa_enabled=user.mfa_enabled,
                is_active=user.is_active
            )
        )

    # Issue standard full tokens (one session family per login, F-21)
    family_id = str(uuid.uuid4())
    access_token, jti, exp = SecurityService.create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        roles=roles,
        permissions=permissions,
        mfa_verified=False,
        family_id=family_id
    )
    refresh_token, _, _ = SecurityService.create_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        family_id=family_id
    )

    # Log successful login audit event
    audit = AuditEvent(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        event_type="AUTH_LOGIN",
        resource_type="USER",
        resource_id=user.id,
        action="LOGIN",
        status="SUCCESS",
        ip_address=request.client.host if request.client else "127.0.0.1"
    )
    db.add(audit)
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        mfa_required=False,
        user=UserSummary(
            id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            full_name=user.full_name,
            roles=roles,
            mfa_enabled=user.mfa_enabled,
            is_active=user.is_active
        )
    )

@router.post("/mfa/verify", response_model=TokenResponse)
async def verify_mfa(
    req: MFAVerifyRequest,
    db: AsyncSession = Depends(get_db_session),
    correlation_id: str = Depends(get_correlation_id)
):
    """Verifies TOTP MFA code from authenticator and issues full access token with mfa_verified=True."""
    try:
        payload = SecurityService.decode_token(req.temp_token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": f"Invalid temporary token: {str(e)}", "correlation_id": correlation_id}
        )

    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    roles = payload.get("roles", [])
    if not user_id or not tenant_id or payload.get("type") == "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid temporary token", "correlation_id": correlation_id}
        )
    # Tenant comes from a signature-verified token, so it can be bound for RLS.
    await bind_tenant_context(db, tenant_id)

    user_stmt = select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalars().first()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "User account inactive", "correlation_id": correlation_id}
        )

    # Verify TOTP code against stored secret or test bypass if configured
    if not user.mfa_secret:
        # If user has no MFA setup yet, setup is required
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "MFA is not configured for this user", "correlation_id": correlation_id}
        )

    valid = SecurityService.verify_totp(user.mfa_secret, req.mfa_code)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid 6-digit MFA code", "correlation_id": correlation_id}
        )

    # Issue verified access token
    permissions = await policy_service.get_user_permissions_from_db(db, user.id, user.tenant_id)
    family_id = str(uuid.uuid4())
    access_token, jti, exp = SecurityService.create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        roles=roles,
        permissions=permissions,
        mfa_verified=True,
        family_id=family_id
    )
    refresh_token, _, _ = SecurityService.create_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        family_id=family_id
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        mfa_required=False,
        user=UserSummary(
            id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            full_name=user.full_name,
            roles=roles,
            mfa_enabled=user.mfa_enabled,
            is_active=user.is_active
        )
    )

@router.post("/mfa/setup", response_model=MFASetupResponse)
async def setup_mfa(
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Generates an RFC 6238 TOTP secret and returns setup details."""
    secret = SecurityService.generate_totp_secret()
    uri = SecurityService.get_totp_uri(secret, context.email)

    stmt = select(User).where(User.id == context.user_id, User.tenant_id == context.tenant_id)
    res = await db.execute(stmt)
    user = res.scalars().first()
    if user:
        user.mfa_secret = SecurityService.encrypt_mfa_secret(secret)
        user.mfa_enabled = True
        await db.commit()

    return MFASetupResponse(secret=secret, otpauth_uri=uri)

@router.post("/refresh", response_model=TokenResponse)
async def refresh_session(
    req: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db_session),
    correlation_id: str = Depends(get_correlation_id)
):
    """
    Rotates a refresh token (F-21). Each refresh token is single-use: it is revoked as
    soon as it is exchanged. Presenting an already-used refresh token is treated as theft:
    the whole session family is revoked, including access tokens already issued from it.
    Roles and permissions are re-read from the database on every refresh.
    """
    def _deny(msg: str):
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                             detail={"error": msg, "correlation_id": correlation_id})
    try:
        payload = SecurityService.decode_token(req.refresh_token)
    except Exception:
        raise _deny("Invalid refresh token")
    user_id, tenant_id = payload.get("sub"), payload.get("tenant_id")
    jti, family_id = payload.get("jti"), payload.get("fam")
    if payload.get("type") != "refresh" or not (user_id and tenant_id and jti and family_id):
        raise _deny("Invalid refresh token")

    await bind_tenant_context(db, tenant_id)
    family_marker = f"family:{family_id}"
    revoked = {r.token_jti for r in (await db.execute(
        select(SessionRevocation).where(SessionRevocation.token_jti.in_([jti, family_marker]))
    )).scalars().all()}
    expires = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    if family_marker in revoked:
        raise _deny("Session has been revoked")
    if jti in revoked:
        # Reuse of a rotated token: assume it was stolen and kill the whole session.
        db.add(SessionRevocation(token_jti=family_marker, tenant_id=tenant_id, user_id=user_id,
                                 expires_at=expires, reason="refresh_token_reuse_detected"))
        db.add(AuditEvent(tenant_id=tenant_id, actor_id=user_id, event_type="AUTH_REFRESH_REUSE",
                          resource_type="SESSION", resource_id=family_id, action="REVOKE_FAMILY", status="BLOCKED"))
        await db.commit()
        raise _deny("Refresh token reuse detected; session revoked")

    user = (await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))).scalars().first()
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalars().first()
    if not user or not user.is_active or not tenant or not tenant.is_active:
        raise _deny("Account or tenant is inactive")

    roles = [r[0] for r in (await db.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id, UserRole.tenant_id == tenant_id)
    )).all()] or ["sales_representative"]
    # Privileged sessions must re-authenticate with MFA rather than silently extend.
    if settings.enforce_mfa_for_managers and (policy_service.has_privileged_role(roles) or user.mfa_enabled):
        raise _deny("Re-authentication with MFA required")
    permissions = await policy_service.get_user_permissions_from_db(db, user.id, tenant_id)

    db.add(SessionRevocation(token_jti=jti, tenant_id=tenant_id, user_id=user_id,
                             expires_at=expires, reason="refresh_rotated"))
    access_token, _, _ = SecurityService.create_access_token(
        user_id=user.id, tenant_id=tenant_id, email=user.email, roles=roles,
        permissions=permissions, mfa_verified=False, family_id=family_id
    )
    new_refresh, _, _ = SecurityService.create_refresh_token(user_id=user.id, tenant_id=tenant_id, family_id=family_id)
    await db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        token_type="Bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        mfa_required=False,
        user=UserSummary(id=user.id, tenant_id=tenant_id, email=user.email, full_name=user.full_name,
                         roles=roles, mfa_enabled=user.mfa_enabled, is_active=user.is_active)
    )


@router.post("/logout")
async def logout(
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Revokes the presented token and its whole session family (incl. refresh tokens)."""
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    db.add(SessionRevocation(
        token_jti=context.jti,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        expires_at=expires_at,
        reason="user_logout"
    ))
    if context.family_id:
        db.add(SessionRevocation(
            token_jti=f"family:{context.family_id}",
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            expires_at=expires_at,
            reason="user_logout"
        ))
    await db.commit()
    return {"status": "SUCCESS", "message": "Session revoked successfully"}
