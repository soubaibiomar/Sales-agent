"""
User & Membership Management API Endpoints.
Enforces tenant scoping, least-privilege RBAC, and prevents unauthorized role elevation.
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
    UserCreateRequest, UserResponse, UserUpdateRequest, MyProfileUpdateRequest
)
from src.backend.models.entities import User, Role, UserRole

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns profile for currently authenticated user."""
    stmt = select(User).where(User.id == context.user_id, User.tenant_id == context.tenant_id)
    res = await db.execute(stmt)
    user = res.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "User profile not found", "correlation_id": context.correlation_id}
        )
    return UserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        mfa_enabled=user.mfa_enabled,
        roles=context.roles,
        created_at=user.created_at
    )

@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    req: MyProfileUpdateRequest,
    context: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Updates the signed-in user's display name (Selia profile page). Own record only."""
    name = " ".join(req.full_name.split())
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="full_name must not be blank")
    stmt = select(User).where(User.id == context.user_id, User.tenant_id == context.tenant_id)
    user = (await db.execute(stmt)).scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "User profile not found", "correlation_id": context.correlation_id})
    user.full_name = name
    await db.flush()
    # Build the response inside the transaction: the tenant RLS context is transaction-local,
    # so re-reading the row after commit would not see it.
    response = UserResponse(
        id=user.id, tenant_id=user.tenant_id, email=user.email, full_name=user.full_name,
        is_active=user.is_active, is_verified=user.is_verified, mfa_enabled=user.mfa_enabled,
        roles=context.roles, created_at=user.created_at
    )
    await db.commit()
    return response


@router.get("", response_model=List[UserResponse])
async def list_users(
    context: SecurityContext = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_db_session)
):
    """Lists all users belonging strictly to current active tenant."""
    stmt = select(User).where(User.tenant_id == context.tenant_id)
    res = await db.execute(stmt)
    users = res.scalars().all()

    output = []
    for u in users:
        role_stmt = (
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == u.id, UserRole.tenant_id == context.tenant_id)
        )
        r_res = await db.execute(role_stmt)
        roles = [r[0] for r in r_res.all()]
        output.append(
            UserResponse(
                id=u.id,
                tenant_id=u.tenant_id,
                email=u.email,
                full_name=u.full_name,
                is_active=u.is_active,
                is_verified=u.is_verified,
                mfa_enabled=u.mfa_enabled,
                roles=roles or ["sales_representative"],
                created_at=u.created_at
            )
        )
    return output

@router.post("", response_model=UserResponse)
async def create_user(
    req: UserCreateRequest,
    context: SecurityContext = Depends(require_permission("users:write")),
    db: AsyncSession = Depends(get_db_session)
):
    """Creates a new user strictly inside the current tenant."""
    # Check if email exists in this tenant
    stmt = select(User).where(User.email == req.email, User.tenant_id == context.tenant_id)
    res = await db.execute(stmt)
    if res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "User with this email already exists in tenant", "correlation_id": context.correlation_id}
        )

    # Check if creating a privileged user requires privileged MFA from caller
    is_creating_privileged = any(policy_service.is_privileged_role(r) for r in req.roles)
    if is_creating_privileged and not context.mfa_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "MFA verification required to create users with privileged roles", "correlation_id": context.correlation_id}
        )

    new_user = User(
        tenant_id=context.tenant_id,
        email=req.email,
        full_name=req.full_name,
        hashed_password=SecurityService.hash_password(req.password),
        is_active=True,
        is_verified=True
    )
    db.add(new_user)
    await db.flush()

    # Assign roles
    for r_name in req.roles:
        r_stmt = select(Role).where(Role.name == r_name)
        r_res = await db.execute(r_stmt)
        role = r_res.scalars().first()
        if role:
            ur = UserRole(user_id=new_user.id, role_id=role.id, tenant_id=context.tenant_id)
            db.add(ur)

    await db.commit()
    await db.refresh(new_user)

    return UserResponse(
        id=new_user.id,
        tenant_id=new_user.tenant_id,
        email=new_user.email,
        full_name=new_user.full_name,
        is_active=new_user.is_active,
        is_verified=new_user.is_verified,
        mfa_enabled=new_user.mfa_enabled,
        roles=req.roles,
        created_at=new_user.created_at
    )

@router.put("/{user_id}/status", response_model=UserResponse)
async def update_user_status(
    user_id: str,
    req: UserUpdateRequest,
    context: SecurityContext = Depends(require_permission("users:write")),
    _mfa: SecurityContext = Depends(require_privileged_mfa),
    db: AsyncSession = Depends(get_db_session)
):
    """Enables or disables a user account in the current tenant."""
    stmt = select(User).where(User.id == user_id, User.tenant_id == context.tenant_id)
    res = await db.execute(stmt)
    user = res.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "User not found in current tenant", "correlation_id": context.correlation_id}
        )

    if req.is_active is not None:
        user.is_active = req.is_active
    if req.full_name is not None:
        user.full_name = req.full_name

    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
        mfa_enabled=user.mfa_enabled,
        roles=context.roles,
        created_at=user.created_at
    )
