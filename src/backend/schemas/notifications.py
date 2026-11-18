"""
Pydantic Schemas for Notification Orchestrator & Templates.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator


class NotificationTemplateCreateRequest(BaseModel):
    template_code: str = Field(..., description="Unique code e.g. ORDER_CONFIRMED, QUOTE_APPROVAL_REQUIRED, APPOINTMENT_REMINDER")
    channel_type: str = Field(..., description="EMAIL, WHATSAPP, IN_APP")
    message_class: str = Field("TRANSACTIONAL", description="MARKETING, TRANSACTIONAL, SERVICE, SECURITY")
    language: str = Field("fr-FR", description="fr-FR, en-US, ar-MA, ary-Arab, ary-Latn")
    subject_template: Optional[str] = None
    body_template: str
    variables: List[str] = Field(default_factory=list)
    is_active: bool = True

    @model_validator(mode="before")
    @classmethod
    def resolve_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "name" in data and not data.get("template_code"):
                data["template_code"] = data["name"]
            if "channel" in data and not data.get("channel_type"):
                data["channel_type"] = data["channel"]
        return data


class NotificationTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    template_code: str
    channel_type: str
    message_class: str
    language: str
    subject_template: Optional[str] = None
    body_template: str
    variables_json: List[str] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class NotificationSendRequest(BaseModel):
    recipient_identifier: str = Field(..., description="Email address, phone number (+212...), or user ID")
    channel_type: str = Field("WHATSAPP", description="EMAIL, WHATSAPP, IN_APP")
    message_class: str = Field("TRANSACTIONAL", description="MARKETING, TRANSACTIONAL, SERVICE, SECURITY")
    template_code: Optional[str] = Field(None, description="Optional template code to render")
    subject: Optional[str] = None
    content: Optional[str] = Field(None, description="Direct text or rendered body")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Variables for template substitution")
    language: str = Field("fr-FR", description="Target language")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def resolve_send_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "recipient" in data and not data.get("recipient_identifier"):
                data["recipient_identifier"] = data["recipient"]
            if "channel" in data and not data.get("channel_type"):
                data["channel_type"] = data["channel"]
            if "template_name" in data and not data.get("template_code"):
                data["template_code"] = data["template_name"]
        return data


class NotificationLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    template_id: Optional[str] = None
    recipient_identifier: str
    channel_type: str
    message_class: str
    subject: Optional[str] = None
    content: str
    status: str
    error_reason: Optional[str] = None
    retry_count: int = 0
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    sent_at: Optional[datetime] = None


class OptOutRequest(BaseModel):
    channel_type: str = "WHATSAPP"
    recipient_identifier: str
    directive: str = Field("STOP", description="Opt-out directive e.g. STOP, BARAKA, HBS, UNSUBSCRIBE")

    @model_validator(mode="before")
    @classmethod
    def resolve_optout_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "recipient" in data and not data.get("recipient_identifier"):
                data["recipient_identifier"] = data["recipient"]
            if "channel" in data and not data.get("channel_type"):
                data["channel_type"] = data["channel"]
            if "inbound_message_text" in data and not data.get("directive"):
                data["directive"] = data["inbound_message_text"]
        return data
