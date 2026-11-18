"""
Security Tests for Quotation, Approvals, Pricing, and Tenant Boundaries.
Tests Anti-Self-Approval, Step-up MFA enforcement, BOLA/IDOR protection, and Float Money rejection.
(Baseline Controls 05, 06, 07, 16, 17, 33, 34, 42, 51, 57, 58; SAI-08)
"""
import pytest
from decimal import Decimal
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from datetime import timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

from src.backend.main import app
from src.backend.models.entities import (
    Base, Tenant, User, Product, Quote, QuoteApproval, Account
)
from src.backend.core.security import SecurityService
from src.backend.core.database import get_db_session
from src.backend.domains.pricing.money import Money, NegativeQuantityError
from src.backend.domains.pricing.service import PricingService, PricingError
from src.backend.domains.quotations.service import QuotationService
from src.backend.domains.approvals.service import (
    ApprovalService, SelfApprovalProhibitedError, MfaRequiredForApprovalError
)

TEST_DB = "sqlite+aiosqlite:///:memory:"

@asynccontextmanager
async def get_security_test_env():
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
        t_alpha = Tenant(id="t_sec_alpha", name="Security Tenant Alpha", slug="sec-alpha")
        t_beta = Tenant(id="t_sec_beta", name="Security Tenant Beta", slug="sec-beta")
        session.add_all([t_alpha, t_beta])

        # Rep in Tenant Alpha
        rep_alpha = User(
            id="u_rep_alpha",
            tenant_id="t_sec_alpha",
            email="rep@alpha.com",
            hashed_password=SecurityService.hash_password("RepPass123!"),
            full_name="Rep Omar Alpha",
            is_active=True,
            is_verified=True
        )
        # Manager in Tenant Alpha (with step-up MFA)
        mgr_alpha = User(
            id="u_mgr_alpha",
            tenant_id="t_sec_alpha",
            email="mgr@alpha.com",
            hashed_password=SecurityService.hash_password("MgrPass123!"),
            full_name="Manager Sarah Alpha",
            is_active=True,
            is_verified=True
        )
        # Attacker / Rep in Tenant Beta
        rep_beta = User(
            id="u_rep_beta",
            tenant_id="t_sec_beta",
            email="attacker@beta.com",
            hashed_password=SecurityService.hash_password("BetaPass123!"),
            full_name="Rep Bob Beta",
            is_active=True,
            is_verified=True
        )
        prod = Product(
            id="p_sec_01",
            tenant_id="t_sec_alpha",
            sku="SEC-SERVER-01",
            name="Alpha High-Security Appliance",
            category="HARDWARE",
            base_price_cents=200000,
            cost_cents=100000,
            tax_rate_percent=20.0,
            uom="UNIT",
            is_active=True
        )
        session.add_all([rep_alpha, mgr_alpha, rep_beta, prod])
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

    # Token for Rep Alpha (sales_rep, no MFA)
    rep_alpha_token, _, _ = SecurityService.create_access_token(
        user_id="u_rep_alpha",
        tenant_id="t_sec_alpha",
        email="rep@alpha.com",
        roles=["sales_rep", "sales_manager"],  # Has manager role but is creator!
        permissions=["quotes:read", "quotes:write", "quotes:approve"],
        mfa_verified=True,
        expires_delta=timedelta(minutes=30)
    )

    # Token for Manager Alpha without MFA
    mgr_no_mfa_token, _, _ = SecurityService.create_access_token(
        user_id="u_mgr_alpha",
        tenant_id="t_sec_alpha",
        email="mgr@alpha.com",
        roles=["sales_manager"],
        permissions=["quotes:read", "quotes:write", "quotes:approve"],
        mfa_verified=False,  # NO MFA
        expires_delta=timedelta(minutes=30)
    )

    # Token for Attacker in Tenant Beta
    rep_beta_token, _, _ = SecurityService.create_access_token(
        user_id="u_rep_beta",
        tenant_id="t_sec_beta",
        email="attacker@beta.com",
        roles=["tenant_admin", "sales_manager"],
        permissions=["quotes:read", "quotes:write", "quotes:approve", "crm:read"],
        mfa_verified=True,
        expires_delta=timedelta(minutes=30)
    )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield {
                "client": client,
                "session_factory": session_factory,
                "rep_alpha_token": rep_alpha_token,
                "mgr_no_mfa_token": mgr_no_mfa_token,
                "rep_beta_token": rep_beta_token,
                "t_alpha": "t_sec_alpha",
                "t_beta": "t_sec_beta",
                "u_rep_alpha": "u_rep_alpha",
                "u_mgr_alpha": "u_mgr_alpha",
                "p_sec_01": "p_sec_01"
            }
    finally:
        db_mod.AsyncSessionLocal = orig_factory
        mw.AsyncSessionLocal = orig_factory
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_anti_self_approval_strict_enforcement():
    """
    Control 57 (Anti-Self-Approval):
    The quote creator/requester cannot approve their own quote, regardless of roles or MFA status.
    """
    async with get_security_test_env() as env:
        client = env["client"]
        sf = env["session_factory"]
        t_alpha = env["t_alpha"]
        rep_id = env["u_rep_alpha"]

        # 1. Rep creates a quote and requests 25% discount -> requires approval
        async with sf() as session:
            quote = await QuotationService.create_draft_quote(
                session=session,
                tenant_id=t_alpha,
                created_by_user_id=rep_id
            )
            await session.commit()
            quote_id = quote.id

        async with sf() as session:
            await QuotationService.update_and_price_quote(
                session=session,
                tenant_id=t_alpha,
                quote_id=quote_id,
                item_requests=[{"product_id": env["p_sec_01"], "quantity": 1, "discount_percent": 25.0}],
                actor_user_id=rep_id
            )
            await session.commit()

        # Fetch the pending approval
        async with sf() as session:
            stmt = select(QuoteApproval).where(QuoteApproval.quote_id == quote_id)
            approval = (await session.execute(stmt)).scalars().first()
            assert approval is not None
            assert approval.requested_by_user_id == rep_id
            approval_id = approval.id

        # 2. Domain Service Self-Approval Rejection
        async with sf() as session:
            with pytest.raises(SelfApprovalProhibitedError) as exc_info:
                await ApprovalService.decide_approval(
                    session=session,
                    tenant_id=t_alpha,
                    approval_id=approval_id,
                    approver_user_id=rep_id,  # Requester attempting self-approval
                    decision="APPROVED",
                    approver_roles=["sales_manager", "tenant_admin"],
                    mfa_verified=True
                )
            assert "Self-approval is strictly prohibited" in str(exc_info.value)

        # 3. HTTP Endpoint Self-Approval Rejection -> 403 Forbidden
        headers = {"Authorization": f"Bearer {env['rep_alpha_token']}"}
        decide_payload = {
            "decision": "APPROVED",
            "reason": "Attempting self-approval via API"
        }
        res = await client.post(f"/api/v1/approvals/{approval_id}/decide", json=decide_payload, headers=headers)
        assert res.status_code == 403, res.text
        assert "Self-approval is strictly prohibited" in res.json()["detail"]


@pytest.mark.asyncio
async def test_step_up_mfa_mandatory_for_privileged_approvals():
    """
    Control 05, 07; SAI-08:
    Approving a quotation requires step-up MFA. Attempting to approve without verified MFA must return 403.
    """
    async with get_security_test_env() as env:
        client = env["client"]
        sf = env["session_factory"]
        t_alpha = env["t_alpha"]
        rep_id = env["u_rep_alpha"]
        mgr_id = env["u_mgr_alpha"]

        # 1. Create quote requiring approval
        async with sf() as session:
            quote = await QuotationService.create_draft_quote(
                session=session,
                tenant_id=t_alpha,
                created_by_user_id=rep_id
            )
            await session.commit()
            quote_id = quote.id

        async with sf() as session:
            await QuotationService.update_and_price_quote(
                session=session,
                tenant_id=t_alpha,
                quote_id=quote_id,
                item_requests=[{"product_id": env["p_sec_01"], "quantity": 1, "discount_percent": 25.0}],
                actor_user_id=rep_id
            )
            await session.commit()

        async with sf() as session:
            stmt = select(QuoteApproval).where(QuoteApproval.quote_id == quote_id)
            approval = (await session.execute(stmt)).scalars().first()
            approval_id = approval.id

        # 2. Domain Service MFA Rejection
        async with sf() as session:
            with pytest.raises(MfaRequiredForApprovalError) as exc_info:
                await ApprovalService.decide_approval(
                    session=session,
                    tenant_id=t_alpha,
                    approval_id=approval_id,
                    approver_user_id=mgr_id,
                    decision="APPROVED",
                    approver_roles=["sales_manager"],
                    mfa_verified=False  # NO MFA
                )
            assert "Step-up MFA verification is mandatory" in str(exc_info.value)

        # 3. HTTP Endpoint MFA Rejection -> 403 Forbidden
        no_mfa_headers = {"Authorization": f"Bearer {env['mgr_no_mfa_token']}"}
        decide_payload = {
            "decision": "APPROVED",
            "reason": "Manager approving without step-up MFA"
        }
        res = await client.post(f"/api/v1/approvals/{approval_id}/decide", json=decide_payload, headers=no_mfa_headers)
        assert res.status_code == 403, res.text
        assert "Step-up MFA verification is mandatory" in str(res.json()["detail"])


@pytest.mark.asyncio
async def test_bola_idor_cross_tenant_isolation():
    """
    Control 33, 42:
    Tenant Beta must be strictly blocked from reading, modifying, issuing, or approving Tenant Alpha's quotations or accounts.
    """
    async with get_security_test_env() as env:
        client = env["client"]
        sf = env["session_factory"]
        t_alpha = env["t_alpha"]
        rep_alpha = env["u_rep_alpha"]
        beta_headers = {"Authorization": f"Bearer {env['rep_beta_token']}"}

        # 1. Create an Account and Quote in Tenant Alpha
        async with sf() as session:
            acc = Account(
                id="acc_alpha_secret",
                tenant_id=t_alpha,
                name="Alpha Defense Systems",
                account_type="CUSTOMER",
                is_active=True
            )
            quote = await QuotationService.create_draft_quote(
                session=session,
                tenant_id=t_alpha,
                account_id=acc.id,
                created_by_user_id=rep_alpha
            )
            session.add(acc)
            await session.commit()
            alpha_quote_id = quote.id

        # 2. Attacker in Tenant Beta tries to GET Tenant Alpha's Quote -> 404
        get_res = await client.get(f"/api/v1/quotes/{alpha_quote_id}", headers=beta_headers)
        assert get_res.status_code == 404, f"Expected 404 BOLA block, got {get_res.status_code}"

        # 3. Attacker in Tenant Beta tries to modify line items of Tenant Alpha's Quote -> 404
        put_res = await client.put(
            f"/api/v1/quotes/{alpha_quote_id}/items",
            json={"items": [{"product_id": env["p_sec_01"], "quantity": 1}]},
            headers=beta_headers
        )
        assert put_res.status_code == 404, f"Expected 404 BOLA block, got {put_res.status_code}"

        # 4. Attacker in Tenant Beta tries to issue Tenant Alpha's Quote -> 404
        issue_res = await client.post(f"/api/v1/quotes/{alpha_quote_id}/issue", headers=beta_headers)
        assert issue_res.status_code == 404, f"Expected 404 BOLA block, got {issue_res.status_code}"

        # 5. Attacker in Tenant Beta tries to GET Tenant Alpha's Account -> 404
        acc_res = await client.get(f"/api/v1/crm/accounts/acc_alpha_secret", headers=beta_headers)
        assert acc_res.status_code == 404, f"Expected 404 BOLA block, got {acc_res.status_code}"

        # 6. Attacker in Tenant Beta lists pending approvals -> must NOT contain Alpha's records
        app_list_res = await client.get("/api/v1/approvals/pending", headers=beta_headers)
        assert app_list_res.status_code == 200
        assert len(app_list_res.json()) == 0


@pytest.mark.asyncio
async def test_float_money_and_pricing_tampering_blocked():
    """
    Control 51 (Deterministic Integer Math):
    Strictly prevents float arithmetic and fractional cents tampering in commercial money.
    """
    m = Money(5000, "MAD")

    # Multiplication by float is strictly forbidden
    with pytest.raises(TypeError) as exc_info:
        _ = m * 1.5
    assert "strictly forbidden" in str(exc_info.value)

    # Negative quantities strictly forbidden in pricing engine
    async with get_security_test_env() as env:
        sf = env["session_factory"]
        async with sf() as session:
            with pytest.raises(NegativeQuantityError):
                await PricingService.calculate_quote_pricing(
                    session=session,
                    tenant_id=env["t_alpha"],
                    item_requests=[{"product_id": env["p_sec_01"], "quantity": -3}]
                )

            # Excessive discount > 100% strictly forbidden
            with pytest.raises(PricingError):
                await PricingService.calculate_quote_pricing(
                    session=session,
                    tenant_id=env["t_alpha"],
                    item_requests=[{"product_id": env["p_sec_01"], "quantity": 1, "discount_percent": 150.0}]
                )
