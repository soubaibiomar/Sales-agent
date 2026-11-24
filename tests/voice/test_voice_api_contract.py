"""
Contract and API Route Tests for Voice AI Platform.
Step 07: Dual-Mode Customer & Manager Voice AI
(Controls 04-07, 28, 35, 39-40, 48-49, 55, 63-67, 70; SAI-01 to SAI-05, SAI-09 to SAI-12)
"""
import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.backend.models.entities import Base
from src.backend.main import app
from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext
from src.backend.voice.audio_pipeline import SyntheticAudioGenerator
from src.backend.voice.otp_delivery import register_otp_delivery_adapter
from src.backend.core.security import SecurityService
from src.backend.models.entities import User, Tenant

MANAGER_TOTP_SEED = SecurityService.generate_totp_secret()


class CapturingOtpDelivery:
    """Test double for the SMS/WhatsApp OTP provider: records the code it would send."""
    def __init__(self):
        self.sent = {}

    async def deliver(self, tenant_id, recipient, code, session_id):
        self.sent[session_id] = code


@asynccontextmanager
async def override_voice_api_dependencies():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_voice_api_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_test_db():
        async with session_factory() as session:
            yield session
            await session.commit()

    async with session_factory() as session:
        session.add(Tenant(id="t_api_voice_mgr", name="Voice Mgr Tenant", slug="voice-mgr-tenant"))
        session.add(User(
            id="u_manager_api", tenant_id="t_api_voice_mgr", email="manager@example.com",
            hashed_password="x", full_name="Manager", is_active=True, mfa_enabled=True,
            mfa_secret=SecurityService.encrypt_mfa_secret(MANAGER_TOTP_SEED)
        ))
        await session.commit()

    app.dependency_overrides[get_db_session] = _get_test_db
    yield
    app.dependency_overrides.clear()
    register_otp_delivery_adapter(None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_full_customer_voice_api_lifecycle():
    async with override_voice_api_dependencies():
        tenant_id = "t_api_voice_01"
        staff_ctx = SecurityContext(
            user_id="u_agent_api", tenant_id=tenant_id, email="agent@example.com",
            roles=["support_agent"], permissions=[], mfa_verified=False,
            jti="jti_agent", correlation_id="corr_agent"
        )

        async def _staff_sec():
            return staff_ctx

        # Session creation requires an authenticated caller (portal/widget backend);
        # all later customer calls use only the signed session token it returns.
        app.dependency_overrides[get_security_context] = _staff_sec
        otp_provider = CapturingOtpDelivery()
        register_otp_delivery_adapter(otp_provider)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Create Voice Session
            resp_create = await client.post(
                "/api/v1/voice/sessions",
                json={
                    "voice_mode": "CUSTOMER",
                    "channel_type": "WEBRTC",
                    "caller_identifier": "+212611223344",
                    "language": "fr-FR",
                    "recording_consent": True
                }
            )
            assert resp_create.status_code == 201
            data_create = resp_create.json()
            session_id = data_create["session_id"]
            assert data_create["disclosure_played"] is True
            assert "enregistré" in data_create["disclosure_text"]
            assert data_create["is_caller_verified"] is False
            assert data_create["session_token"]
            headers = {"X-Voice-Session-Token": data_create["session_token"]}

            # 2. Execute Public Voice Turn (Text input)
            resp_turn1 = await client.post(
                f"/api/v1/voice/sessions/{session_id}/turn",
                headers=headers,
                json={"input_text": "Bonjour, quels sont vos produits informatiques ?"}
            )
            assert resp_turn1.status_code == 200
            data_turn1 = resp_turn1.json()
            assert data_turn1["turn_index"] == 1
            assert data_turn1["audio_base64"] is not None
            assert len(data_turn1["executed_tools"]) > 0

            # 3. Sensitive Order Inquiry before verification requests OTP
            resp_turn2 = await client.post(
                f"/api/v1/voice/sessions/{session_id}/turn",
                headers=headers,
                json={"input_text": "Donne-moi l'état de ma commande ORD-12345"}
            )
            assert resp_turn2.status_code == 200
            data_turn2 = resp_turn2.json()
            assert "vérification de sécurité" in data_turn2["agent_response_text"]

            # 4. Caller Identity Verification with an out-of-band delivered OTP
            resp_static = await client.post(
                f"/api/v1/voice/sessions/{session_id}/verify-caller",
                headers=headers,
                json={"otp_code": "123456"}
            )
            assert resp_static.json()["verified"] is False  # no static/demo code is accepted
            resp_req = await client.post(f"/api/v1/voice/sessions/{session_id}/request-otp", headers=headers)
            assert resp_req.status_code == 202
            assert "otp" not in resp_req.text.lower().replace("otp_sent", "")
            resp_verify = await client.post(
                f"/api/v1/voice/sessions/{session_id}/verify-caller",
                headers=headers,
                json={"otp_code": otp_provider.sent[session_id]}
            )
            assert resp_verify.status_code == 200
            assert resp_verify.json()["verified"] is True

            # 5. Audio-driven Voice Turn with base64 WAV
            chunk = SyntheticAudioGenerator.generate_speech_like_waveform(duration_ms=600)
            resp_turn_audio = await client.post(
                f"/api/v1/voice/sessions/{session_id}/turn",
                headers=headers,
                json={"audio_base64": chunk.to_base64_wav()}
            )
            assert resp_turn_audio.status_code == 200
            assert resp_turn_audio.json()["turn_index"] == 3

            # 6. Signal Barge-in
            resp_barge = await client.post(
                f"/api/v1/voice/sessions/{session_id}/barge-in",
                headers=headers,
                json={
                    "session_id": session_id,
                    "interrupted_turn_index": 3,
                    "energy_level": 750.0,
                    "timestamp_ms": 1700000000000
                }
            )
            assert resp_barge.status_code == 200
            assert resp_barge.json()["status"] == "BARGE_IN_PROCESSED"

            # 7. Human Handoff Escalation
            resp_handoff = await client.post(
                f"/api/v1/voice/sessions/{session_id}/handoff",
                headers=headers,
                json={"reason": "Customer requests live human agent", "target_department": "SUPPORT"}
            )
            assert resp_handoff.status_code == 200
            assert resp_handoff.json()["handoff_status"] == "TRANSFERRED"

            # 8. List Session Transcripts
            resp_transcripts = await client.get(
                f"/api/v1/voice/sessions/{session_id}/transcripts",
                headers=headers
            )
            assert resp_transcripts.status_code == 200
            transcripts = resp_transcripts.json()
            assert len(transcripts) >= 3

            # 9. Conclude Voice Session
            resp_end = await client.post(
                f"/api/v1/voice/sessions/{session_id}/end",
                headers=headers,
                json={"reason": "COMPLETED"}
            )
            assert resp_end.status_code == 200
            assert resp_end.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_manager_copilot_api_and_step_up_mfa_flow():
    async with override_voice_api_dependencies():
        tenant_id = "t_api_voice_mgr"
        manager_ctx = SecurityContext(
            user_id="u_manager_api",
            tenant_id=tenant_id,
            email="manager@example.com",
            roles=["sales_manager"],
            permissions=["voice:copilot", "quotes:approve"],
            mfa_verified=True,
            jti="jti_manager_test",
            correlation_id="corr_test_01"
        )

        async def _mock_manager_sec():
            return manager_ctx

        app.dependency_overrides[get_security_context] = _mock_manager_sec

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {}

            # 1. Safe query: sales insight
            resp_sales = await client.post(
                "/api/v1/voice/copilot/command",
                headers=headers,
                json={"command_text": "Quels sont les chiffres de vente ?"}
            )
            assert resp_sales.status_code == 200
            data_sales = resp_sales.json()
            assert data_sales["requires_confirmation"] is False

            # 2. High-risk command: approve purchase order requires confirmation
            resp_cmd = await client.post(
                "/api/v1/voice/copilot/command",
                headers=headers,
                json={"command_text": "Approuve le bon de commande fournisseur 888"}
            )
            assert resp_cmd.status_code == 200
            data_cmd = resp_cmd.json()
            assert data_cmd["requires_confirmation"] is True
            assert data_cmd["action_preview"] is not None
            token = data_cmd["action_preview"]["action_token"]

            # 3. A well-formed but wrong code is rejected (no format-only checks)
            wrong_code = "000000" if SecurityService.generate_totp_code(MANAGER_TOTP_SEED) != "000000" else "111111"
            resp_bad = await client.post(
                "/api/v1/voice/copilot/confirm-action",
                headers=headers,
                json={"action_token": token, "totp_code": wrong_code, "confirmed": True}
            )
            assert resp_bad.status_code == 403

            # 4. Confirm with a TOTP that verifies against the manager's enrolled seed
            resp_confirm = await client.post(
                "/api/v1/voice/copilot/confirm-action",
                headers=headers,
                json={"action_token": token, "totp_code": SecurityService.generate_totp_code(MANAGER_TOTP_SEED), "confirmed": True}
            )
            assert resp_confirm.status_code == 200
            # Voice authorizes; it never executes the high-risk action itself.
            assert resp_confirm.json()["executed"] is False
            assert "authorized with verified step-up MFA" in resp_confirm.json()["message"]
