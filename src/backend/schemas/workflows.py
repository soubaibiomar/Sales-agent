"""
Pydantic Schemas for Durable Workflows & Sagas.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator


class WorkflowExecutionCreateRequest(BaseModel):
    workflow_type: str = Field(..., description="Type identifier of the workflow saga (e.g. CHECKOUT_SAGA, STOCK_EXPIRY, QUOTE_APPROVAL_ESCALATION, FULFILLMENT_DISPATCH, RMA_TRIAGE)")
    idempotency_key: str = Field(..., description="Client or caller idempotency key ensuring deduplication")
    correlation_id: Optional[str] = Field(None, description="End-to-end tracing correlation ID")
    workflow_name: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict, description="Input parameters for the workflow saga")
    input_payload: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def resolve_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "input_payload" in data and not data.get("payload"):
                data["payload"] = data["input_payload"]
        return data


class WorkflowStepLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    step_name: str
    step_type: str
    status: str
    input_json: Optional[Dict[str, Any]] = None
    output_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    duration_ms: int = 0
    created_at: datetime


class WorkflowExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    workflow_type: str
    correlation_id: str
    idempotency_key: str
    status: str
    current_step: Optional[str] = None
    payload_json: Dict[str, Any]
    result_json: Optional[Dict[str, Any]] = None
    error_details: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    step_logs: List[WorkflowStepLogResponse] = Field(default_factory=list)


class WorkflowRetryRequest(BaseModel):
    override_max_retries: Optional[int] = Field(None, description="Optional override of max retry limit")
    reset_compensation: bool = Field(False, description="Whether to re-attempt action steps or continue compensation")


class AutomationRuleCreateRequest(BaseModel):
    name: str
    trigger_event: str
    condition: Optional[Dict[str, Any]] = Field(default_factory=dict)
    action_type: str
    action_config: Optional[Dict[str, Any]] = Field(default_factory=dict)
    is_active: bool = True


class AutomationRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    trigger_event: str
    condition_json: Optional[Dict[str, Any]] = None
    action_type: str
    action_config_json: Optional[Dict[str, Any]] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
