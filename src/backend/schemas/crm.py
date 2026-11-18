"""
CRM Pydantic Schemas.
(Baseline Controls 15, 16)
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, EmailStr, ConfigDict

class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    account_type: str = Field(default="CUSTOMER", max_length=50)
    tax_identifier: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    website: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None
    assigned_user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    account_type: str
    tax_identifier: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None
    assigned_user_id: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

class LeadCreate(BaseModel):
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    company_name: Optional[str] = Field(default=None, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    source: str = Field(default="MANUAL", max_length=50)
    score: int = Field(default=10, ge=0, le=100)
    assigned_user_id: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class LeadConvertRequest(BaseModel):
    opportunity_title: str = Field(..., min_length=1, max_length=255)
    estimated_amount_cents: int = Field(default=0, ge=0)
    currency: str = Field(default="MAD", max_length=10)

class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: str
    source: str
    score: int
    assigned_user_id: Optional[str] = None
    converted_account_id: Optional[str] = None
    converted_contact_id: Optional[str] = None
    converted_opportunity_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class OpportunityCreate(BaseModel):
    account_id: str
    title: str = Field(..., min_length=1, max_length=255)
    amount_cents: int = Field(default=0, ge=0)
    currency: str = Field(default="MAD", max_length=10)
    stage: str = Field(default="DISCOVERY", max_length=50)
    probability_percent: int = Field(default=20, ge=0, le=100)
    contact_id: Optional[str] = None
    lead_id: Optional[str] = None
    expected_close_date: Optional[datetime] = None
    assigned_user_id: Optional[str] = None
    notes: Optional[str] = None

class OpportunityUpdateStage(BaseModel):
    stage: str = Field(..., min_length=1, max_length=50)
    lost_reason: Optional[str] = None

class OpportunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    account_id: str
    contact_id: Optional[str] = None
    lead_id: Optional[str] = None
    title: str
    stage: str
    amount_cents: int
    currency: str
    probability_percent: int
    expected_close_date: Optional[datetime] = None
    assigned_user_id: Optional[str] = None
    lost_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class ActivityCreate(BaseModel):
    activity_type: str = Field(..., max_length=50)
    subject: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    assigned_user_id: Optional[str] = None
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    account_id: Optional[str] = None
    contact_id: Optional[str] = None

class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    activity_type: str
    subject: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    assigned_user_id: Optional[str] = None
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    created_at: datetime

