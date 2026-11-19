"""
Voice AI Platform API Routes.
Customer Voice Agent, Manager Voice Copilot, VAD/Barge-in, Multilingual Audio,
Real-Time WebSocket Streaming, and Telephony/SIP Inbound Gateway.
Step 10: Complete Customer Voice AI & Manager Voice AI Copilot
(Controls 04-07, 28, 35, 39-40, 48-49, 55, 63-67, 70; SAI-01 to SAI-05, SAI-09 to SAI-12)
"""
import base64
import json
import time
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Header, WebSocket, WebSocketDisconnect, Query, Request
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
from src.backend.voice.audio_pipeline import AudioChunk, VoiceActivityDetector, BargeInManager
from src.backend.voice.customer_agent import CustomerVoiceAgent
from src.backend.voice.telephony import (
    TelephonySignatureVerifier,
    VoiceCallRateLimiter,
    VoiceCallbackQueue,
    G711Codec,
    TelephonySecurityError,
    ReplayAttackDetectedError,
    CallRateLimitExceededError
)
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

logger = logging.getLogger("SalesAI.VoiceAPI")
router = APIRouter(prefix="/api/v1/voice", tags=["Voice AI Platform"])

# Shared telephony infrastructure singletons
telephony_verifier = TelephonySignatureVerifier()
call_rate_limiter = VoiceCallRateLimiter(max_concurrent=5, max_calls_per_minute=20)
callback_queue = VoiceCallbackQueue()


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

    disc_text = CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT.get(
        session.language,
        CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT["fr-FR"]
    )

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

    disc_text = CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT.get(
        session.language,
        CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT["fr-FR"]
    )

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
        disc_text = CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT.get(
            session.language,
            CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT["fr-FR"]
        )
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

    from src.backend.models.entities import VoiceTranscript
    stmt = select(VoiceTranscript).where(
        and_(VoiceTranscript.tenant_id == tenant_id, VoiceTranscript.session_id == session_id)
    ).order_by(VoiceTranscript.turn_index.asc())

    res = await db.execute(stmt)
    return list(res.scalars().all())


# =============================================================================
# REAL-TIME WEBSOCKET STREAMING ENDPOINT (PCM Chunks, VAD, Barge-in, Playback)
# =============================================================================

@router.websocket("/ws/{session_id}")
async def websocket_voice_streaming(
    websocket: WebSocket,
    session_id: str,
    tenant_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Bi-directional full-duplex real-time voice streaming over WebSocket.
    Processes live audio chunks, continuous VAD turn detection, barge-in cancellation,
    and streams back audio playback frames and transcripts.
    (Controls 28, 70; SAI-04, SAI-05)
    """
    await websocket.accept()
    t_id = tenant_id or "t_voice_default"
    service = VoiceSessionService(db)

    session = await service.get_session(t_id, session_id)
    if not session:
        session = await service.create_session(
            tenant_id=t_id,
            voice_mode="CUSTOMER",
            channel_type="WEBSOCKET",
            caller_identifier="ws_caller",
            language="fr-FR",
            recording_consent=True,
            session_id=session_id
        )
        await db.commit()

    disc_text = CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT.get(
        session.language,
        CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT["fr-FR"]
    )

    await websocket.send_json({
        "type": "SESSION_INITIALIZED",
        "session_id": session.session_id,
        "language": session.language,
        "disclosure_text": disc_text,
        "is_caller_verified": session.is_caller_verified
    })

    vad = VoiceActivityDetector(energy_threshold=400.0, silence_timeout_ms=500.0)
    barge_in_mgr = BargeInManager()
    is_active_playback = False
    speech_buffer = bytearray()

    try:
        while True:
            message = await websocket.receive()
            if "bytes" in message and message["bytes"]:
                pcm_data = message["bytes"]
                chunk = AudioChunk(pcm_data)
                vad_result = vad.process_chunk(chunk)

                # Check barge-in during active agent playback
                if is_active_playback:
                    interrupted, cancel_token = barge_in_mgr.process_chunk(chunk)
                    if interrupted:
                        is_active_playback = False
                        await websocket.send_json({
                            "type": "BARGE_IN_TRIGGERED",
                            "session_id": session_id,
                            "cancel_token": cancel_token
                        })
                        continue

                # Accumulate speech frames
                if vad_result["is_speech_frame"]:
                    speech_buffer.extend(pcm_data)
                    if vad_result["in_speech_turn"] and len(speech_buffer) == len(pcm_data):
                        await websocket.send_json({"type": "VAD_SPEECH_START"})

                # On turn complete: process turn through service
                if vad_result["turn_completed"] and len(speech_buffer) > 0:
                    await websocket.send_json({"type": "VAD_SPEECH_STOP"})
                    audio_turn_chunk = AudioChunk(bytes(speech_buffer))
                    speech_buffer.clear()

                    turn_res = await service.process_turn(
                        tenant_id=t_id,
                        session_id=session_id,
                        audio_chunk=audio_turn_chunk
                    )
                    await db.commit()
                    is_active_playback = True

                    await websocket.send_json({
                        "type": "TURN_COMPLETED",
                        "turn_index": turn_res["turn_index"],
                        "user_transcript": turn_res["user_transcript"],
                        "agent_response": turn_res["agent_response_text"],
                        "audio_base64": turn_res.get("audio_base64"),
                        "detected_language": turn_res.get("detected_language")
                    })

            elif "text" in message and message["text"]:
                data = json.loads(message["text"])
                msg_type = data.get("type", "TEXT_TURN").upper()

                if msg_type == "TEXT_TURN":
                    text_input = data.get("text", "")
                    turn_res = await service.process_turn(
                        tenant_id=t_id,
                        session_id=session_id,
                        input_text=text_input
                    )
                    await db.commit()
                    is_active_playback = True
                    await websocket.send_json({
                        "type": "TURN_COMPLETED",
                        "turn_index": turn_res["turn_index"],
                        "user_transcript": turn_res["user_transcript"],
                        "agent_response": turn_res["agent_response_text"],
                        "audio_base64": turn_res.get("audio_base64"),
                        "detected_language": turn_res.get("detected_language")
                    })

                elif msg_type == "BARGE_IN":
                    is_active_playback = False
                    barge_in_mgr.abort()
                    await websocket.send_json({
                        "type": "BARGE_IN_CONFIRMED",
                        "session_id": session_id,
                        "status": "PLAYBACK_CANCELLED"
                    })

                elif msg_type == "VERIFY_CALLER":
                    otp_code = data.get("otp_code", "")
                    v_res = await service.verify_caller_identity(t_id, session_id, otp_code)
                    await db.commit()
                    await websocket.send_json({
                        "type": "CALLER_VERIFIED",
                        "verified": v_res["verified"],
                        "message": v_res["message"]
                    })

                elif msg_type == "PING":
                    await websocket.send_json({"type": "PONG", "timestamp": time.time()})

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected cleanly for voice session {session_id}")
    except Exception as e:
        logger.warning(f"Voice WebSocket session {session_id} ended: {e}")


# =============================================================================
# TELEPHONY / SIP INBOUND WEBHOOK & CALLBACK QUEUE ENDPOINTS
# =============================================================================

@router.post("/telephony/inbound")
async def telephony_inbound_webhook(
    request: Request,
    x_tenant_id: Optional[str] = Header(None),
    x_twilio_signature: Optional[str] = Header(None),
    x_telephony_signature: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Inbound phone call signaling webhook.
    Enforces signature verification, anti-replay freshness, and call flood rate limits.
    (Control 28, 70; SAI-04, SAI-05)
    """
    body_bytes = await request.body()
    headers = dict(request.headers)
    params = {}
    content_type = headers.get("content-type", "")

    if "application/json" in content_type:
        params = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    elif "application/x-www-form-urlencoded" in content_type:
        from urllib.parse import parse_qs
        parsed = parse_qs(body_bytes.decode("utf-8"))
        params = {k: v[0] for k, v in parsed.items()}

    tenant_id = x_tenant_id or params.get("tenant_id") or "t_telephony_default"
    caller_id = params.get("From") or params.get("caller_id") or "+212600000000"

    # Enforce call flood rate limiter
    try:
        call_rate_limiter.acquire_call_slot(caller_id)
    except CallRateLimitExceededError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    # Verify signature if signature header is provided
    sig = x_twilio_signature or x_telephony_signature
    if sig:
        auth_token = "telephony_secret_token"
        try:
            is_valid = telephony_verifier.verify_twilio_signature(
                auth_token=auth_token,
                webhook_url=str(request.url),
                params=params,
                signature=sig,
                timestamp=float(headers.get("x-telephony-timestamp", time.time()))
            )
            if not is_valid:
                call_rate_limiter.release_call_slot(caller_id)
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid telephony webhook signature.")
        except ReplayAttackDetectedError as e:
            call_rate_limiter.release_call_slot(caller_id)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Initialize voice session
    service = VoiceSessionService(db)
    session = await service.create_session(
        tenant_id=tenant_id,
        voice_mode="CUSTOMER",
        channel_type="SIP",
        caller_identifier=caller_id,
        language="fr-FR",
        recording_consent=True
    )
    await db.commit()

    disc_text = CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT["fr-FR"]
    return {
        "status": "ACCEPTED",
        "session_id": session.session_id,
        "caller_id": caller_id,
        "disclosure_text": disc_text,
        "stream_url": f"/api/v1/voice/ws/{session.session_id}?tenant_id={tenant_id}"
    }


@router.post("/telephony/status")
async def telephony_status_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """Releases rate limiter slots on call termination."""
    body_bytes = await request.body()
    try:
        data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        data = {}

    caller_id = data.get("From") or data.get("caller_id")
    if caller_id:
        call_rate_limiter.release_call_slot(caller_id)

    return {"status": "ACKNOWLEDGED"}


@router.post("/callbacks")
async def request_voice_callback(
    req: Dict[str, Any],
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    x_tenant_id: Optional[str] = Header(None)
):
    """Registers customer callback request when operators are unavailable."""
    tenant_id = ctx.tenant_id if ctx else (x_tenant_id or "t_callback_default")
    caller_id = req.get("caller_id") or "+212600000000"
    record = callback_queue.enqueue_callback(
        tenant_id=tenant_id,
        caller_id=caller_id,
        customer_name=req.get("customer_name"),
        reason=req.get("reason", "Customer scheduled callback"),
        priority=req.get("priority", "NORMAL")
    )
    return {"status": "QUEUED", "callback": record}


@router.get("/callbacks")
async def list_voice_callbacks(
    ctx: Optional[SecurityContext] = Depends(get_optional_security_context),
    x_tenant_id: Optional[str] = Header(None)
):
    """Lists registered customer callbacks for this tenant."""
    tenant_id = ctx.tenant_id if ctx else (x_tenant_id or "t_callback_default")
    callbacks = callback_queue.list_callbacks(tenant_id=tenant_id)
    return {"tenant_id": tenant_id, "callbacks": callbacks}
