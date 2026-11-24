"""
Contract Tests for Quotation Lifecycle, Terms Hashing, Document Generation, and Manager Approvals.
Tests Quote State Machine, automatic approval trigger, pro-forma creation, customer acceptance, and expiration.
(Baseline Controls 16, 17, 33, 34, 42, 51, 57, 58; SAI-08)
"""
import pytest
from src.backend.core.signed_links import issue_link_token
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from datetime import timedelta, datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

from src.backend.main import app
from src.backend.models.entities import (
    Base, Tenant, User, Role, UserRole, Account, Opportunity, Product, Quote, QuoteDocument, QuoteApproval
)
from src.backend.core.security import SecurityService
from src.backend.core.database import get_db_session

TEST_DB = "sqlite+aiosqlite:///:memory:"

@asynccontextmanager
async def get_quotes_test_env():
    engine = create_async_engine(
        TEST_DB,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        t = Tenant(id="t_qt_01", name="Quotes Tenant Alpha", slug="quotes-tenant-alpha")
        session.add(t)

        rep = User(
            id="u_rep_qt",
            tenant_id="t_qt_01",
            email="rep@quotes.com",
            hashed_password=SecurityService.hash_password("RepPass123!"),
            full_name="Sales Rep Omar",
            is_active=True,
            is_verified=True
        )
        mgr = User(
            id="u_mgr_qt",
            tenant_id="t_qt_01",
            email="mgr@quotes.com",
            hashed_password=SecurityService.hash_password("MgrPass123!"),
            full_name="Sales Manager Sarah",
            is_active=True,
            is_verified=True
        )
        prod = Product(
            id="p_sw_01",
            tenant_id="t_qt_01",
            sku="SW-ENTERPRISE-01",
            name="Enterprise SaaS License",
            category="SOFTWARE",
            base_price_cents=100000,  # 1,000 MAD
            cost_cents=20000,        # 200 MAD
            tax_rate_percent=20.0,
            uom="UNIT",
            is_active=True
        )
        session.add_all([rep, mgr, prod])
        await session.commit()

    async def override_get_db():
        async with session_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db

    import src.backend.core.auth_middleware as mw
    import src.backend.core.database as db_mod
    orig_factory = db_mod.AsyncSessionLocal
    db_mod.AsyncSessionLocal = session_factory
    mw.AsyncSessionLocal = session_factory

    rep_token, _, _ = SecurityService.create_access_token(
        user_id="u_rep_qt",
        tenant_id="t_qt_01",
        email="rep@quotes.com",
        roles=["sales_rep"],
        permissions=["quotes:read", "quotes:write", "catalog:read"],
        mfa_verified=False,
        expires_delta=timedelta(minutes=30)
    )

    mgr_token, _, _ = SecurityService.create_access_token(
        user_id="u_mgr_qt",
        tenant_id="t_qt_01",
        email="mgr@quotes.com",
        roles=["sales_manager"],
        permissions=["quotes:read", "quotes:write", "quotes:approve"],
        mfa_verified=True,  # Step-up MFA active
        expires_delta=timedelta(minutes=30)
    )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield {
                "client": client,
                "rep_token": rep_token,
                "mgr_token": mgr_token,
                "tenant_id": "t_qt_01",
                "rep_user_id": "u_rep_qt",
                "mgr_user_id": "u_mgr_qt",
                "product_id": "p_sw_01",
                "session_factory": session_factory
            }
    finally:
        db_mod.AsyncSessionLocal = orig_factory
        mw.AsyncSessionLocal = orig_factory
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_quote_standard_lifecycle():
    """
    Tests full standard lifecycle without manager approval:
    DRAFT -> PRICED -> ISSUED -> SENT -> ACCEPTED
    """
    async with get_quotes_test_env() as env:
        client = env["client"]
        rep_headers = {"Authorization": f"Bearer {env['rep_token']}"}

        # 1. Create DRAFT quote
        draft_payload = {
            "currency": "MAD",
            "payment_terms": "NET_30",
            "valid_days": 30,
            "notes": "Standard commercial proposal"
        }
        res = await client.post("/api/v1/quotes", json=draft_payload, headers=rep_headers)
        assert res.status_code == 201, res.text
        quote = res.json()
        quote_id = quote["id"]
        assert quote["status"] == "DRAFT"
        assert quote["version"] == 1

        # 2. Add line items and price quote (discount 10% <= 20% max rep discount -> no approval needed)
        items_payload = {
            "expected_version": 1,
            "payment_terms": "NET_30",
            "items": [
                {
                    "product_id": env["product_id"],
                    "quantity": 10,
                    "discount_percent": 10.0
                }
            ]
        }
        price_res = await client.put(f"/api/v1/quotes/{quote_id}/items", json=items_payload, headers=rep_headers)
        assert price_res.status_code == 200, price_res.text
        priced_quote = price_res.json()
        assert priced_quote["status"] == "PRICED"
        assert priced_quote["version"] == 2
        assert priced_quote["requires_approval"] is False
        assert priced_quote["terms_hash"] != "draft_uncalculated_hash"
        # 10 units * 1,000 MAD = 10,000 MAD subtotal (1,000,000 cents)
        assert priced_quote["subtotal_cents"] == 1000000
        # 10% discount = 1,000 MAD (100,000 cents)
        assert priced_quote["discount_total_cents"] == 100000
        # Taxable amount = 9,000 MAD, 20% VAT = 1,800 MAD (180,000 cents)
        assert priced_quote["tax_total_cents"] == 180000
        # Grand total = 10,800 MAD (1,080,000 cents)
        assert priced_quote["grand_total_cents"] == 1080000

        # 3. Issue Quote -> generates document and advances state to ISSUED
        issue_res = await client.post(f"/api/v1/quotes/{quote_id}/issue", headers=rep_headers)
        assert issue_res.status_code == 200, issue_res.text
        issue_data = issue_res.json()
        assert issue_data["quote_status"] == "ISSUED"
        assert issue_data["document_hash"] is not None
        assert len(issue_data["document_hash"]) == 64  # SHA-256

        # Verify Document endpoint
        doc_res = await client.get(f"/api/v1/quotes/{quote_id}/document", headers=rep_headers)
        assert doc_res.status_code == 200
        assert doc_res.json()["document_hash"] == issue_data["document_hash"]

        # 4. Send Quote -> advances state to SENT
        send_payload = {
            "recipient_identifier": "client@acme.ma",
            "channel_type": "EMAIL"
        }
        send_res = await client.post(f"/api/v1/quotes/{quote_id}/send", json=send_payload, headers=rep_headers)
        assert send_res.status_code == 200
        assert send_res.json()["quote_status"] == "SENT"

        token = send_res.json()["acceptance_token"]

        # 5a. Knowing the quote id is not enough: no token / forged token are refused
        no_tok = await client.post(f"/api/v1/quotes/{quote_id}/accept", json={"acceptance_token": ""})
        assert no_tok.status_code == 401
        forged = await client.post(f"/api/v1/quotes/{quote_id}/accept", json={"acceptance_token": token[:-4] + "0000"})
        assert forged.status_code == 401

        # 5. Public Customer Acceptance through the signed link sent with the quote
        accept_payload = {
            "acceptance_token": token,
            "signature_or_note": "Digitally accepted by Procurement Director"
        }
        accept_res = await client.post(f"/api/v1/quotes/{quote_id}/accept", json=accept_payload)
        assert accept_res.status_code == 200, accept_res.text
        assert accept_res.json()["quote_status"] == "ACCEPTED"


@pytest.mark.asyncio
async def test_quote_manager_approval_workflow():
    """
    Tests quote requiring manager approval (> 20% discount):
    DRAFT -> PENDING_APPROVAL -> (attempt issue fails 403) -> MANAGER APPROVAL -> ISSUED
    """
    async with get_quotes_test_env() as env:
        client = env["client"]
        rep_headers = {"Authorization": f"Bearer {env['rep_token']}"}
        mgr_headers = {"Authorization": f"Bearer {env['mgr_token']}"}

        # 1. Create DRAFT quote
        res = await client.post("/api/v1/quotes", json={"currency": "MAD"}, headers=rep_headers)
        quote_id = res.json()["id"]

        # 2. Add line items with 25% discount (exceeds 20% max rep discount threshold)
        items_payload = {
            "expected_version": 1,
            "items": [
                {
                    "product_id": env["product_id"],
                    "quantity": 5,
                    "discount_percent": 25.0
                }
            ]
        }
        price_res = await client.put(f"/api/v1/quotes/{quote_id}/items", json=items_payload, headers=rep_headers)
        assert price_res.status_code == 200
        quote_data = price_res.json()
        assert quote_data["status"] == "PENDING_APPROVAL"
        assert quote_data["requires_approval"] is True

        # 3. Attempt to issue quote directly without approval -> MUST FAIL WITH 403
        issue_attempt = await client.post(f"/api/v1/quotes/{quote_id}/issue", headers=rep_headers)
        assert issue_attempt.status_code == 403, f"Expected 403, got {issue_attempt.status_code}"

        # 4. Manager lists pending approvals
        list_app_res = await client.get("/api/v1/approvals/pending", headers=mgr_headers)
        assert list_app_res.status_code == 200
        pending_list = list_app_res.json()
        assert len(pending_list) >= 1
        approval = next(a for a in pending_list if a["quote_id"] == quote_id)
        approval_id = approval["id"]
        assert approval["status"] == "PENDING"
        assert approval["requested_by_user_id"] == env["rep_user_id"]

        # 5. Manager approves the quotation
        decide_payload = {
            "decision": "APPROVED",
            "reason": "Special enterprise incentive approved for Q4 quota."
        }
        decide_res = await client.post(f"/api/v1/approvals/{approval_id}/decide", json=decide_payload, headers=mgr_headers)
        assert decide_res.status_code == 200, decide_res.text
        decided = decide_res.json()
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == env["mgr_user_id"]

        # 6. Rep can now successfully issue the approved quote
        issue_res = await client.post(f"/api/v1/quotes/{quote_id}/issue", headers=rep_headers)
        assert issue_res.status_code == 200, issue_res.text
        assert issue_res.json()["quote_status"] == "ISSUED"


@pytest.mark.asyncio
async def test_quote_expiration_rejection():
    """
    Tests that a quote past its valid_until date cannot be accepted.
    """
    async with get_quotes_test_env() as env:
        client = env["client"]
        rep_headers = {"Authorization": f"Bearer {env['rep_token']}"}

        # 1. Create quote
        res = await client.post("/api/v1/quotes", json={"valid_days": 30}, headers=rep_headers)
        quote_id = res.json()["id"]

        # Set status to SENT and expired valid_until directly via session for test
        async with env["session_factory"]() as s:
            q = (await s.execute(select(Quote).where(Quote.id == quote_id))).scalars().first()
            q.status = "SENT"
            q.valid_until = datetime.now(timezone.utc) - timedelta(days=2)
            await s.commit()
            link_token = issue_link_token("quote_response", q.tenant_id, q.id, q.version, ttl_seconds=3600)

        # 2. Attempt customer acceptance -> MUST return 410 GONE
        accept_res = await client.post(f"/api/v1/quotes/{quote_id}/accept",
                                       json={"acceptance_token": link_token, "signature_or_note": "Too late"})
        assert accept_res.status_code == 410, f"Expected 410 Gone for expired quote, got {accept_res.status_code}"
