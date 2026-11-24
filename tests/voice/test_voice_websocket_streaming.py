"""
WebSocket Streaming Tests for Voice AI Platform.
Full-duplex real-time streaming, VAD chunking, barge-in cancellation,
disclosure enforcement, and caller OTP verification.
Step 10: Complete Customer Voice AI & Manager Voice AI Copilot
(Controls 28, 70; SAI-04, SAI-05)
"""
import uuid
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.backend.models.entities import Base
from src.backend.main import app
from src.backend.core.database import get_db_session
from src.backend.voice.audio_pipeline import SyntheticAudioGenerator
from src.backend.voice.session_tokens import issue_voice_session_token
from src.backend.voice.otp_delivery import register_otp_delivery_adapter


class CapturingOtpDelivery:
    def __init__(self):
        self.sent = {}

    async def deliver(self, tenant_id, recipient, code, session_id):
        self.sent[session_id] = code


def _create_session_via_api(client, tenant_id: str) -> tuple:
    """Voice sessions are created by the authenticated API (never by the socket itself)."""
    from src.backend.core.auth_middleware import get_security_context, SecurityContext

    async def _staff():
        return SecurityContext(user_id="u_ws_staff", tenant_id=tenant_id, email="s@x.test", roles=["support_agent"],
                               permissions=[], mfa_verified=False, jti="jti_ws", correlation_id="corr_ws")
    app.dependency_overrides[get_security_context] = _staff
    resp = client.post("/api/v1/voice/sessions", json={"voice_mode": "CUSTOMER", "channel_type": "WEBSOCKET",
                                                        "caller_identifier": "+212611000000", "language": "fr-FR"})
    assert resp.status_code == 201, resp.text
    app.dependency_overrides.pop(get_security_context)
    return resp.json()["session_id"], resp.json()["session_token"]


def test_voice_websocket_full_lifecycle():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_voice_ws_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    import asyncio
    async def _init_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_init_tables())

    async def _get_test_db():
        async with session_factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db_session] = _get_test_db

    try:
        client = TestClient(app)
        session_id, token = _create_session_via_api(client, "t_ws_01")
        otp_provider = CapturingOtpDelivery()
        register_otp_delivery_adapter(otp_provider)

        # 0. Without the signed session token the socket is refused
        import pytest
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/voice/ws/{session_id}?tenant_id=t_ws_01") as ws:
                ws.receive_json()

        # 1. Connect WebSocket
        with client.websocket_connect(f"/api/v1/voice/ws/{session_id}?token={token}") as ws:
            # 2. Receive initial session initialization with statutory disclosure
            init_frame = ws.receive_json()
            assert init_frame["type"] == "SESSION_INITIALIZED"
            assert init_frame["session_id"] == session_id
            assert "enregistré" in init_frame["disclosure_text"]
            assert init_frame["is_caller_verified"] is False

            # 3. Send text turn
            ws.send_json({
                "type": "TEXT_TURN",
                "text": "Bonjour, quels sont vos serveurs disponibles ?"
            })
            turn_frame = ws.receive_json()
            assert turn_frame["type"] == "TURN_COMPLETED"
            assert turn_frame["turn_index"] == 1
            assert turn_frame["audio_base64"] is not None
            assert "Serveur" in turn_frame["agent_response"] or "disponibles" in turn_frame["agent_response"]

            # 4. Send Barge-in Interruption
            ws.send_json({
                "type": "BARGE_IN",
                "interrupted_turn_index": 1
            })
            barge_frame = ws.receive_json()
            assert barge_frame["type"] == "BARGE_IN_CONFIRMED"
            assert barge_frame["status"] == "PLAYBACK_CANCELLED"

            # 5. Static code is refused; the out-of-band delivered OTP verifies the caller
            ws.send_json({"type": "VERIFY_CALLER", "otp_code": "123456"})
            assert ws.receive_json()["verified"] is False
            ws.send_json({"type": "REQUEST_OTP"})
            assert ws.receive_json()["type"] == "OTP_SENT"
            ws.send_json({
                "type": "VERIFY_CALLER",
                "otp_code": otp_provider.sent[session_id]
            })
            verify_frame = ws.receive_json()
            assert verify_frame["type"] == "CALLER_VERIFIED"
            assert verify_frame["verified"] is True

            # 6. Send Ping / Pong
            ws.send_json({"type": "PING"})
            pong_frame = ws.receive_json()
            assert pong_frame["type"] == "PONG"

    finally:
        app.dependency_overrides.clear()
        register_otp_delivery_adapter(None)
        async def _drop():
            # The in-memory database disappears with its last connection; dropping tables
            # through a pooled connection owned by the TestClient's event loop is not possible.
            await engine.dispose()
        asyncio.run(_drop())


def test_voice_websocket_binary_audio_pcm_streaming():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_voice_ws_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    import asyncio
    async def _init_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_init_tables())

    async def _get_test_db():
        async with session_factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db_session] = _get_test_db

    try:
        client = TestClient(app)
        session_id, token = _create_session_via_api(client, "t_ws_02")

        with client.websocket_connect(f"/api/v1/voice/ws/{session_id}?token={token}") as ws:
            init_frame = ws.receive_json()
            assert init_frame["type"] == "SESSION_INITIALIZED"

            # Generate synthetic active speech audio chunk
            speech_chunk = SyntheticAudioGenerator.generate_speech_like_waveform(duration_ms=300)
            # Send binary PCM frames
            ws.send_bytes(speech_chunk.pcm_bytes)

            # Receive VAD Speech Start
            msg1 = ws.receive_json()
            assert msg1["type"] in ("VAD_SPEECH_START", "TURN_COMPLETED")

    finally:
        app.dependency_overrides.clear()
        register_otp_delivery_adapter(None)
        async def _drop():
            # The in-memory database disappears with its last connection; dropping tables
            # through a pooled connection owned by the TestClient's event loop is not possible.
            await engine.dispose()
        asyncio.run(_drop())
