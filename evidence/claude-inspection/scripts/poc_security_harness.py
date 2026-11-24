"""
Claude independent inspection - isolated security proof-of-concept harness.
Runs the real FastAPI app in-process (httpx ASGITransport) against a throwaway
SQLite database in the scratchpad. No network server, no shared DB, no source edits.
Each probe records the HTTP status / outcome. Secrets are never printed.
"""
import os, sys, json, uuid, hmac, hashlib, asyncio, tempfile
from datetime import datetime, timedelta, timezone

REPO = sys.argv[1]
OUT = sys.argv[2]
DB = os.path.join(tempfile.gettempdir(), "claude_insp_" + uuid.uuid4().hex[:8] + ".db")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + DB.replace("\\", "/")
os.environ["ENVIRONMENT"] = "development"
sys.path.insert(0, REPO)

import httpx
from src.backend.main import app
from src.backend.core.database import init_db, AsyncSessionLocal
from src.backend.core.security import SecurityService
from src.backend.models import entities as E
import src.backend.api.payments as payments_api

results = []
def rec(pid, title, expected_secure, observed, vulnerable):
    results.append({"probe": pid, "title": title, "expected_secure_behaviour": expected_secure,
                    "observed": observed, "verdict": "VULNERABLE" if vulnerable else "DEFENDED"})

def tok(user, tenant, roles, perms=(), mfa=False):
    t, _, _ = SecurityService.create_access_token(user, tenant, f"{user}@x.test", list(roles), list(perms), mfa_verified=mfa)
    return {"Authorization": "Bearer " + t}

async def main():
    await init_db()
    TA, TB = "t_insp_A", "t_insp_B"
    UA_MGR, UA_REP, UB = "u_mgr_A", "u_rep_A", "u_B"
    async with AsyncSessionLocal() as s:
        for tid in (TA, TB):
            s.add(E.Tenant(id=tid, name=tid, slug=tid))
        for uid, tid in ((UA_MGR, TA), (UA_REP, TA), (UB, TB)):
            s.add(E.User(id=uid, tenant_id=tid, email=f"{uid}@x.test", hashed_password="x", full_name=uid))
        # Tenant B private data
        s.add(E.NotificationLog(tenant_id=TB, recipient_identifier="+212600000099", channel_type="SMS",
                                content="B-PRIVATE: votre code client 7781"))
        vs_b = E.VoiceSession(tenant_id=TB, session_id="vs_B_1")
        s.add(vs_b)
        # Tenant A order + payment intent
        order = E.SalesOrder(tenant_id=TA, order_number="SO-INSP-1", terms_hash="h", grand_total_cents=100000,
                             currency="MAD") if hasattr(E.SalesOrder, "grand_total_cents") else None
        s.add(order)
        await s.flush()
        s.add(E.PaymentIntent(tenant_id=TA, order_id=order.id, provider_intent_id="pi_insp_1", amount_cents=100000,
                              provider="STRIPE_SANDBOX"))
        await s.commit()
        order_id = order.id

    tr = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://insp") as c:
        # P1 unauthenticated cross-tenant read via X-Tenant-ID header fallback
        r = await c.get("/api/v1/notifications/history", headers={"X-Tenant-ID": TB})
        leaked = r.status_code == 200 and "B-PRIVATE" in r.text
        rec("SEC-PROBE-01", "Unauthenticated read of tenant B notifications via X-Tenant-ID header",
            "401 without bearer token", f"HTTP {r.status_code}; tenant-B content returned={leaked}", leaked)

        # P2 unauthenticated write (create automation rule / send notification) in tenant B
        r = await c.post("/api/v1/notifications/send", headers={"X-Tenant-ID": TB},
                         json={"recipient_identifier": "+212600000001", "channel_type": "SMS",
                               "message_class": "TRANSACTIONAL", "content": "injected by unauthenticated caller"})
        rec("SEC-PROBE-02", "Unauthenticated notification dispatch inside tenant B",
            "401 without bearer token", f"HTTP {r.status_code}", r.status_code in (200, 201))

        # P3 forged payment webhook using the HMAC constant committed in source
        body = json.dumps({"id": "evt_forged_" + uuid.uuid4().hex[:6], "type": "payment_intent.succeeded",
                           "data": {"id": "pi_insp_1"}})
        sig = hmac.new(payments_api.DEFAULT_WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        r = await c.post(f"/api/v1/payments/webhook?tenant_id={TA}", content=body,
                         headers={"X-Signature-SHA256": sig, "Content-Type": "application/json"})
        async with AsyncSessionLocal() as s:
            o = await s.get(E.SalesOrder, order_id)
            paid = getattr(o, "payment_status", None)
        rec("SEC-PROBE-03", "Forged payment_intent.succeeded webhook signed with repository constant",
            "Per-tenant provider secret from vault + provider reconciliation; forged event rejected",
            f"HTTP {r.status_code}; order.payment_status={paid}", paid == "PAID")

        # P4 refund: cumulative over-refund + MFA via client header, requester == approver
        mgr = tok(UA_MGR, TA, ["sales_manager"], ["orders:manage"], mfa=False)
        ids, codes = [], []
        for i in range(3):
            r = await c.post("/api/v1/payments/refunds", headers=mgr,
                             json={"order_id": order_id, "amount_cents": 100000, "reason": "probe",
                                   "idempotency_key": "same-key"})
            codes.append(r.status_code)
            if r.status_code in (200, 201): ids.append(r.json()["id"])
        appr = []
        for rid in ids:
            r = await c.post(f"/api/v1/payments/refunds/{rid}/approve", headers={**mgr, "X-MFA-Verified": "true"})
            appr.append((r.status_code, r.json().get("status") if r.headers.get("content-type", "").startswith("application/json") else None))
        total_refunded = sum(100000 for st in appr if st[1] == "COMPLETED")
        rec("SEC-PROBE-04", "Refund approval with client 'X-MFA-Verified: true' header, no real MFA; 3x full refunds, same idempotency key, self-approved",
            "Server-verified step-up MFA, cumulative refund <= captured amount, idempotency, 4-eyes",
            f"create={codes}; approve={appr}; total_refunded_cents={total_refunded} vs captured=100000",
            total_refunded > 100000 or any(st[1] == "COMPLETED" for st in appr))

        # P5 customer voice OTP backdoor 123456
        r = await c.post("/api/v1/voice/sessions", headers={"X-Tenant-ID": TA},
                         json={"voice_mode": "CUSTOMER", "channel_type": "WEBRTC", "caller_identifier": "+212611111111"})
        sid = r.json().get("session_id") if r.status_code in (200, 201) else None
        r2 = await c.post(f"/api/v1/voice/sessions/{sid}/verify-caller", headers={"X-Tenant-ID": TA},
                          json={"otp_code": "123456"})
        ok = r2.status_code == 200 and r2.json().get("verified") is True
        rec("SEC-PROBE-05", "Unauthenticated caller verifies identity with static OTP 123456 (no OTP issued)",
            "Verification fails unless a server-issued OTP was delivered and matched",
            f"create={r.status_code}; verify HTTP {r2.status_code} verified={r2.json().get('verified') if r2.status_code==200 else None}", ok)

        # P6 manager step-up with arbitrary 6 chars
        h = tok(UA_MGR, TA, ["sales_manager"], ["voice:copilot"], mfa=False)
        r = await c.post("/api/v1/voice/copilot/command", headers=h,
                         json={"command_text": "Approuve le bon de commande fournisseur 888"})
        token = (r.json().get("action_preview") or {}).get("action_token") if r.status_code == 200 else None
        r2 = await c.post("/api/v1/voice/copilot/confirm-action", headers=h,
                          json={"action_token": token, "totp_code": "abcdef", "confirmed": True})
        ok = r2.status_code == 200 and r2.json().get("executed") is True
        rec("SEC-PROBE-06", "Manager high-risk voice action confirmed with non-numeric 'TOTP' abcdef",
            "Cryptographic TOTP verification against enrolled seed",
            f"command HTTP {r.status_code}; confirm HTTP {r2.status_code}; executed={r2.json().get('executed') if r2.status_code==200 else None}", ok)

        # P6b cross-tenant action token consumption
        r = await c.post("/api/v1/voice/copilot/command", headers=h,
                         json={"command_text": "Approuve le bon de commande fournisseur 999"})
        token2 = (r.json().get("action_preview") or {}).get("action_token") if r.status_code == 200 else None
        hb = tok(UB, TB, ["sales_manager"], ["voice:copilot"])
        r2 = await c.post("/api/v1/voice/copilot/confirm-action", headers=hb,
                          json={"action_token": token2, "totp_code": "000000", "confirmed": True})
        ok = r2.status_code == 200 and r2.json().get("executed") is True
        rec("SEC-PROBE-07", "Tenant B manager consumes tenant A action-preview token",
            "Token bound to issuing tenant+user", f"HTTP {r2.status_code}; executed={r2.json().get('executed') if r2.status_code==200 else None}", ok)

        # P8 RAG ACL escalation through client-supplied user_roles
        adm = tok(UA_MGR, TA, ["sales_manager"], ["ai:rag"], mfa=True)
        r = await c.post("/api/v1/ai/rag/documents", headers=adm,
                         json={"title": "Board-only margin policy", "content": "CONFIDENTIAL floor margin 7 percent for Atlas deals. " * 5,
                               "acl_roles": ["board_only"], "source_type": "INTERNAL"})
        rep = tok(UA_REP, TA, ["sales_rep"], ["ai:rag"])
        r1 = await c.post("/api/v1/ai/rag/query", headers=rep, json={"query": "floor margin Atlas", "user_roles": ["customer"], "min_score": 0.0})
        r2 = await c.post("/api/v1/ai/rag/query", headers=rep, json={"query": "floor margin Atlas", "user_roles": ["board_only"], "min_score": 0.0})
        n1 = len(r1.json()) if r1.status_code == 200 else None
        n2 = len(r2.json()) if r2.status_code == 200 else None
        rec("SEC-PROBE-08", "Sales rep reads board-only RAG document by adding user_roles=['board_only'] to the request body",
            "Roles taken only from server-side identity", f"ingest HTTP {r.status_code}; without role -> {n1} chunks; with self-asserted role -> {n2} chunks",
            bool(n2) and not n1)

        # P9 refresh token accepted as access token
        rt, _, _ = SecurityService.create_refresh_token(UA_MGR, TA)
        r = await c.get("/api/v1/voice/callbacks", headers={"Authorization": "Bearer " + rt})
        rec("SEC-PROBE-09", "7-day refresh token presented as bearer access token",
            "Rejected (token type != access)", f"HTTP {r.status_code}", r.status_code == 200)

    # P10 OutputGuard fail-open without evidence
    from src.ai.output_guard import OutputGuard, EvidenceEnvelope
    g = OutputGuard.inspect_and_guard("Votre commande est payée. Prix final 999 MAD avec une remise de 40%.", evidence=None)
    rec("SEC-PROBE-10", "OutputGuard with no evidence envelope: paid/price/discount claims",
        "Unverifiable commercial claims blocked (fail closed)", f"is_safe={g.is_safe}; violations={len(g.violations)}", g.is_safe)
    env = EvidenceEnvelope(tenant_id="t", verified_prices={"SKU": 1250.0}, verified_currency="MAD")
    g2 = OutputGuard.inspect_and_guard("Le prix est de MAD 999, soit 999 dirhams.", evidence=env)
    rec("SEC-PROBE-11", "OutputGuard: wrong price written as 'MAD 999' / '999 dirhams'",
        "Rejected as ungrounded", f"is_safe={g2.is_safe}; violations={len(g2.violations)}", g2.is_safe)

    # P12 AI tool gateway returns fixture data regardless of DB
    from src.ai.tool_gateway import tool_gateway
    from src.ai.tool_gateway import ServerSecurityContext
    res = await tool_gateway.execute_tool("orders.get_status", {"order_id": "DOES-NOT-EXIST"},
                                          ServerSecurityContext(tenant_id=TA, user_id=UA_REP, role="order_payment", permissions=[]), None)
    rec("SEC-PROBE-12", "AI tool orders.get_status for a non-existent order",
        "NOT_FOUND from domain service", json.dumps(res)[:200], res.get("payment_status") == "PAID")

    json.dump({"generated_utc": datetime.now(timezone.utc).isoformat(), "database": "throwaway SQLite (scratch)",
               "results": results}, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    for x in results:
        print(x["probe"], x["verdict"], "|", x["observed"])

asyncio.run(main())
