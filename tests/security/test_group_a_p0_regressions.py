"""
Regression tests for the P0 defects found by the independent inspection
(reports/claude-inspection/findings_register.csv, remediation group A).

Each test reproduces the original exploit and asserts it is now rejected,
plus a positive case proving the legitimate path still works.
"""
import hashlib
import hmac
import json
import time
import uuid
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from src.backend.main import app
from src.backend.core.database import get_db_session
from src.backend.core.security import SecurityService
from src.backend.core.config import settings, Settings
from src.backend.models.entities import (
    Base, Tenant, User, SalesOrder, PaymentIntent, TenantChannelIntegration, VoiceSession,
    Product, InventoryItem, Warehouse
)
from src.backend.voice.session_tokens import issue_voice_session_token
from src.backend.voice.otp_delivery import register_otp_delivery_adapter
from src.backend.voice.security import ManagerPrivilegedActionGuard

TA, TB = "t_p0_A", "t_p0_B"
MGR_A, REP_A, MGR2_A, MGR_B = "u_mgr_a", "u_rep_a", "u_mgr2_a", "u_mgr_b"
TENANT_A_PAYMENT_SECRET = "tenant-a-provider-secret-" + uuid.uuid4().hex
SIP_SECRET = "tenant-a-sip-secret-" + uuid.uuid4().hex
SIP_NUMBER = "+212522000111"
MGR_TOTP_SEED = SecurityService.generate_totp_secret()


def bearer(user, tenant, roles=("sales_manager",), perms=(), mfa=False):
    tok, _, _ = SecurityService.create_access_token(user, tenant, f"{user}@x.test", list(roles), list(perms), mfa_verified=mfa)
    return {"Authorization": f"Bearer {tok}"}


@asynccontextmanager
async def p0_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False},
                                 poolclass=StaticPool, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        s.add_all([Tenant(id=TA, name="A", slug="p0-a"), Tenant(id=TB, name="B", slug="p0-b")])
        for uid, tid in ((MGR_A, TA), (REP_A, TA), (MGR2_A, TA), (MGR_B, TB)):
            s.add(User(id=uid, tenant_id=tid, email=f"{uid}@x.test", hashed_password="x", full_name=uid,
                       is_active=True, mfa_enabled=uid != REP_A,
                       mfa_secret=SecurityService.encrypt_mfa_secret(MGR_TOTP_SEED) if uid != REP_A else None))
        s.add(SalesOrder(id="so_a", tenant_id=TA, order_number="SO-P0-1", terms_hash="h",
                         grand_total_cents=100000, currency="MAD", payment_status="PAID", status="CONFIRMED"))
        s.add(SalesOrder(id="so_a2", tenant_id=TA, order_number="SO-P0-2", terms_hash="h",
                         grand_total_cents=50000, currency="MAD"))
        s.add(PaymentIntent(tenant_id=TA, order_id="so_a2", provider="STRIPE_SANDBOX",
                            provider_intent_id="pi_p0", amount_cents=50000, currency="MAD"))
        s.add(TenantChannelIntegration(tenant_id=TA, channel_type="PAYMENT_STRIPE_SANDBOX",
                                       provider_asset_id="acct_a", webhook_secret=TENANT_A_PAYMENT_SECRET))
        s.add(TenantChannelIntegration(tenant_id=TA, channel_type="VOICE_SIP",
                                       provider_asset_id=SIP_NUMBER, webhook_secret=SIP_SECRET))
        s.add(VoiceSession(tenant_id=TB, session_id="vs_b", caller_identifier="+212600000002"))
        s.add(Warehouse(id="wh_a", tenant_id=TA, name="Main", code="WH-A"))
        s.add(Product(id="p_a", tenant_id=TA, sku="SKU-REAL-1", name="Real Product", base_price_cents=125000))
        s.add(InventoryItem(id="ii_a", tenant_id=TA, warehouse_id="wh_a", product_id="p_a", sku="SKU-REAL-1",
                            on_hand_quantity=7, reserved_quantity=2, allocated_quantity=0))
        await s.commit()

    import src.backend.core.database as db_mod
    import src.backend.core.auth_middleware as mw
    orig = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = factory
    mw.AsyncSessionLocal = factory

    async def _db():
        async with factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db_session] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        db_mod.AsyncSessionLocal = orig
        mw.AsyncSessionLocal = orig
        register_otp_delivery_adapter(None)
        await engine.dispose()


# ---------------------------------------------------------------- F-01
@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [
    ("get", "/api/v1/notifications/history"),
    ("post", "/api/v1/notifications/send"),
    ("get", "/api/v1/workflows/executions"),
    ("post", "/api/v1/workflows/recovery/resume"),
    ("get", "/api/v1/integrations/status"),
    ("get", "/api/v1/integrations/outbox/dlq"),
    ("post", "/api/v1/integrations/n8n/verify-barrier"),
    ("get", "/api/v1/voice/callbacks"),
    ("get", "/api/v1/voice/sessions/vs_b"),
    ("get", "/api/v1/voice/sessions/vs_b/transcripts"),
])
async def test_f01_client_tenant_header_never_authenticates(method, path):
    async with p0_env() as (client, _):
        resp = await getattr(client, method)(path, headers={"X-Tenant-ID": TB},
                                             **({"json": {}} if method == "post" else {}))
        assert resp.status_code in (401, 403), f"{path} -> {resp.status_code}"


@pytest.mark.asyncio
async def test_f01_permissions_required_on_operator_apis():
    async with p0_env() as (client, _):
        rep = bearer(REP_A, TA, roles=("sales_rep",))
        assert (await client.get("/api/v1/workflows/executions", headers=rep)).status_code == 403
        ok = bearer(MGR_A, TA, perms=("workflows:read",))
        assert (await client.get("/api/v1/workflows/executions", headers=ok)).status_code == 200


@pytest.mark.asyncio
async def test_f21_refresh_token_rejected_as_access_token():
    async with p0_env() as (client, _):
        rt, _, _ = SecurityService.create_refresh_token(MGR_A, TA)
        resp = await client.get("/api/v1/voice/callbacks", headers={"Authorization": f"Bearer {rt}"})
        assert resp.status_code == 401


# ---------------------------------------------------------------- F-02
def _signed_webhook(secret, body, ts=None):
    ts = int(time.time()) if ts is None else ts
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return {"X-Signature-SHA256": sig, "X-Signature-Timestamp": str(ts), "Content-Type": "application/json"}


def _event(amount=50000, currency="MAD"):
    return json.dumps({"id": "evt_" + uuid.uuid4().hex[:10], "type": "payment_intent.succeeded",
                       "data": {"object": {"id": "pi_p0", "amount": amount, "currency": currency}},
                       "provider_intent_id": "pi_p0"})


@pytest.mark.asyncio
async def test_f02_forged_payment_webhooks_rejected_and_genuine_accepted():
    async with p0_env() as (client, factory):
        url = f"/api/v1/payments/webhook?tenant_id={TA}&provider=STRIPE_SANDBOX"
        body = _event()
        # Old exploit: shared/global secret (here the dev fallback) no longer works for a tenant with its own secret.
        r = await client.post(url, content=body, headers=_signed_webhook(settings.payment_webhook_secret, body))
        assert r.status_code == 403
        # Unsigned timestamp / legacy body-only signature
        legacy = hmac.new(TENANT_A_PAYMENT_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        r = await client.post(url, content=body, headers={"X-Signature-SHA256": legacy, "Content-Type": "application/json"})
        assert r.status_code == 401
        # Stale (replayed) delivery
        r = await client.post(url, content=body, headers=_signed_webhook(TENANT_A_PAYMENT_SECRET, body, ts=int(time.time()) - 3600))
        assert r.status_code == 403
        # Wrong amount
        bad = _event(amount=1)
        r = await client.post(url, content=bad, headers=_signed_webhook(TENANT_A_PAYMENT_SECRET, bad))
        assert r.status_code == 400
        async with factory() as s:
            assert (await s.get(SalesOrder, "so_a2")).payment_status != "PAID"
        # Genuine event
        r = await client.post(url, content=body, headers=_signed_webhook(TENANT_A_PAYMENT_SECRET, body))
        assert r.status_code == 200, r.text
        async with factory() as s:
            assert (await s.get(SalesOrder, "so_a2")).payment_status == "PAID"


# ---------------------------------------------------------------- F-03
@pytest.mark.asyncio
async def test_f03_refund_mfa_cumulative_cap_idempotency_and_four_eyes():
    async with p0_env() as (client, _):
        requester = bearer(MGR_A, TA, perms=("orders:manage",))
        approver = bearer(MGR2_A, TA, perms=("orders:manage",))
        r1 = await client.post("/api/v1/payments/refunds", headers=requester,
                               json={"order_id": "so_a", "amount_cents": 60000, "reason": "r", "idempotency_key": "rk-1"})
        assert r1.status_code == 201
        replay = await client.post("/api/v1/payments/refunds", headers=requester,
                                   json={"order_id": "so_a", "amount_cents": 60000, "reason": "r", "idempotency_key": "rk-1"})
        assert replay.json()["id"] == r1.json()["id"]
        over = await client.post("/api/v1/payments/refunds", headers=requester,
                                 json={"order_id": "so_a", "amount_cents": 60000, "reason": "r", "idempotency_key": "rk-2"})
        assert over.status_code == 422  # 60000 + 60000 > 100000
        rid = r1.json()["id"]
        # Client-asserted MFA is ignored
        r = await client.post(f"/api/v1/payments/refunds/{rid}/approve?mfa_verified=true",
                              headers={**approver, "X-MFA-Verified": "true"})
        assert r.status_code == 403
        # Wrong TOTP
        r = await client.post(f"/api/v1/payments/refunds/{rid}/approve", headers=approver, json={"mfa_code": "000000"})
        assert r.status_code == 403
        # Requester cannot approve own refund even with valid TOTP
        code = SecurityService.generate_totp_code(MGR_TOTP_SEED)
        r = await client.post(f"/api/v1/payments/refunds/{rid}/approve", headers=requester, json={"mfa_code": code})
        assert r.status_code == 403
        # Second person with valid TOTP succeeds; partial refund does not mark order fully refunded
        r = await client.post(f"/api/v1/payments/refunds/{rid}/approve", headers=approver, json={"mfa_code": code})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "COMPLETED"


# ---------------------------------------------------------------- F-04 / F-06 helper
@pytest.mark.asyncio
async def test_f04_step_up_requires_real_totp():
    from src.backend.core.step_up import is_step_up_satisfied
    from src.backend.core.auth_middleware import SecurityContext
    async with p0_env() as (_, factory):
        ctx = SecurityContext(user_id=MGR_A, tenant_id=TA, email="", roles=["sales_manager"], permissions=[],
                              mfa_verified=False, jti="j", correlation_id="c")
        async with factory() as s:
            assert await is_step_up_satisfied(s, ctx, "any-non-empty-code") is False
            assert await is_step_up_satisfied(s, ctx, "123456") is False or SecurityService.generate_totp_code(MGR_TOTP_SEED) == "123456"
            assert await is_step_up_satisfied(s, ctx, SecurityService.generate_totp_code(MGR_TOTP_SEED)) is True


# ---------------------------------------------------------------- F-05
class CapturingOtp:
    def __init__(self):
        self.sent = {}

    async def deliver(self, tenant_id, recipient, code, session_id):
        self.sent[session_id] = code


@pytest.mark.asyncio
async def test_f05_static_otp_rejected_and_delivered_otp_accepted():
    async with p0_env() as (client, _):
        create = await client.post("/api/v1/voice/sessions", headers=bearer(MGR_A, TA),
                                   json={"voice_mode": "CUSTOMER", "caller_identifier": "+212611111111"})
        assert create.status_code == 201
        sid, tok = create.json()["session_id"], create.json()["session_token"]
        h = {"X-Voice-Session-Token": tok}
        r = await client.post(f"/api/v1/voice/sessions/{sid}/verify-caller", headers=h, json={"otp_code": "123456"})
        assert r.json()["verified"] is False
        # No delivery provider configured -> fail closed
        assert (await client.post(f"/api/v1/voice/sessions/{sid}/request-otp", headers=h)).status_code == 503
        cap = CapturingOtp()
        register_otp_delivery_adapter(cap)
        assert (await client.post(f"/api/v1/voice/sessions/{sid}/request-otp", headers=h)).status_code == 202
        r = await client.post(f"/api/v1/voice/sessions/{sid}/verify-caller", headers=h, json={"otp_code": cap.sent[sid]})
        assert r.json()["verified"] is True
        # A token for one session cannot drive another tenant's session
        assert (await client.get("/api/v1/voice/sessions/vs_b", headers=h)).status_code == 403
        forged = issue_voice_session_token(TB, "vs_b", secret="attacker-guess-secret-attacker-guess")
        assert (await client.get("/api/v1/voice/sessions/vs_b", headers={"X-Voice-Session-Token": forged})).status_code == 401


# ---------------------------------------------------------------- F-06
@pytest.mark.asyncio
async def test_f06_manager_action_needs_real_totp_and_same_user():
    async with p0_env() as (client, _):
        mgr = bearer(MGR_A, TA, perms=("voice:copilot",))
        cmd = await client.post("/api/v1/voice/copilot/command", headers=mgr,
                                json={"command_text": "Approuve le bon de commande fournisseur 888"})
        token = cmd.json()["action_preview"]["action_token"]
        assert (await client.post("/api/v1/voice/copilot/confirm-action", headers=mgr,
                                  json={"action_token": token, "totp_code": "abcdef"})).status_code == 403
        other = bearer(MGR_B, TB, perms=("voice:copilot",))
        code = SecurityService.generate_totp_code(MGR_TOTP_SEED)
        assert (await client.post("/api/v1/voice/copilot/confirm-action", headers=other,
                                  json={"action_token": token, "totp_code": code})).status_code == 403
        ok = await client.post("/api/v1/voice/copilot/confirm-action", headers=mgr,
                               json={"action_token": token, "totp_code": code})
        assert ok.status_code == 200
        assert ok.json()["executed"] is False  # voice never executes; it only authorizes
        assert ok.json()["result"]["status"] == "AUTHORIZED_PENDING_EXECUTION"


@pytest.mark.asyncio
async def test_f06_guard_unit_binding():
    from src.backend.voice.security import VoiceSecurityError
    async with p0_env() as (_, factory):
        async with factory() as s:
            guard = ManagerPrivilegedActionGuard(s)
            prev = await guard.create_action_preview(TA, MGR_A, "APPROVE_PO", {}, "s")
            with pytest.raises(VoiceSecurityError):
                await guard.consume_action(prev["action_token"], tenant_id=TA, user_id=MGR_A, step_up_verified=False)
            with pytest.raises(VoiceSecurityError):
                await guard.consume_action(prev["action_token"], tenant_id=TB, user_id=MGR_B, step_up_verified=True)
            ok = await guard.consume_action(prev["action_token"], tenant_id=TA, user_id=MGR_A, step_up_verified=True)
            assert ok["action_type"] == "APPROVE_PO"
            # Single use
            with pytest.raises(VoiceSecurityError):
                await guard.consume_action(prev["action_token"], tenant_id=TA, user_id=MGR_A, step_up_verified=True)


# ---------------------------------------------------------------- F-13 telephony / websocket
@pytest.mark.asyncio
async def test_f13_telephony_requires_signature_and_derives_tenant():
    from src.backend.voice.telephony import TelephonySignatureVerifier
    import base64
    async with p0_env() as (client, _):
        params = {"From": "+212612345678", "To": SIP_NUMBER, "CallSid": "CA" + uuid.uuid4().hex[:8]}
        r = await client.post("/api/v1/voice/telephony/inbound", headers={"X-Tenant-Id": TB}, json=params)
        assert r.status_code == 401
        url = "http://test/api/v1/voice/telephony/inbound"
        data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
        sig = base64.b64encode(hmac.new(SIP_SECRET.encode(), data.encode(), hashlib.sha1).digest()).decode()
        r = await client.post("/api/v1/voice/telephony/inbound", json=params,
                              headers={"X-Twilio-Signature": sig, "X-Telephony-Timestamp": str(time.time())})
        assert r.status_code == 200, r.text
        assert "token=" in r.json()["stream_url"]


def test_f13_websocket_requires_session_token():
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    with TestClient(app) as tc:
        with pytest.raises(WebSocketDisconnect):
            with tc.websocket_connect("/api/v1/voice/ws/vs_b?tenant_id=" + TB) as ws:
                ws.receive_json()


# ---------------------------------------------------------------- F-07 / F-08
@pytest.mark.asyncio
async def test_f07_tools_answer_from_domain_data_only():
    from src.ai.tool_gateway import ToolGateway, ServerSecurityContext, DomainServiceRejectedError
    async with p0_env() as (_, factory):
        gw = ToolGateway()
        ctx = ServerSecurityContext(tenant_id=TA, user_id=REP_A, role="order_payment")
        async with factory() as s:
            with pytest.raises(DomainServiceRejectedError):
                await gw.execute_tool("orders.get_status", {"order_id": "DOES-NOT-EXIST"}, ctx, s)
            res = await gw.execute_tool("orders.get_status", {"order_id": "SO-P0-1"}, ctx, s)
            assert res["payment_status"] == "PAID" and res["total_cents"] == 100000
            atp = await gw.execute_tool("inventory.check_atp", {"sku": "SKU-REAL-1"}, ctx, s)
            assert atp["available_units"] == 5
        with pytest.raises(DomainServiceRejectedError):
            await gw.execute_tool("orders.get_status", {"order_id": "SO-P0-1"}, ctx, None)


def test_f08_guard_fails_closed():
    from src.ai.output_guard import OutputGuard, EvidenceEnvelope
    assert OutputGuard.inspect_and_guard("Votre commande est payée, prix 999 MAD, remise de 40%.", evidence=None).is_safe is False
    env = EvidenceEnvelope(verified_prices={"SKU": 1250.0})
    assert OutputGuard.inspect_and_guard("Le prix est de MAD 999.", evidence=env).is_safe is False
    assert OutputGuard.inspect_and_guard("Prix: 999 dirhams.", evidence=env).is_safe is False
    assert OutputGuard.inspect_and_guard("Il reste 10 en stock.", evidence=None).is_safe is False
    assert OutputGuard.inspect_and_guard("Le prix est de 1 250,00 MAD.", evidence=env).is_safe is True
    assert OutputGuard.inspect_and_guard("Bonjour, comment puis-je vous aider ?", evidence=None).is_safe is True


# ---------------------------------------------------------------- F-10
def test_f10_insecure_defaults_refused_outside_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(Exception, match="insecure default"):
        Settings(_env_file=None)


def test_f10_development_still_boots(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert Settings(_env_file=None).is_development


# ---------------------------------------------------------------- F-09 (real PostgreSQL)
def _dev_pg_url(role: str) -> str:
    """Builds local dev URLs from the repository's own dev bootstrap files (no new secrets)."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    if role == "app":
        pw = re.search(r"sales_app_user WITH LOGIN PASSWORD '([^']+)'", (root / "infra/init-db.sql").read_text(encoding="utf-8")).group(1)
        return f"postgresql+psycopg://sales_app_user:{pw}@127.0.0.1:5432/sales_ai_db"
    pw = re.search(r"POSTGRES_PASSWORD:-([^}]+)\}", (root / "infra/docker-compose.yml").read_text(encoding="utf-8")).group(1)
    return f"postgresql+psycopg://postgres:{pw}@127.0.0.1:5432/sales_ai_db"


def test_f09_login_lookup_works_under_rls_and_superuser_is_refused(monkeypatch):
    # psycopg async needs a selector event loop on Windows.
    import asyncio
    asyncio.run(_f09_body(monkeypatch), loop_factory=asyncio.SelectorEventLoop)


async def _f09_body(monkeypatch):
    from sqlalchemy import text
    from src.backend.core import database as dbm
    app_engine = create_async_engine(_dev_pg_url("app"))
    su_engine = create_async_engine(_dev_pg_url("su"))
    try:
        async with app_engine.connect() as c:
            await c.execute(text("SELECT 1"))
    except Exception:
        await app_engine.dispose(); await su_engine.dispose()
        pytest.skip("Local PostgreSQL not reachable")
    tenant, user = "t_f09_" + uuid.uuid4().hex[:8], "u_f09_" + uuid.uuid4().hex[:8]
    email = f"{user}@f09.test"
    try:
        async with su_engine.begin() as c:
            await c.execute(text("INSERT INTO tenants(id,name,slug) VALUES (:t,:t,:t)"), {"t": tenant})
            await c.execute(text("INSERT INTO users(id,tenant_id,email,hashed_password,full_name) VALUES (:u,:t,:e,'x','x')"),
                            {"u": user, "t": tenant, "e": email})
        app_factory = async_sessionmaker(bind=app_engine, class_=AsyncSession, expire_on_commit=False)
        async with app_factory() as s:
            # The app role cannot see users without tenant context ...
            assert (await s.execute(text("SELECT count(*) FROM users WHERE email=:e"), {"e": email})).scalar() == 0
            # ... but the SECURITY DEFINER lookup resolves exactly the login tenant
            assert await dbm.resolve_login_tenants(s, email) == [tenant]
            assert await dbm.resolve_login_tenants(s, email, "other-tenant") == []
            await dbm.bind_tenant_context(s, tenant)
            assert (await s.execute(text("SELECT count(*) FROM users WHERE email=:e"), {"e": email})).scalar() == 1
        # Startup guard: least-privileged role accepted, superuser refused outside development
        assert await dbm.assert_rls_enforced_connection(app_engine) is None
        monkeypatch.setattr(dbm.settings, "environment", "production")
        with pytest.raises(RuntimeError, match="bypasses Row-Level Security"):
            await dbm.assert_rls_enforced_connection(su_engine)
    finally:
        async with su_engine.begin() as c:
            await c.execute(text("DELETE FROM users WHERE id=:u"), {"u": user})
            await c.execute(text("DELETE FROM tenants WHERE id=:t"), {"t": tenant})
        await app_engine.dispose()
        await su_engine.dispose()
