"""
Telephony, SIP and WebRTC Transport Gateway Tests.
Twilio & SIP signature validation, anti-replay freshness window, call flood rate limiting,
callback queue operations, ITU-T G.711 mu-law transcoding and telephony API contracts.
Step 10: Complete Customer Voice AI & Manager Voice AI Copilot
(Controls 04, 05, 06, 28, 70; SAI-04, SAI-05)
"""
import pytest
import time
import base64
import hmac
import hashlib
import struct
import uuid
from httpx import AsyncClient, ASGITransport
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.backend.models.entities import Base
from src.backend.main import app
from src.backend.core.database import get_db_session
from src.backend.voice.telephony import (
    G711Codec,
    TelephonySignatureVerifier,
    VoiceCallRateLimiter,
    VoiceCallbackQueue,
    TelephonySecurityError,
    ReplayAttackDetectedError,
    CallRateLimitExceededError
)


@asynccontextmanager
async def setup_telephony_db():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_telephony_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_test_db():
        async with session_factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db_session] = _get_test_db
    yield
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def test_g711_mulaw_codec_and_resampling():
    # 1. Linear 16-bit to mu-law and back
    original_samples = [0, 500, -500, 10000, -10000, 30000, -30000]
    pcm_in = struct.pack(f"<{len(original_samples)}h", *original_samples)

    ulaw = G711Codec.linear16_to_ulaw(pcm_in)
    assert len(ulaw) == len(original_samples)

    pcm_out = G711Codec.ulaw_to_linear16(ulaw)
    decoded_samples = struct.unpack(f"<{len(original_samples)}h", pcm_out)

    # Verify logarithmic quantization within acceptable tolerance
    for orig, dec in zip(original_samples, decoded_samples):
        if orig == 0:
            assert abs(dec) <= 35
        else:
            rel_error = abs(orig - dec) / abs(orig)
            assert rel_error < 0.10

    # 2. Resampling: 8kHz to 16kHz
    pcm_8k = struct.pack("<4h", 100, 200, 300, 400)
    pcm_16k = G711Codec.resample_8k_to_16k(pcm_8k)
    assert len(pcm_16k) == len(pcm_8k) * 2

    # 3. Resampling: 16kHz to 8kHz
    pcm_decimated = G711Codec.resample_16k_to_8k(pcm_16k)
    assert len(pcm_decimated) == len(pcm_8k)


def test_telephony_signature_and_replay_protection():
    verifier = TelephonySignatureVerifier(replay_window_seconds=10.0)
    auth_token = "secret_twilio_token_2026"
    url = "https://salesai.ma/api/v1/voice/telephony/inbound"
    params = {"CallSid": "CA10203040", "From": "+212600112233"}

    # 1. Valid Signature
    data_to_sign = url + "CallSidCA10203040From+212600112233"
    valid_sig = base64.b64encode(
        hmac.new(auth_token.encode(), data_to_sign.encode(), hashlib.sha1).digest()
    ).decode()

    now = time.time()
    assert verifier.verify_twilio_signature(auth_token, url, params, valid_sig, timestamp=now, nonce="nonce_01") is True

    # 2. Tampered Signature Rejected
    assert verifier.verify_twilio_signature(auth_token, url, params, "invalid_sig", timestamp=now, nonce="nonce_02") is False

    # 3. Replay Attack: Expired timestamp (> 10s)
    with pytest.raises(ReplayAttackDetectedError, match="Timestamp delta"):
        verifier.verify_twilio_signature(auth_token, url, params, valid_sig, timestamp=now - 20.0, nonce="nonce_03")

    # 4. Replay Attack: Duplicate nonce
    with pytest.raises(ReplayAttackDetectedError, match="Duplicate nonce"):
        verifier.verify_twilio_signature(auth_token, url, params, valid_sig, timestamp=now, nonce="nonce_01")

    # 5. SIP HMAC-SHA256 signature
    body = b'{"event":"call_started","call_id":"sip_123"}'
    sip_secret = "sip_carrier_secret"
    sip_sig = hmac.new(sip_secret.encode(), body, hashlib.sha256).hexdigest()
    assert verifier.verify_sip_hmac_sha256(sip_secret, body, f"sha256={sip_sig}", timestamp=now) is True


def test_voice_call_flood_rate_limiter():
    limiter = VoiceCallRateLimiter(max_concurrent=2, max_calls_per_minute=3)
    caller = "+212611998877"

    # Acquire slots up to concurrency limit
    limiter.acquire_call_slot(caller)
    limiter.acquire_call_slot(caller)

    # 3rd concurrent call blocked
    with pytest.raises(CallRateLimitExceededError, match="Concurrent call limit exceeded"):
        limiter.acquire_call_slot(caller)

    # Release a slot
    limiter.release_call_slot(caller)
    limiter.acquire_call_slot(caller)
    limiter.release_call_slot(caller)

    # Exceed velocity limit (max 3 calls per minute)
    with pytest.raises(CallRateLimitExceededError, match="Rate limit exceeded"):
        limiter.acquire_call_slot(caller)


def test_voice_callback_queue():
    queue = VoiceCallbackQueue()
    tenant_id = "t_cb_test_01"

    rec1 = queue.enqueue_callback(tenant_id, "+212655443322", customer_name="Société Alpha", reason="Support billing")
    assert rec1["status"] == "QUEUED"
    assert rec1["queue_position"] == 1

    rec2 = queue.enqueue_callback(tenant_id, "+212688776655", customer_name="Société Beta", reason="Devis ERP", priority="HIGH")
    assert rec2["queue_position"] == 2

    # List queued callbacks
    queued = queue.list_callbacks(tenant_id)
    assert len(queued) == 2

    # Complete first callback
    success = queue.complete_callback(tenant_id, rec1["callback_id"])
    assert success is True

    # Only 1 pending callback remains
    pending = queue.list_callbacks(tenant_id, status="QUEUED")
    assert len(pending) == 1
    assert pending[0]["callback_id"] == rec2["callback_id"]


@pytest.mark.asyncio
async def test_telephony_inbound_api_and_callbacks():
    async with setup_telephony_db():
        tenant_id = "t_api_telephony_01"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"X-Tenant-Id": tenant_id}

            # 1. Inbound Webhook
            resp_inbound = await client.post(
                "/api/v1/voice/telephony/inbound",
                headers=headers,
                json={"From": "+212612345678", "CallSid": "CA998877"}
            )
            assert resp_inbound.status_code == 200
            data_inbound = resp_inbound.json()
            assert data_inbound["status"] == "ACCEPTED"
            assert "ws" in data_inbound["stream_url"]
            assert data_inbound["caller_id"] == "+212612345678"

            # 2. Status Webhook
            resp_status = await client.post(
                "/api/v1/voice/telephony/status",
                headers=headers,
                json={"From": "+212612345678", "CallDuration": "45"}
            )
            assert resp_status.status_code == 200
            assert resp_status.json()["status"] == "ACKNOWLEDGED"

            # 3. Request Callback
            resp_cb = await client.post(
                "/api/v1/voice/callbacks",
                headers=headers,
                json={
                    "caller_id": "+212612345678",
                    "customer_name": "Entreprise Maroc Tech",
                    "reason": "Demande de rappel pour devis",
                    "priority": "HIGH"
                }
            )
            assert resp_cb.status_code == 200
            assert resp_cb.json()["status"] == "QUEUED"

            # 4. List Callbacks
            resp_list_cb = await client.get("/api/v1/voice/callbacks", headers=headers)
            assert resp_list_cb.status_code == 200
            assert len(resp_list_cb.json()["callbacks"]) >= 1
