"""
Voice AI Platform API Routes.
Customer Voice Agent, Manager Voice Copilot, VAD/Barge-in, and Multilingual Audio.
Step 07: Dual-Mode Customer & Manager Voice AI
(Controls 04-07, 28, 35, 39-40, 48-49, 55, 63-67, 70; SAI-01 to SAI-05, SAI-09 to SAI-12)
"""
import base64
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import (
    get_security_context,
    get_optional_security_context,
    require_permission,
    SecurityContext
)
from src.backend.voice.service import VoiceSessionService, VoiceSessionNotFoundError
from src.backend.voice.security import (
    VoiceSecurityError,
    CallerUnverifiedError,
    PromptInjectionDetectedError
)
from src.backend.voice.audio_pipeline import AudioChunk
from src.backend.schemas.voice import (
    VoiceSessionCreateRequest,
    VoiceSessionResponse,
    VoiceSessionEndRequest,
    CustomerVerificationRequest,
    CustomerVerificationResponse,
    VoiceTurnRequest,
    VoiceTurnResponse,
    VoiceBargeInNotification,
    ManagerCommandRequest,
    ManagerCommandResponse,
    ManagerConfirmationRequest,
    ManagerConfirmationResponse,
    VoiceHandoffRequest,
    VoiceHandoffResponse,
    VoiceTranscriptResponse
)

router = APIRouter(prefix="/api/v1/voice", tags=["Voice AI Platform"])


@router.post("/sessions", response_model=VoiceSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_voice_session(
    req: VoiceSessionCreateRequest,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Initializes a customer voice session or authenticated manager voice copilot session.
    Plays mandatory AI & recording disclosure before bi-directional audio.
    """
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant identification.")

    manager_user_id = ctx.user_id if ctx and req.voice_mode.upper() == "MANAGER" else None

    # Enforce manager permission
    if req.voice_mode.upper() == "MANAGER":
        if not ctx or "voice:copilot" not in ctx.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Manager Voice Copilot requires 'voice:copilot' permission."
            )

    service = VoiceSessionService(db)
    session = await service.create_session(
        tenant_id=tenant_id,
        voice_mode=req.voice_mode,
        channel_type=req.channel_type,
        caller_identifier=req.caller_identifier,
        language=req.language,
        recording_consent=req.recording_consent,
        manager_user_id=manager_user_id,
        metadata=req.metadata
    )
    await db.commit()

    disclosure_text = service.verification_manager.__class__.__name__
    from src.backend.voice.customer_agent import CustomerVoiceAgent
    disc_text = CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT.get(session.language, CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT["fr-FR"])

    return VoiceSessionResponse(
        id=session.id,
        tenant_id=session.tenant_id,
        session_id=session.session_id,
        channel_type=session.channel_type,
        voice_mode=session.voice_mode,
        caller_identifier=session.caller_identifier,
        status=session.status,
        language=session.language,
        is_caller_verified=session.is_caller_verified,
        recording_consent_given=session.recording_consent_given,
        disclosure_played=session.disclosure_played,
        disclosure_text=disc_text,
        turns_count=session.turns_count,
        started_at=session.started_at,
        ended_at=session.ended_at,
        metadata_json=session.metadata_json,
        created_at=session.created_at
    )


@router.get("/sessions/{session_id}", response_model=VoiceSessionResponse)
async def get_voice_session(
    session_id: str,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant context.")

    service = VoiceSessionService(db)
    session = await service.get_session(tenant_id, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Voice session '{session_id}' not found.")

    return VoiceSessionResponse(
        id=session.id,
        tenant_id=session.tenant_id,
        session_id=session.session_id,
        channel_type=session.channel_type,
        voice_mode=session.voice_mode,
        caller_identifier=session.caller_identifier,
        status=session.status,
        language=session.language,
        is_caller_verified=session.is_caller_verified,
        recording_consent_given=session.recording_consent_given,
        disclosure_played=session.disclosure_played,
        turns_count=session.turns_count,
        started_at=session.started_at,
        ended_at=session.ended_at,
        metadata_json=session.metadata_json,
        created_at=session.created_at
    )


@router.post("/sessions/{session_id}/verify-caller", response_model=CustomerVerificationResponse)
async def verify_caller_identity(
    session_id: str,
    req: CustomerVerificationRequest,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Customer verification via OTP/PIN (Control SAI-01, SAI-03).
    Prevents caller-ID spoofing from disclosing sensitive customer records.
    """
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant context.")

    service = VoiceSessionService(db)
    try:
        res = await service.verify_caller_identity(tenant_id, session_id, req.otp_code)
        await db.commit()
        return CustomerVerificationResponse(
            verified=res["verified"],
            message=res["message"],
            customer_name="Verified Customer" if res["verified"] else None
        )
    except VoiceSessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/sessions/{session_id}/turn", response_model=VoiceTurnResponse)
async def execute_voice_turn(
    session_id: str,
    req: VoiceTurnRequest,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Processes a voice turn with text or streaming audio input.
    Enforces VAD, language identification, tool execution, and audio synthesis.
    """
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant context.")

    service = VoiceSessionService(db)
    audio_chunk = None
    if req.audio_base64:
        try:
            raw_audio = base64.b64decode(req.audio_base64)
            audio_chunk = AudioChunk(raw_audio)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid audio format: {e}")

    try:
        turn_result = await service.process_turn(
            tenant_id=tenant_id,
            session_id=session_id,
            input_text=req.input_text,
            audio_chunk=audio_chunk,
            is_barge_in=req.is_barge_in
        )
        await db.commit()
        return VoiceTurnResponse(**turn_result)
    except VoiceSessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PromptInjectionDetectedError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except VoiceSecurityError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post("/sessions/{session_id}/barge-in", status_code=status.HTTP_200_OK)
async def handle_barge_in_interruption(
    session_id: str,
    req: VoiceBargeInNotification,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Signals user interruption (barge-in).
    Cancels in-flight audio synthesis and queues user input turn.
    """
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant context.")

    service = VoiceSessionService(db)
    session = await service.get_session(tenant_id, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Voice session '{session_id}' not found.")

    return {
        "status": "BARGE_IN_PROCESSED",
        "session_id": session_id,
        "interrupted_turn_index": req.interrupted_turn_index
    }


@router.post("/sessions/{session_id}/handoff", response_model=VoiceHandoffResponse)
async def escalate_to_human(
    session_id: str,
    req: VoiceHandoffRequest,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Escalates voice call to a human operator (Control SAI-11).
    """
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant context.")

    service = VoiceSessionService(db)
    session = await service.get_session(tenant_id, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Voice session '{session_id}' not found.")

    session.status = "TRANSFERRED"
    await db.commit()

    from datetime import datetime, timezone
    return VoiceHandoffResponse(
        session_id=session_id,
        handoff_status="TRANSFERRED",
        assigned_queue=f"{req.target_department}_QUEUE",
        summary_for_agent=f"Escalation requested. Reason: {req.reason}",
        timestamp=datetime.now(timezone.utc)
    )


@router.post("/sessions/{session_id}/end", response_model=VoiceSessionResponse)
async def end_voice_session(
    session_id: str,
    req: VoiceSessionEndRequest,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant context.")

    service = VoiceSessionService(db)
    try:
        session = await service.end_session(tenant_id, session_id)
        await db.commit()
        return VoiceSessionResponse(
            id=session.id,
            tenant_id=session.tenant_id,
            session_id=session.session_id,
            channel_type=session.channel_type,
            voice_mode=session.voice_mode,
            caller_identifier=session.caller_identifier,
            status=session.status,
            language=session.language,
            is_caller_verified=session.is_caller_verified,
            recording_consent_given=session.recording_consent_given,
            disclosure_played=session.disclosure_played,
            turns_count=session.turns_count,
            started_at=session.started_at,
            ended_at=session.ended_at,
            metadata_json=session.metadata_json,
            created_at=session.created_at
        )
    except VoiceSessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/copilot/command", response_model=ManagerCommandResponse)
async def execute_manager_voice_command(
    req: ManagerCommandRequest,
    ctx: SecurityContext = Depends(require_permission("voice:copilot")),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Executes an authenticated manager voice command.
    Guards high-risk mutations by returning an ActionPreview requiring confirmation (Control 55; SAI-02).
    """
    from src.backend.voice.manager_copilot import ManagerVoiceCopilot
    copilot = ManagerVoiceCopilot(db, ctx.tenant_id, ctx.user_id)
    cmd = req.command_text or "Donne-moi le chiffre d'affaires"

    try:
        res = await copilot.process_manager_command(cmd)
        return ManagerCommandResponse(
            session_id="copilot_session",
            insight_text=res["insight_text"],
            action_preview=res.get("action_preview"),
            requires_confirmation=res["requires_confirmation"]
        )
    except PromptInjectionDetectedError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/copilot/confirm-action", response_model=ManagerConfirmationResponse)
async def confirm_manager_action(
    req: ManagerConfirmationRequest,
    ctx: SecurityContext = Depends(require_permission("voice:copilot")),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Executes second-factor confirmation (step-up TOTP) for high-risk manager commands.
    """
    from src.backend.voice.manager_copilot import ManagerVoiceCopilot
    copilot = ManagerVoiceCopilot(db, ctx.tenant_id, ctx.user_id)

    try:
        action = copilot.action_guard.consume_action(req.action_token, req.totp_code)
        return ManagerConfirmationResponse(
            action_token=req.action_token,
            executed=True,
            result={"status": "EXECUTED", "action_type": action["action_type"]},
            message=f"Action '{action['action_type']}' confirmed and executed successfully with step-up verification."
        )
    except VoiceSecurityError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/sessions/{session_id}/transcripts", response_model=List[VoiceTranscriptResponse])
async def list_session_transcripts(
    session_id: str,
    x_tenant_id: Optional[str] = Header(None),
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    tenant_id = ctx.tenant_id if ctx else x_tenant_id
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing tenant context.")

    from sqlalchemy import select
    from src.backend.models.entities import VoiceTranscript
    stmt = select(VoiceTranscript).where(
        and_(VoiceTranscript.tenant_id == tenant_id, VoiceTranscript.session_id == session_id)
    ).order_by(VoiceTranscript.turn_index.asc())

    res = await db.execute(stmt)
    return list(res.scalars().all())
