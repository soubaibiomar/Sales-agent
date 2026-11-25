"""
Identity, Tenancy, and RBAC Management Pydantic Schemas.
"""
from typing import List, Optional
from datetime import datetime
from pydantic import ConfigDict, BaseModel, EmailStr, Field

class TenantCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100)
    tier: str = Field(default="standard")

class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    tier: str
    is_active: bool
    created_at: datetime

class OrganizationSiteCreateRequest(BaseModel):
    name: str = Field(..., min_length=2)
    code: str = Field(..., min_length=2, max_length=50)
    timezone: str = "Africa/Casablanca"
    currency: str = "MAD"

class OrganizationSiteResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    code: str
    timezone: str
    currency: str
    is_active: bool
    created_at: datetime

class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2)
    roles: List[str] = Field(default_factory=lambda: ["sales_representative"])

class MyProfileUpdateRequest(BaseModel):
    """Self-service profile edit: only the display name. Roles, status, e-mail and tenant
    are never accepted here (no privilege change through the profile page)."""
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(..., min_length=1, max_length=120)

class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    roles: Optional[List[str]] = None

class UserResponse(BaseModel):
    id: str
    tenant_id: str
    email: str
    full_name: str
    is_active: bool
    is_verified: bool
    mfa_enabled: bool
    roles: List[str]
    created_at: datetime

class RoleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_privileged: bool
    permissions: List[str]

class AuditLogResponse(BaseModel):
    id: str
    tenant_id: str
    actor_id: Optional[str] = None
    event_type: str
    resource_type: str
    resource_id: Optional[str] = None
    action: str
    ip_address: Optional[str] = None
    status: str
    timestamp: datetime
