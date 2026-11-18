"""
Authentication & Session Lifecycle API Endpoints.
Covers: Login, Step-up MFA, Session Refresh, and Immediate JTI Revocation on Logout.
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.config import settings
from src.backend.core.security import SecurityService
from src.backend.core.database import get_db_session, current_tenant_id_ctx
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
    # Query user by email (and optional tenant_id)
    stmt = select(User).where(User.email == req.email)
    if req.tenant_id:
        stmt = stmt.where(User.tenant_id == req.tenant_id)
    
    res = await db.execute(stmt)
    user = res.scalars().first()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid email or password", "correlation_id": correlation_id}
        )

    # Check account lockout
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
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

    # Issue standard full tokens
    access_token, jti, exp = SecurityService.create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        roles=roles,
        permissions=permissions,
        mfa_verified=False
    )
    refresh_token, _, _ = SecurityService.create_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id
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
    access_token, jti, exp = SecurityService.create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        roles=roles,
        permissions=permissions,
        mfa_verified=True
    )
    refresh_token, _, _ = SecurityService.create_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id
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
        user.mfa_secret = secret
        user.mfa_enabled = True
        await db.commit()

    return MFASetupResponse(secret=secret, otpauth_uri=uri)

@router.post("/logout")
async def logout(
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Revokes active token immediately by recording JTI in session_revocations table."""
    revocation = SessionRevocation(
        token_jti=context.jti,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes),
        reason="user_logout"
    )
    db.add(revocation)
    await db.commit()
    return {"status": "SUCCESS", "message": "Session revoked successfully"}
