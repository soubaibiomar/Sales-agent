"""
Authentication Middleware, Fast Security Dependencies, and Tenant Boundary Guards.
Enforces:
1. Cryptographic token validation with PyJWT.
2. JTI session revocation checks against database.
3. Active account & active tenant status verification.
4. Mandatory MFA enforcement for privileged roles.
5. Strict zero-trust header rejection for client-supplied X-Tenant-ID spoofing.
"""
import uuid
from typing import Optional, List, Callable
from dataclasses import dataclass
from fastapi import Request, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
import jwt

from src.backend.core.config import settings
from src.backend.core.security import SecurityService
from src.backend.core.database import AsyncSessionLocal, current_tenant_id_ctx
from src.backend.core.policy_service import policy_service
from src.backend.models.entities import SessionRevocation, User, Tenant

security_bearer = HTTPBearer(auto_error=False)

@dataclass
class SecurityContext:
    user_id: str
    tenant_id: str
    email: str
    roles: List[str]
    permissions: List[str]
    mfa_verified: bool
    jti: str
    correlation_id: str
    family_id: Optional[str] = None

async def get_correlation_id(request: Request) -> str:
    """Extracts or mints a correlation ID for end-to-end request tracing."""
    cid = request.headers.get("X-Correlation-ID")
    if not cid:
        cid = str(uuid.uuid4())
    return cid

async def get_security_context(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    correlation_id: str = Depends(get_correlation_id)
) -> SecurityContext:
    """
    Main authentication dependency for protected endpoints.
    Fail-closed: All errors return explicit 401 Unauthorized or 403 Forbidden.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Missing or malformed Authorization Bearer header", "correlation_id": correlation_id},
            headers={"WWW-Authenticate": "Bearer"}
        )

    raw_token = credentials.credentials
    try:
        payload = SecurityService.decode_token(raw_token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Token has expired", "correlation_id": correlation_id},
            headers={"WWW-Authenticate": "Bearer"}
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid token audience", "correlation_id": correlation_id},
            headers={"WWW-Authenticate": "Bearer"}
        )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": f"Invalid token: {str(e)}", "correlation_id": correlation_id},
            headers={"WWW-Authenticate": "Bearer"}
        )

    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    jti = payload.get("jti")
    roles = payload.get("roles", [])
    permissions = payload.get("permissions", [])
    mfa_verified = payload.get("mfa_verified", False)

    # F-21: refresh tokens (7-day lifetime) must never authenticate API calls.
    if payload.get("type") == "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Refresh tokens cannot be used as access tokens", "correlation_id": correlation_id},
            headers={"WWW-Authenticate": "Bearer"}
        )

    if not user_id or not tenant_id or not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Incomplete token claims", "correlation_id": correlation_id}
        )

    # ZERO-TRUST INVARIANT: Client-supplied X-Tenant-ID spoofing rejection
    client_tenant_header = request.headers.get("X-Tenant-ID")
    if client_tenant_header and client_tenant_header != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Client tenant ID mismatch. Headers cannot override cryptographically verified token tenant.",
                "correlation_id": correlation_id
            }
        )

    # Database state verification (Revocation, Active status)
    async with AsyncSessionLocal() as session:
        bind = session.bind
        if bind and getattr(bind.dialect, "name", None) == "postgresql":
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)}
            )
        try:
            # 1. Check token revocation list
            # F-21: a revoked session family (logout, refresh-token reuse) kills every
            # access token issued in that session, not only the one presented.
            revoked_ids = [jti]
            if payload.get("fam"):
                revoked_ids.append(f"family:{payload['fam']}")
            rev_stmt = select(SessionRevocation).where(SessionRevocation.token_jti.in_(revoked_ids))
            rev_res = await session.execute(rev_stmt)
            if rev_res.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"error": "Token has been revoked", "correlation_id": correlation_id}
                )

            # 2. Check user active status
            user_stmt = select(User).where(User.id == user_id, User.tenant_id == tenant_id)
            user_res = await session.execute(user_stmt)
            user = user_res.scalars().first()
            if not user or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error": "User account is disabled or does not exist", "correlation_id": correlation_id}
                )

            # 3. Check tenant active status
            tenant_stmt = select(Tenant).where(Tenant.id == tenant_id)
            tenant_res = await session.execute(tenant_stmt)
            tenant = tenant_res.scalars().first()
            if not tenant or not tenant.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"error": "Tenant account is inactive or disabled", "correlation_id": correlation_id}
                )
        finally:
            if bind and getattr(bind.dialect, "name", None) == "postgresql":
                try:
                    await session.execute(text("RESET app.current_tenant_id;"))
                except Exception:
                    pass

    # Bind active tenant into execution context variable
    current_tenant_id_ctx.set(tenant_id)

    return SecurityContext(
        user_id=user_id,
        tenant_id=tenant_id,
        email=payload.get("email", user.email),
        roles=roles,
        permissions=permissions,
        mfa_verified=mfa_verified,
        jti=jti,
        correlation_id=correlation_id,
        family_id=payload.get("fam")
    )

async def get_optional_security_context(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    correlation_id: str = Depends(get_correlation_id)
) -> Optional[SecurityContext]:
    """
    Optional authentication dependency for dual-mode endpoints supporting both
    unauthenticated customer sessions (identified via channel/caller/header) and
    authenticated user sessions. Returns None if no Bearer token is provided.
    """
    if not credentials or not credentials.credentials:
        return None
    return await get_security_context(request, credentials, correlation_id)

def require_permission(permission_code: str) -> Callable:
    """FastAPI dependency factory enforcing server-side RBAC/ABAC permissions."""
    async def permission_checker(
        context: SecurityContext = Depends(get_security_context)
    ) -> SecurityContext:
        has_perm = (
            permission_code in context.permissions
            or policy_service.check_permission(context.roles, permission_code)
        )
        if not has_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": f"Access denied. Missing required permission: {permission_code}",
                    "correlation_id": context.correlation_id
                }
            )
        return context
    return permission_checker

def require_privileged_mfa(
    context: SecurityContext = Depends(get_security_context)
) -> SecurityContext:
    """FastAPI dependency enforcing that privileged roles MUST have mfa_verified=True."""
    if policy_service.has_privileged_role(context.roles) and not context.mfa_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Step-up MFA verification required for privileged role operations.",
                "correlation_id": context.correlation_id,
                "mfa_required": True
            }
        )
    return context
