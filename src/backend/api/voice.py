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
from src.backend.core.config import settings
from src.backend.core.auth_middleware import security_bearer, get_correlation_id
from src.backend.core.database import bind_tenant_context
from src.backend.core.step_up import verify_user_totp
from src.backend.models.entities import TenantChannelIntegration
from src.backend.voice.service import VoiceSessionService, VoiceSessionNotFoundError
from src.backend.voice.session_tokens import (
    issue_voice_session_token, verify_voice_session_token, VoiceSessionTokenError
)
from src.backend.voice.otp_delivery import OtpDeliveryUnavailableError
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


async def resolve_voice_tenant(
    session_id: str,
    request: Request,
    credentials=Depends(security_bearer),
    correlation_id: str = Depends(get_correlation_id)
) -> str:
    """
    F-01/F-13: the tenant of a voice session is established server-side only:
      * staff/manager callers: verified bearer JWT (any session of their tenant);
      * anonymous customer callers: the signed X-Voice-Session-Token issued when the
        session was created, which must match the session in the path.
    Client-supplied X-Tenant-ID headers are ignored.
    """
    if credentials and credentials.credentials:
        ctx = await get_security_context(request, credentials, correlation_id)
        return ctx.tenant_id
    try:
        claims = verify_voice_session_token(request.headers.get("X-Voice-Session-Token"))
    except VoiceSessionTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    if claims.session_id != session_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Voice session token does not match this session.")
    from src.backend.core.database import current_tenant_id_ctx
    current_tenant_id_ctx.set(claims.tenant_id)
    return claims.tenant_id


@router.post("/sessions", response_model=VoiceSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_voice_session(
    req: VoiceSessionCreateRequest,
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Initializes a customer voice session or authenticated manager voice copilot session.
    Plays mandatory AI & recording disclosure before bi-directional audio.
    F-01: creation requires an authenticated caller (staff, portal or widget backend);
    the response carries a signed session token that anonymous customers use afterwards.
    PSTN calls create sessions through the signature-verified telephony webhook instead.
    """
    tenant_id = ctx.tenant_id

    manager_user_id = ctx.user_id if req.voice_mode.upper() == "MANAGER" else None

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
        created_at=session.created_at,
        session_token=issue_voice_session_token(session.tenant_id, session.session_id)
    )


@router.get("/sessions/{session_id}", response_model=VoiceSessionResponse)
async def get_voice_session(
    session_id: str,
    tenant_id: str = Depends(resolve_voice_tenant),
    db: AsyncSession = Depends(get_db_session)
):

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


@router.post("/sessions/{session_id}/request-otp", status_code=status.HTTP_202_ACCEPTED)
async def request_caller_otp(
    session_id: str,
    tenant_id: str = Depends(resolve_voice_tenant),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Issues a single-use verification code delivered out of band (SMS/WhatsApp) to the
    caller identifier on file (SAI-01/SAI-03). The code is never returned here.
    Fails closed with 503 when no delivery provider is configured.
    """
    service = VoiceSessionService(db)
    try:
        await service.issue_caller_otp(tenant_id, session_id)
    except VoiceSessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OtpDeliveryUnavailableError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except VoiceSecurityError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"status": "OTP_SENT", "session_id": session_id}


@router.post("/sessions/{session_id}/verify-caller", response_model=CustomerVerificationResponse)
async def verify_caller_identity(
    session_id: str,
    req: CustomerVerificationRequest,
    tenant_id: str = Depends(resolve_voice_tenant),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Customer verification via OTP/PIN (Control SAI-01, SAI-03).
    Prevents caller-ID spoofing from disclosing sensitive customer records.
    """

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
    tenant_id: str = Depends(resolve_voice_tenant),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Processes a voice turn with text or streaming audio input.
    Enforces VAD, language identification, tool execution, and audio synthesis.
    """

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
    tenant_id: str = Depends(resolve_voice_tenant),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Signals user interruption (barge-in).
    Cancels in-flight audio synthesis and queues user input turn.
    """

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
    tenant_id: str = Depends(resolve_voice_tenant),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Escalates voice call to a human operator (Control SAI-11).
    """

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
    tenant_id: str = Depends(resolve_voice_tenant),
    db: AsyncSession = Depends(get_db_session)
):

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

    # F-06: spoken high-risk commands always need a FRESH TOTP verified against the
    # manager's enrolled seed (session-level MFA is not enough for the voice channel).
    step_up_ok = await verify_user_totp(db, ctx.tenant_id, ctx.user_id, req.totp_code)
    try:
        action = copilot.action_guard.consume_action(
            req.action_token,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            step_up_verified=step_up_ok
        )
    except VoiceSecurityError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    # No domain executor is wired for voice-initiated actions yet: report the truth
    # (authorized, not executed) instead of claiming execution.
    return ManagerConfirmationResponse(
        action_token=req.action_token,
        executed=False,
        result={"status": "AUTHORIZED_PENDING_EXECUTION", "action_type": action["action_type"]},
        message=(f"Action '{action['action_type']}' authorized with verified step-up MFA. "
                 "It must be executed through the owning domain workflow; voice does not execute it.")
    )


@router.get("/sessions/{session_id}/transcripts", response_model=List[VoiceTranscriptResponse])
async def list_session_transcripts(
    session_id: str,
    tenant_id: str = Depends(resolve_voice_tenant),
    db: AsyncSession = Depends(get_db_session)
):

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
    token: Optional[str] = Query(None, description="Signed voice session token"),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Bi-directional full-duplex real-time voice streaming over WebSocket.
    Processes live audio chunks, continuous VAD turn detection, barge-in cancellation,
    and streams back audio playback frames and transcripts.
    (Controls 28, 70; SAI-04, SAI-05)
    F-13: the connection must present the signed session token issued at session
    creation; the tenant comes from that token. Sessions are never auto-created here,
    and recording consent is whatever was explicitly recorded for the session.
    """
    try:
        claims = verify_voice_session_token(token)
    except VoiceSessionTokenError:
        await websocket.close(code=4401)
        return
    if claims.session_id != session_id:
        await websocket.close(code=4403)
        return
    t_id = claims.tenant_id
    await bind_tenant_context(db, t_id)
    service = VoiceSessionService(db)

    session = await service.get_session(t_id, session_id)
    if not session:
        await websocket.close(code=4404)
        return
    await websocket.accept()

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
                    await bind_tenant_context(db, t_id)
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
                    await bind_tenant_context(db, t_id)
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
                    await bind_tenant_context(db, t_id)
                    await websocket.send_json({
                        "type": "CALLER_VERIFIED",
                        "verified": v_res["verified"],
                        "message": v_res["message"]
                    })

                elif msg_type == "REQUEST_OTP":
                    try:
                        await service.issue_caller_otp(t_id, session_id)
                        await websocket.send_json({"type": "OTP_SENT", "session_id": session_id})
                    except OtpDeliveryUnavailableError:
                        await websocket.send_json({"type": "OTP_UNAVAILABLE", "session_id": session_id})

                elif msg_type == "PING":
                    await websocket.send_json({"type": "PONG", "timestamp": time.time()})

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected cleanly for voice session {session_id}")
    except Exception as e:
        logger.warning(f"Voice WebSocket session {session_id} ended: {e}")


# =============================================================================
# TELEPHONY / SIP INBOUND WEBHOOK & CALLBACK QUEUE ENDPOINTS
# =============================================================================

async def _verify_telephony_request(request: Request, db: AsyncSession) -> tuple:
    """
    F-13: every telephony callback must be signed. The tenant is the owner of the
    called number ('To') registered as a VOICE_SIP integration, and the signature is
    verified with THAT integration's secret. Returns (params, integration).
    """
    body_bytes = await request.body()
    content_type = request.headers.get("content-type", "")
    params: Dict[str, Any] = {}
    if "application/json" in content_type:
        params = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    elif "application/x-www-form-urlencoded" in content_type:
        from urllib.parse import parse_qs
        params = {k: v[0] for k, v in parse_qs(body_bytes.decode("utf-8")).items()}

    signature = request.headers.get("x-twilio-signature") or request.headers.get("x-telephony-signature")
    ts_header = request.headers.get("x-telephony-timestamp")
    called_number = params.get("To") or params.get("called_number")
    if not signature or not ts_header or not called_number:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Signed telephony callback required (signature, timestamp and called number).")

    integration = (await db.execute(select(TenantChannelIntegration).where(and_(
        TenantChannelIntegration.channel_type == "VOICE_SIP",
        TenantChannelIntegration.provider_asset_id == str(called_number),
        TenantChannelIntegration.is_active.is_(True)
    )))).scalars().first()
    secret = integration.webhook_secret if integration else None
    if not integration or not secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown or unconfigured telephony number.")

    try:
        timestamp = float(ts_header)
        valid = telephony_verifier.verify_twilio_signature(
            auth_token=secret,
            webhook_url=str(request.url),
            params=params,
            signature=signature,
            timestamp=timestamp,
            nonce=params.get("CallSid") and f"{params.get('CallSid')}:{request.url.path}:{ts_header}"
        )
    except ReplayAttackDetectedError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid telephony timestamp.")
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid telephony webhook signature.")
    return params, integration


@router.post("/telephony/inbound")
async def telephony_inbound_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Inbound phone call signaling webhook.
    Enforces mandatory signature verification, anti-replay freshness, and call flood rate limits.
    (Control 28, 70; SAI-04, SAI-05)
    """
    params, integration = await _verify_telephony_request(request, db)
    tenant_id = integration.tenant_id
    caller_id = params.get("From") or params.get("caller_id")
    if not caller_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing caller identifier.")

    try:
        call_rate_limiter.acquire_call_slot(caller_id)
    except CallRateLimitExceededError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    await bind_tenant_context(db, tenant_id)
    service = VoiceSessionService(db)
    session = await service.create_session(
        tenant_id=tenant_id,
        voice_mode="CUSTOMER",
        channel_type="SIP",
        caller_identifier=caller_id,
        language="fr-FR",
        recording_consent=False  # off by default until explicit consent is captured (SAI-04)
    )
    await db.commit()

    session_token = issue_voice_session_token(tenant_id, session.session_id)
    disc_text = CustomerVoiceAgent.MANDATORY_DISCLOSURE_TEXT["fr-FR"]
    return {
        "status": "ACCEPTED",
        "session_id": session.session_id,
        "caller_id": caller_id,
        "disclosure_text": disc_text,
        "session_token": session_token,
        "stream_url": f"/api/v1/voice/ws/{session.session_id}?token={session_token}"
    }


@router.post("/telephony/status")
async def telephony_status_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """Releases rate limiter slots on call termination (signed callbacks only)."""
    params, _integration = await _verify_telephony_request(request, db)
    caller_id = params.get("From") or params.get("caller_id")
    if caller_id:
        call_rate_limiter.release_call_slot(caller_id)
    return {"status": "ACKNOWLEDGED"}


@router.post("/callbacks")
async def request_voice_callback(
    req: Dict[str, Any],
    ctx: SecurityContext = Depends(get_security_context)
):
    """Registers customer callback request when operators are unavailable."""
    tenant_id = ctx.tenant_id
    caller_id = req.get("caller_id")
    if not caller_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="caller_id is required.")
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
    ctx: SecurityContext = Depends(get_security_context)
):
    """Lists registered customer callbacks for this tenant."""
    callbacks = callback_queue.list_callbacks(tenant_id=ctx.tenant_id)
    return {"tenant_id": ctx.tenant_id, "callbacks": callbacks}
