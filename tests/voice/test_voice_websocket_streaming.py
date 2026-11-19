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
        session_id = f"ws_sess_{uuid.uuid4().hex[:8]}"

        # 1. Connect WebSocket
        with client.websocket_connect(f"/api/v1/voice/ws/{session_id}?tenant_id=t_ws_01") as ws:
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

            # 5. Send Caller Verification Frame (OTP code)
            ws.send_json({
                "type": "VERIFY_CALLER",
                "otp_code": "123456"
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
        async def _drop():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
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
        session_id = f"ws_audio_{uuid.uuid4().hex[:8]}"

        with client.websocket_connect(f"/api/v1/voice/ws/{session_id}?tenant_id=t_ws_02") as ws:
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
        async def _drop():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()
        asyncio.run(_drop())
