"""
Tenant Lifecycle & Context Switching API Endpoints.
Guarantees tenant isolation and zero-trust validation on tenant switching.
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.security import SecurityService
from src.backend.core.policy_service import policy_service
from src.backend.core.auth_middleware import (
    get_security_context, SecurityContext, require_permission, require_privileged_mfa
)
from src.backend.schemas.identity import (
    TenantCreateRequest, TenantResponse
)
from src.backend.schemas.auth import (
    TenantSwitchRequest, TokenResponse, UserSummary
)
from src.backend.models.entities import Tenant, UserRole, Role, User

router = APIRouter(prefix="/tenants", tags=["Tenancy"])

@router.get("/current", response_model=TenantResponse)
async def get_current_tenant(
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns details of the currently authenticated tenant."""
    stmt = select(Tenant).where(Tenant.id == context.tenant_id)
    res = await db.execute(stmt)
    tenant = res.scalars().first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Tenant not found", "correlation_id": context.correlation_id}
        )
    return tenant

@router.post("", response_model=TenantResponse)
async def create_tenant(
    req: TenantCreateRequest,
    context: SecurityContext = Depends(require_permission("*")),
    _mfa: SecurityContext = Depends(require_privileged_mfa),
    db: AsyncSession = Depends(get_db_session)
):
    """Provisions a new tenant. Restricted to super_admin."""
    # Check slug uniqueness
    stmt = select(Tenant).where(Tenant.slug == req.slug)
    res = await db.execute(stmt)
    if res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Tenant with this slug already exists", "correlation_id": context.correlation_id}
        )

    tenant = Tenant(
        name=req.name,
        slug=req.slug,
        tier=req.tier
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return tenant

@router.post("/switch", response_model=TokenResponse)
async def switch_tenant(
    req: TenantSwitchRequest,
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Switches active tenant for the logged-in user.
    ZERO-TRUST CHECK: Validates that the user has verified membership in target_tenant_id.
    """
    target_tenant_id = req.target_tenant_id

    # 1. Verify target tenant exists and is active
    t_stmt = select(Tenant).where(Tenant.id == target_tenant_id, Tenant.is_active == True)
    t_res = await db.execute(t_stmt)
    target_tenant = t_res.scalars().first()
    if not target_tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Target tenant not found or inactive", "correlation_id": context.correlation_id}
        )

    # 2. Check user membership in target tenant
    # Super admins can switch freely; regular users must have a verified user/role record in target tenant
    is_super_admin = "super_admin" in context.roles

    if not is_super_admin:
        # Check if user exists in target tenant
        u_stmt = select(User).where(User.email == context.email, User.tenant_id == target_tenant_id)
        u_res = await db.execute(u_stmt)
        target_user = u_res.scalars().first()

        if not target_user or not target_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "Cross-tenant access denied: You do not have an active membership in the target tenant.",
                    "correlation_id": context.correlation_id
                }
            )
        effective_user_id = target_user.id
        effective_mfa_enabled = target_user.mfa_enabled
    else:
        effective_user_id = context.user_id
        effective_mfa_enabled = True

    # 3. Fetch roles in target tenant
    role_stmt = (
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == effective_user_id, UserRole.tenant_id == target_tenant_id)
    )
    role_res = await db.execute(role_stmt)
    target_roles = [r[0] for r in role_res.all()]
    if not target_roles and is_super_admin:
        target_roles = ["super_admin"]
    elif not target_roles:
        target_roles = ["sales_representative"]

    # Load target permissions
    target_permissions = await policy_service.get_user_permissions_from_db(
        db, effective_user_id, target_tenant_id
    )

    # 4. Mint fresh tokens scoped to target tenant
    access_token, jti, exp = SecurityService.create_access_token(
        user_id=effective_user_id,
        tenant_id=target_tenant_id,
        email=context.email,
        roles=target_roles,
        permissions=target_permissions,
        mfa_verified=context.mfa_verified
    )
    refresh_token, _, _ = SecurityService.create_refresh_token(
        user_id=effective_user_id,
        tenant_id=target_tenant_id
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        expires_in=1800,
        mfa_required=False,
        user=UserSummary(
            id=effective_user_id,
            tenant_id=target_tenant_id,
            email=context.email,
            full_name=context.email.split("@")[0],
            roles=target_roles,
            mfa_enabled=effective_mfa_enabled,
            is_active=True
        )
    )
