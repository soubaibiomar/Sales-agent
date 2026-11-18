"""
Voice AI Platform Pydantic Schemas.
Customer Voice Agent, Manager Voice Copilot, VAD/Barge-in, and Multilingual Audio.
Step 07: Dual-Mode Customer & Manager Voice AI
(Controls 04-07, 28, 35, 39-40, 48-49, 55, 63-67, 70; SAI-01 to SAI-05, SAI-09 to SAI-12)
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# 1. Voice Sessions
class VoiceSessionCreateRequest(BaseModel):
    voice_mode: str = Field("CUSTOMER", max_length=32, description="CUSTOMER or MANAGER")
    channel_type: str = Field("WEBRTC", max_length=32, description="WEBRTC, SIP_PSTN, or WEB_VOICE")
    caller_identifier: Optional[str] = Field(None, max_length=255, description="E.164 phone or browser client ID")
    language: str = Field("fr-FR", max_length=16, description="Preferred language code (fr-FR, en-US, ar-MA, ary-Arab, ary-Latn)")
    recording_consent: bool = Field(False, description="Customer explicit consent to call recording")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class VoiceSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    session_id: str
    channel_type: str
    voice_mode: str
    caller_identifier: Optional[str] = None
    status: str
    language: str
    is_caller_verified: bool
    recording_consent_given: bool
    disclosure_played: bool
    disclosure_text: Optional[str] = None
    turns_count: int
    started_at: datetime
    ended_at: Optional[datetime] = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class VoiceSessionEndRequest(BaseModel):
    reason: Optional[str] = Field("COMPLETED", max_length=50)


# 2. Customer Identity Verification (SAI-01)
class CustomerVerificationRequest(BaseModel):
    otp_code: str = Field(..., min_length=4, max_length=8, description="6-digit verification code or customer PIN")
    phone_or_email: Optional[str] = None


class CustomerVerificationResponse(BaseModel):
    verified: bool
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    customer_name: Optional[str] = None
    message: str


# 3. Voice Turn & Audio Streaming
class VoiceTurnRequest(BaseModel):
    input_text: Optional[str] = None
    audio_base64: Optional[str] = None
    audio_format: Optional[str] = "audio/wav"
    client_timestamp_ms: Optional[int] = None
    is_barge_in: bool = False


class ExecutedToolSummary(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    success: bool
    output_preview: str


class VoiceTurnResponse(BaseModel):
    session_id: str
    turn_index: int
    detected_language: str
    user_transcript: str
    redacted_transcript: str
    agent_response_text: str
    audio_base64: Optional[str] = None
    latency_ms: int
    executed_tools: List[ExecutedToolSummary] = Field(default_factory=list)
    handoff_triggered: bool = False
    handoff_details: Optional[Dict[str, Any]] = None


# 4. Barge-in / Interruption
class VoiceBargeInNotification(BaseModel):
    session_id: str
    interrupted_turn_index: int
    energy_level: float
    timestamp_ms: int


# 5. Manager Voice Copilot Actions & Step-Up MFA (SAI-02)
class ManagerCommandRequest(BaseModel):
    command_text: Optional[str] = None
    audio_base64: Optional[str] = None


class ManagerActionPreview(BaseModel):
    action_token: str
    action_type: str
    requires_step_up_mfa: bool
    risk_level: str  # LOW, MEDIUM, HIGH
    parameters: Dict[str, Any]
    summary: str
    expires_at_ms: int


class ManagerCommandResponse(BaseModel):
    session_id: str
    insight_text: str
    audio_base64: Optional[str] = None
    action_preview: Optional[ManagerActionPreview] = None
    requires_confirmation: bool = False


class ManagerConfirmationRequest(BaseModel):
    action_token: str
    totp_code: Optional[str] = None
    confirmed: bool = True


class ManagerConfirmationResponse(BaseModel):
    action_token: str
    executed: bool
    result: Dict[str, Any]
    message: str


# 6. Human Handoff (SAI-11)
class VoiceHandoffRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=255)
    target_department: str = Field("SUPPORT", max_length=50)


class VoiceHandoffResponse(BaseModel):
    session_id: str
    handoff_status: str
    assigned_queue: str
    summary_for_agent: str
    timestamp: datetime


# 7. Transcripts & Recordings
class VoiceTranscriptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    turn_index: int
    speaker_type: str
    redacted_text: str
    language: str
    latency_ms: int
    is_barge_in: bool
    created_at: datetime


class VoiceRecordingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    storage_path: str
    duration_seconds: int
    file_size_bytes: int
    mime_type: str
    encryption_algorithm: str
    expires_at: datetime
    created_at: datetime
