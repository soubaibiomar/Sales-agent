"""
Quotation Approval Pydantic Schemas.
(Baseline Controls 05, 07, 15, 16)
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(APPROVED|REJECTED)$")
    reason: Optional[str] = None
    mfa_code: Optional[str] = None  # Optional TOTP MFA code for step-up verification

class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    quote_id: str
    quote_version: int
    terms_hash: str
    requested_by_user_id: str
    requested_at: datetime
    status: str
    decided_by_user_id: Optional[str] = None
    decided_at: Optional[datetime] = None
    decision_reason: Optional[str] = None
    mfa_verified: bool
    decision_signature: Optional[str] = None
    created_at: datetime
    updated_at: datetime
