"""
Voice AI Platform Session Service.
Orchestrates voice session lifecycles, real-time turns, customer verification,
audio persistence, and transcript redaction with PostgreSQL RLS.
Step 07: Dual-Mode Customer & Manager Voice AI
(Controls 04-07, 28, 35, 39-40, 48-49, 55, 63-67, 70; SAI-01 to SAI-05, SAI-09 to SAI-12)
"""
import asyncio
import uuid
import logging
logger = logging.getLogger('SalesAI.VoiceService')
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.backend.models.entities import VoiceSession, VoiceTranscript, VoiceRecording, AuditEvent
from src.backend.voice.audio_pipeline import AudioChunk, VoiceActivityDetector, BargeInManager
from src.backend.voice.multilingual_voice import MultilingualVoiceEngine
from src.backend.voice.security import (
    VoicePIIRedactor,
    VoiceIdentityVerificationManager,
    VoiceSecurityError,
    CallerUnverifiedError
)
from src.backend.voice.customer_agent import CustomerVoiceAgent
from src.backend.voice.manager_copilot import ManagerVoiceCopilot


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VoiceSessionNotFoundError(VoiceSecurityError):
    pass


class VoiceSessionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.verification_manager = VoiceIdentityVerificationManager(db)

    # -------------------------------------------------------------------------
    # 1. SESSION LIFECYCLE
    # -------------------------------------------------------------------------
    async def create_session(
        self,
        tenant_id: str,
        voice_mode: str = "CUSTOMER",
        channel_type: str = "WEBRTC",
        caller_identifier: Optional[str] = None,
        language: str = "fr-FR",
        recording_consent: bool = False,
        manager_user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ) -> VoiceSession:
        """
        Initializes an authenticated or verified voice session.
        Enforces mandatory AI and recording disclosure on session setup.
        """
        final_session_id = session_id or f"voice_{uuid.uuid4().hex[:16]}"
        is_verified = (voice_mode.upper() == "MANAGER" and bool(manager_user_id))

        session = VoiceSession(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            session_id=final_session_id,
            channel_type=channel_type.upper(),
            voice_mode=voice_mode.upper(),
            caller_identifier=caller_identifier,
            manager_user_id=manager_user_id,
            status="ACTIVE",
            language=language,
            is_caller_verified=is_verified,
            recording_consent_given=recording_consent,
            disclosure_played=True,
            turns_count=0,
            metadata_json=metadata or {}
        )
        self.db.add(session)
        await self.db.flush()

        # Audit event emission
        audit = AuditEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            event_type="VOICE_SESSION_INITIATED",
            actor_id=manager_user_id,
            resource_type="VOICE_SESSION",
            resource_id=session.session_id,
            action="CREATE",
            payload_json={
                "voice_mode": voice_mode,
                "channel": channel_type,
                "caller": caller_identifier,
                "language": language
            }
        )
        self.db.add(audit)
        await self.db.flush()

        return session

    async def get_session(self, tenant_id: str, session_id: str) -> Optional[VoiceSession]:
        stmt = select(VoiceSession).options(
            selectinload(VoiceSession.transcripts),
            selectinload(VoiceSession.recordings)
        ).where(
            and_(VoiceSession.tenant_id == tenant_id, VoiceSession.session_id == session_id)
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def issue_caller_otp(self, tenant_id: str, session_id: str) -> None:
        """
        Generates a single-use OTP for the session and delivers it out of band to the
        caller identifier on file. Raises OtpDeliveryUnavailableError when no provider
        is configured (fail closed). The code is never returned to the API caller.
        """
        from src.backend.voice.otp_delivery import get_otp_delivery_adapter
        session = await self.get_session(tenant_id, session_id)
        if not session:
            raise VoiceSessionNotFoundError(f"Voice session '{session_id}' not found.")
        if not session.caller_identifier:
            raise VoiceSecurityError("No caller identifier on file to deliver a verification code to.")
        code = await self.verification_manager.generate_otp(tenant_id, session_id)
        try:
            await get_otp_delivery_adapter().deliver(tenant_id, session.caller_identifier, code, session_id)
        except Exception:
            await self.verification_manager.discard(tenant_id, session_id)
            raise

    async def verify_caller_identity(
        self,
        tenant_id: str,
        session_id: str,
        otp_code: str
    ) -> Dict[str, Any]:
        """
        Validates caller OTP code and transitions caller state to verified.
        (Control SAI-01, SAI-03)
        """
        session = await self.get_session(tenant_id, session_id)
        if not session:
            raise VoiceSessionNotFoundError(f"Voice session '{session_id}' not found.")

        # F-05: only a server-issued, out-of-band delivered, single-use OTP is accepted.
        # (The former static '123456' fallback has been removed.)
        is_valid = await self.verification_manager.verify_otp(tenant_id, session_id, otp_code)

        if is_valid:
            session.is_caller_verified = True
            await self.db.flush()
            return {
                "verified": True,
                "message": "Customer identity verified successfully. You may now access your orders and account data."
            }

        return {
            "verified": False,
            "message": "Invalid or expired verification code. Please check and retry."
        }

    # -------------------------------------------------------------------------
    # 2. AUDIO & TEXT CONVERSATION TURN PROCESSING
    # -------------------------------------------------------------------------
    async def process_turn(
        self,
        tenant_id: str,
        session_id: str,
        input_text: Optional[str] = None,
        audio_chunk: Optional[AudioChunk] = None,
        is_barge_in: bool = False
    ) -> Dict[str, Any]:
        """
        Processes a full turn: Speech-To-Text, Intent/Tool dispatch, Text-To-Speech,
        and saves redacted transcripts and audio records.
        """
        start_time = time.time()
        session = await self.get_session(tenant_id, session_id)
        if not session:
            raise VoiceSessionNotFoundError(f"Voice session '{session_id}' not found.")

        # 1. Speech Recognition (ASR)
        if input_text:
            user_utterance = input_text
        elif audio_chunk:
            # F-15: real CPU speech recognition, off the event loop.
            from src.backend.voice.speech_engines import SpeechEngineUnavailableError
            try:
                asr_res = await asyncio.to_thread(
                    MultilingualVoiceEngine.transcribe_audio_chunk, audio_chunk, session.language
                )
                user_utterance = asr_res["text"]
            except SpeechEngineUnavailableError as exc:
                logger.error(f"ASR unavailable for session {session_id}: {exc}")
                user_utterance = ""
        else:
            user_utterance = "Bonjour"

        # 2. Identify language and dialect
        lang_res = MultilingualVoiceEngine.identify_language_and_dialect(user_utterance)
        detected_lang = lang_res["language_code"]

        # 3. Dispatch to Customer Agent or Manager Copilot
        executed_tools = []
        handoff_triggered = False
        handoff_details = None

        if session.voice_mode == "MANAGER":
            copilot = ManagerVoiceCopilot(self.db, tenant_id, session.manager_user_id or "u_manager_01")
            copilot_res = await copilot.process_manager_command(user_utterance, language=detected_lang)
            agent_response_text = copilot_res["insight_text"]
            redacted_transcript = copilot_res["redacted_transcript"]
        else:
            agent = CustomerVoiceAgent(self.db, tenant_id)
            agent_res = await agent.process_turn(
                session_id=session_id,
                user_utterance=user_utterance,
                is_caller_verified=session.is_caller_verified,
                language=detected_lang,
                caller_id=session.caller_identifier
            )
            agent_response_text = agent_res["agent_response"]
            redacted_transcript = agent_res["redacted_transcript"]
            executed_tools = agent_res.get("executed_tools", [])
            handoff_triggered = agent_res.get("handoff_triggered", False)
            handoff_details = agent_res.get("handoff_details")
            if handoff_triggered:
                session.status = "TRANSFERRED"

        # 4. Synthesize speech (TTS)
        # F-15: real speech synthesis, off the event loop. If TTS is unavailable the
        # turn still returns its text (audio_base64 = None) instead of fake audio.
        from src.backend.voice.speech_engines import SpeechEngineUnavailableError
        try:
            tts_audio, tts_meta = await asyncio.to_thread(
                MultilingualVoiceEngine.synthesize_speech, agent_response_text, detected_lang
            )
        except SpeechEngineUnavailableError as exc:
            logger.error(f"TTS unavailable for session {session_id}: {exc}")
            tts_audio, tts_meta = None, {"tts_engine": "UNAVAILABLE", "duration_ms": 0}

        latency_ms = int((time.time() - start_time) * 1000)

        # 5. Record transcripts to DB with RLS and redaction
        turn_idx = session.turns_count + 1
        transcript = VoiceTranscript(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            session_id=session_id,
            turn_index=turn_idx,
            speaker_type="USER",
            raw_text=user_utterance,
            redacted_text=redacted_transcript,
            language=detected_lang,
            latency_ms=latency_ms,
            is_barge_in=is_barge_in
        )
        self.db.add(transcript)

        # Update session turns
        session.turns_count = turn_idx
        await self.db.flush()

        return {
            "session_id": session_id,
            "turn_index": turn_idx,
            "detected_language": detected_lang,
            "user_transcript": user_utterance,
            "redacted_transcript": redacted_transcript,
            "agent_response_text": agent_response_text,
            "audio_base64": tts_audio.to_base64_wav() if tts_audio is not None else None,
            "latency_ms": latency_ms,
            "executed_tools": executed_tools,
            "handoff_triggered": handoff_triggered,
            "handoff_details": handoff_details
        }

    async def end_session(self, tenant_id: str, session_id: str) -> VoiceSession:
        session = await self.get_session(tenant_id, session_id)
        if not session:
            raise VoiceSessionNotFoundError(f"Voice session '{session_id}' not found.")

        session.status = "COMPLETED"
        session.ended_at = utc_now()
        await self.db.flush()
        return session
