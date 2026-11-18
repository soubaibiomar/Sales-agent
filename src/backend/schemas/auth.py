"""
Authentication and Session Pydantic Schemas.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    tenant_id: Optional[str] = None
    site_code: Optional[str] = None

class MFAVerifyRequest(BaseModel):
    temp_token: str
    mfa_code: str = Field(..., min_length=6, max_length=6)

class MFASetupResponse(BaseModel):
    secret: str
    otpauth_uri: str

class UserSummary(BaseModel):
    id: str
    tenant_id: str
    email: str
    full_name: str
    roles: List[str]
    mfa_enabled: bool
    is_active: bool

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_in: int
    mfa_required: bool = False
    temp_token: Optional[str] = None
    user: Optional[UserSummary] = None

class TokenPayload(BaseModel):
    sub: str  # user_id
    tenant_id: str
    email: str
    roles: List[str]
    permissions: List[str]
    mfa_verified: bool = False
    jti: str
    exp: int
    iat: int
    iss: str = "sales-ai-platform"
    aud: str = "sales-ai-api"

class TenantSwitchRequest(BaseModel):
    target_tenant_id: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str
