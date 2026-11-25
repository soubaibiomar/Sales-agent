"""
Server-Side Authorization & Policy Service (RBAC & ABAC).
Guarantees fail-closed evaluation of actions against role permissions.
Never trusts client-supplied roles, tenant IDs, or prompt claims.
"""
from typing import List, Set, Dict, Optional
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.backend.models.entities import Role, Permission, UserRole, User

logger = logging.getLogger("SalesAI.PolicyService")

DEFAULT_ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "super_admin": ["*"],
    "tenant_admin": [
        "tenant:read", "tenant:update", "users:read", "users:write",
        "roles:assign", "sites:read", "sites:write", "audit:read",
        "catalog:read", "catalog:write", "quotes:read", "quotes:write",
        "orders:read", "orders:write", "inventory:read", "inventory:write",
        "conversations:read", "conversations:write", "conversations:handoff",
        "workflows:read", "workflows:manage", "notifications:manage", "integrations:manage",
        # F-34: domain permissions required by the API (previously super_admin only)
        "crm:read", "crm:write", "inventory:manage", "orders:manage", "procurement:manage", "procurement:read",
        "quotes:create", "saas:manage",  # read/create what admins manage; saas:manage = quota adjustment (MFA)
        "logistics:read", "logistics:manage", "scheduling:read", "scheduling:manage",
        "support:read", "support:manage", "ai:agents", "ai:copilot", "ai:manage", "ai:rag",
        "ai:tools", "voice:copilot"
    ],
    "sales_manager": [
        "users:read", "sites:read", "catalog:read", "catalog:write",
        "quotes:read", "quotes:create", "quotes:write", "quotes:approve", "quotes:discount_override",
        "orders:read", "orders:write", "inventory:read", "copilot:access",
        "audit:read", "conversations:read", "conversations:write", "conversations:handoff",
        "crm:read", "crm:write", "orders:manage", "logistics:read", "scheduling:read",
        "scheduling:manage", "support:read", "ai:agents", "ai:copilot", "ai:rag", "voice:copilot"
    ],
    "sales_representative": [
        "catalog:read", "quotes:read", "quotes:create", "quotes:draft",
        "orders:read", "orders:create", "customers:read", "customers:write",
        "copilot:access", "conversations:read", "conversations:write", "conversations:handoff",
        "crm:read", "crm:write", "scheduling:read", "scheduling:manage", "support:read",
        "logistics:read", "ai:copilot", "ai:rag"
    ],
    "sales_rep": [
        "catalog:read", "quotes:read", "quotes:create", "quotes:draft",
        "orders:read", "orders:create", "customers:read", "customers:write",
        "copilot:access", "conversations:read", "conversations:write", "conversations:handoff",
        "crm:read", "crm:write", "scheduling:read", "scheduling:manage", "support:read",
        "logistics:read", "ai:copilot", "ai:rag"
    ],
    "inventory_manager": [
        "catalog:read", "inventory:read", "inventory:write",
        "procurement:read", "procurement:write", "warehouses:read", "warehouses:write",
        "inventory:manage", "procurement:manage", "logistics:read", "logistics:manage"
    ],
    "support_agent": [
        "tickets:read", "tickets:write", "conversations:read", "conversations:write",
        "conversations:handoff", "returns:read", "returns:write", "customers:read",
        "support:read", "support:manage", "scheduling:read", "scheduling:manage",
        "logistics:read", "crm:read", "ai:rag"
    ],
    "customer": [
        "portal:access", "orders:read_self", "orders:create_self",
        "quotes:view_self", "tickets:create_self"
    ]
}

PRIVILEGED_ROLES = {"super_admin", "tenant_admin", "sales_manager"}

class PolicyService:
    @staticmethod
    def is_privileged_role(role_name: str) -> bool:
        """Determines if a role requires mandatory step-up MFA for sensitive operations."""
        return role_name in PRIVILEGED_ROLES

    @staticmethod
    def has_privileged_role(roles: List[str]) -> bool:
        """Returns True if any assigned role is privileged."""
        return any(role in PRIVILEGED_ROLES for role in roles)

    @classmethod
    def check_permission(cls, user_roles: List[str], required_permission: str) -> bool:
        """
        Fast memory check of assigned roles against required permission.
        Fail-closed: Returns False if required permission is not explicitly granted.
        """
        for role in user_roles:
            permissions = DEFAULT_ROLE_PERMISSIONS.get(role, [])
            if "*" in permissions or required_permission in permissions:
                return True
        return False

    @classmethod
    async def get_user_permissions_from_db(
        cls,
        session: AsyncSession,
        user_id: str,
        tenant_id: str
    ) -> List[str]:
        """Loads effective permissions from database for given user within active tenant."""
        stmt = (
            select(Permission.code)
            .join(Role.permissions)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, UserRole.tenant_id == tenant_id)
        )
        res = await session.execute(stmt)
        codes = [row[0] for row in res.all()]
        
        # Also include default role permissions if DB joins are empty
        if not codes:
            role_stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(
                UserRole.user_id == user_id, UserRole.tenant_id == tenant_id
            )
            role_res = await session.execute(role_stmt)
            for (r_name,) in role_res.all():
                codes.extend(DEFAULT_ROLE_PERMISSIONS.get(r_name, []))

        return list(set(codes))

policy_service = PolicyService()
