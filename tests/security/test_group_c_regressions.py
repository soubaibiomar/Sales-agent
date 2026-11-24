"""
Regression tests for remediation group C of the independent inspection
(F-12, F-13 retention, F-21, F-22, F-29, F-30).
"""
import asyncio
import base64
import hashlib
import hmac
import json
import re
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.backend.main import app
from src.backend.core.database import get_db_session
from src.backend.core.security import SecurityService
from src.backend.models.entities import (
    Base, Tenant, User, VoiceSession, VoiceTranscript, VoiceOtpChallenge, TenantChannelIntegration
)

ROOT = Path(__file__).resolve().parents[2]


def _pg_url(role: str) -> str:
    if role == "app":
        pw = re.search(r"sales_app_user WITH LOGIN PASSWORD '([^']+)'", (ROOT / "infra/init-db.sql").read_text(encoding="utf-8")).group(1)
        return f"postgresql+psycopg://sales_app_user:{pw}@127.0.0.1:5432/sales_ai_db"
    pw = re.search(r"POSTGRES_PASSWORD:-([^}]+)\}", (ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8")).group(1)
    return f"postgresql+psycopg://postgres:{pw}@127.0.0.1:5432/sales_ai_db"


@asynccontextmanager
async def sqlite_app_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    import src.backend.core.database as db_mod
    import src.backend.core.auth_middleware as mw
    orig = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = factory
    mw.AsyncSessionLocal = factory

    async def _db():
        async with factory() as s:
            yield s
            await s.commit()
    app.dependency_overrides[get_db_session] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        db_mod.AsyncSessionLocal = orig
        mw.AsyncSessionLocal = orig
        await engine.dispose()


# ---------------------------------------------------------------- F-21
@pytest.mark.asyncio
async def test_f21_refresh_rotation_and_reuse_detection():
    async with sqlite_app_env() as (client, factory):
        async with factory() as s:
            s.add(Tenant(id="t_rf", name="RF", slug="rf"))
            s.add(User(id="u_rf", tenant_id="t_rf", email="rep@rf.example.com", full_name="Rep",
                       hashed_password=SecurityService.hash_password("Rf-Passw0rd!x"), is_active=True))
            await s.commit()
        login = await client.post("/api/v1/auth/login", json={"email": "rep@rf.example.com", "password": "Rf-Passw0rd!x"})
        assert login.status_code == 200, login.text
        r1 = login.json()["refresh_token"]
        assert (await client.get("/api/v1/voice/callbacks", headers={"Authorization": "Bearer " + r1})).status_code == 401

        rot = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
        assert rot.status_code == 200, rot.text
        a2, r2 = rot.json()["access_token"], rot.json()["refresh_token"]
        assert r2 != r1
        assert (await client.get("/api/v1/voice/callbacks", headers={"Authorization": "Bearer " + a2})).status_code == 200

        # Re-using the rotated token = theft signal: whole session family is revoked
        reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
        assert reuse.status_code == 401
        assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": r2})).status_code == 401
        assert (await client.get("/api/v1/voice/callbacks", headers={"Authorization": "Bearer " + a2})).status_code == 401

        access, _, _ = SecurityService.create_access_token("u_rf", "t_rf", "x", [], [])
        assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": access})).status_code == 401


# ---------------------------------------------------------------- F-29
@pytest.mark.asyncio
async def test_f29_otp_is_hashed_single_use_and_shared_across_workers():
    from src.backend.voice.service import VoiceSessionService
    from src.backend.voice.otp_delivery import register_otp_delivery_adapter

    class Capture:
        sent = {}

        async def deliver(self, tenant_id, recipient, code, session_id):
            self.sent[session_id] = code

    async with sqlite_app_env() as (_, factory):
        async with factory() as s:
            s.add(Tenant(id="t_otp", name="O", slug="o"))
            s.add(VoiceSession(tenant_id="t_otp", session_id="vs_otp", caller_identifier="+212600000077"))
            await s.commit()
        cap = Capture()
        register_otp_delivery_adapter(cap)
        try:
            async with factory() as s:  # "worker 1" issues
                await VoiceSessionService(s).issue_caller_otp("t_otp", "vs_otp")
                await s.commit()
            code = cap.sent["vs_otp"]
            async with factory() as s:
                stored = (await s.execute(select(VoiceOtpChallenge))).scalars().one()
                assert stored.code_hash != code and code not in stored.code_hash
            async with factory() as s:  # "worker 2" verifies
                assert (await VoiceSessionService(s).verify_caller_identity("t_otp", "vs_otp", code))["verified"] is True
                await s.commit()
            async with factory() as s:  # single use
                assert (await VoiceSessionService(s).verify_caller_identity("t_otp", "vs_otp", code))["verified"] is False
        finally:
            register_otp_delivery_adapter(None)


@pytest.mark.asyncio
async def test_f29_telephony_replay_rejected_from_durable_nonce():
    secret, number = "sip-c-" + uuid.uuid4().hex, "+212522000555"
    async with sqlite_app_env() as (client, factory):
        async with factory() as s:
            s.add(Tenant(id="t_tel", name="T", slug="t"))
            s.add(TenantChannelIntegration(tenant_id="t_tel", channel_type="VOICE_SIP", provider_asset_id=number, webhook_secret=secret))
            await s.commit()
        params = {"From": "+212612000001", "To": number, "CallSid": "CA" + uuid.uuid4().hex[:8]}
        url = "http://test/api/v1/voice/telephony/inbound"
        data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
        headers = {"X-Twilio-Signature": base64.b64encode(hmac.new(secret.encode(), data.encode(), hashlib.sha1).digest()).decode(),
                   "X-Telephony-Timestamp": str(time.time())}
        assert (await client.post("/api/v1/voice/telephony/inbound", json=params, headers=headers)).status_code == 200
        assert (await client.post("/api/v1/voice/telephony/inbound", json=params, headers=headers)).status_code == 400


# ---------------------------------------------------------------- F-30
@pytest.mark.asyncio
async def test_f30_integration_secrets_encrypted_at_rest_and_carrier_secret_per_tenant():
    from src.backend.integrations.carriers.simulator import SimulatedExpressCarrierAdapter
    from src.backend.core.config import settings
    async with sqlite_app_env() as (client, factory):
        async with factory() as s:
            s.add(Tenant(id="t_enc", name="E", slug="e"))
            s.add(TenantChannelIntegration(tenant_id="t_enc", channel_type="CARRIER_SIMULATED_EXPRESS",
                                           provider_asset_id="acct", webhook_secret="tenant-own-carrier-secret"))
            await s.commit()
        async with factory() as s:
            raw = (await s.execute(text("SELECT webhook_secret FROM tenant_channel_integrations"))).scalar()
            assert raw.startswith("enc:v1:") and "tenant-own-carrier-secret" not in raw
            orm = (await s.execute(select(TenantChannelIntegration))).scalars().one()
            assert orm.webhook_secret == "tenant-own-carrier-secret"
        body = json.dumps({"tracking_number": "NOPE", "status": "DELIVERED"}).encode()
        # The shared dev fallback no longer works for a tenant that has its own secret
        sig = SimulatedExpressCarrierAdapter.compute_webhook_signature(body, settings.carrier_webhook_secret)
        r = await client.post("/api/v1/logistics/webhooks/carrier/SIMULATED_EXPRESS", content=body,
                              headers={"X-Tenant-Id": "t_enc", "X-Carrier-Signature": sig, "Content-Type": "application/json"})
        assert r.status_code == 401


# ---------------------------------------------------------------- F-13 retention
@pytest.mark.asyncio
async def test_f13_worker_applies_retention():
    from src.backend.worker import PlatformWorker
    async with sqlite_app_env() as (_, factory):
        old = datetime.now(timezone.utc) - timedelta(days=400)
        async with factory() as s:
            s.add(Tenant(id="t_ret", name="R", slug="r"))
            s.add(VoiceSession(tenant_id="t_ret", session_id="vs_ret"))
            s.add(VoiceTranscript(tenant_id="t_ret", session_id="vs_ret", speaker_type="USER", raw_text="old", redacted_text="old", created_at=old))
            s.add(VoiceTranscript(tenant_id="t_ret", session_id="vs_ret", speaker_type="USER", raw_text="new", redacted_text="new"))
            s.add(VoiceOtpChallenge(tenant_id="t_ret", session_id="vs_ret", code_hash="x" * 64,
                                    expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
            await s.commit()
        totals = await PlatformWorker(session_factory=factory, dispatcher=None).run_cycle()
        assert totals["errors"] == 0 and totals["retention_purged"] == 2
        async with factory() as s:
            texts = [t.raw_text for t in (await s.execute(select(VoiceTranscript))).scalars().all()]
            assert texts == ["new"]


# ---------------------------------------------------------------- F-22
def test_f22_no_database_dumps_tracked():
    tracked = subprocess.run(["git", "ls-files", "*.dump", "*.backup"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    assert tracked == ""
    assert "*.dump" in (ROOT / ".gitignore").read_text(encoding="utf-8")


# ---------------------------------------------------------------- F-12 (real PostgreSQL)
def test_f12_least_privilege_and_tamper_evident_audit():
    asyncio.run(_f12_body(), loop_factory=asyncio.SelectorEventLoop)


async def _f12_body():
    app_eng, su = create_async_engine(_pg_url("app")), create_async_engine(_pg_url("su"))
    try:
        async with app_eng.connect() as c:
            await c.execute(text("SELECT 1"))
    except Exception:
        await app_eng.dispose(); await su.dispose()
        pytest.skip("Local PostgreSQL not reachable")
    ta, tb = "t_f12_" + uuid.uuid4().hex[:6], "t_f12_" + uuid.uuid4().hex[:6]
    try:
        async with su.begin() as c:
            await c.execute(text("INSERT INTO tenants(id,name,slug) VALUES (:a,:a,:a),(:b,:b,:b)"), {"a": ta, "b": tb})
        # App role can no longer destroy another tenant (cascade bypasses RLS) or alter catalogs
        for stmt in (f"DELETE FROM tenants WHERE id='{tb}'", f"UPDATE tenants SET name='x' WHERE id='{tb}'",
                     "INSERT INTO roles(id,name) VALUES ('r_x','x')"):
            with pytest.raises(Exception, match="permission denied"):
                async with app_eng.begin() as c:
                    await c.execute(text(stmt))
        # Audit chain written by the app role
        async with app_eng.begin() as c:
            await c.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": ta})
            for i in range(3):
                await c.execute(text("INSERT INTO audit_logs(id,tenant_id,event_type,resource_type,action) "
                                     "VALUES (:i,:t,'E','R','A')"), {"i": str(uuid.uuid4()), "t": ta})
            rows = (await c.execute(text("SELECT prev_hash, entry_hash FROM audit_logs WHERE tenant_id=:t ORDER BY chain_seq"), {"t": ta})).all()
            assert rows[0][0] is None and rows[1][0] == rows[0][1] and rows[2][0] == rows[1][1]
            assert tuple((await c.execute(text("SELECT entries_checked, is_intact FROM audit_verify_chain()"))).one()) == (3, True)
            with pytest.raises(Exception, match="permission denied|append-only"):
                async with c.begin_nested():
                    await c.execute(text("UPDATE audit_logs SET action='X' WHERE tenant_id=:t"), {"t": ta})
        # A tampered row (forced by a superuser bypassing the trigger) is detected; rolled back
        async with su.connect() as c:
            tx = await c.begin()
            await c.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_logs_immutable"))
            await c.execute(text("UPDATE audit_logs SET action='TAMPERED' WHERE tenant_id=:t AND prev_hash IS NOT NULL"), {"t": ta})
            await c.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": ta})
            res = (await c.execute(text("SELECT is_intact FROM audit_verify_chain()"))).scalar()
            await tx.rollback()
            assert res is False
    finally:
        async with su.begin() as c:
            await c.execute(text("DELETE FROM tenants WHERE id IN (:a,:b)"), {"a": ta, "b": tb})
        await app_eng.dispose(); await su.dispose()
