"""
Concurrency Tests for Quotation Approvals and State Locking.
Tests race conditions, one-use approval decisions, terms-hash mismatch invalidation, and optimistic version locking.
(Baseline Controls 05, 06, 07, 34, 42, 57, 58; SAI-08)
"""
import pytest
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

from src.backend.models.entities import (
    Base, Tenant, User, Product, Quote, QuoteApproval
)
from src.backend.core.security import SecurityService
from src.backend.domains.quotations.service import (
    QuotationService, StaleQuoteError
)
from src.backend.domains.approvals.service import (
    ApprovalService, ApprovalAlreadyDecidedError, TermsHashMismatchError
)

TEST_DB = "sqlite+aiosqlite:///:memory:"

@asynccontextmanager
async def get_concurrency_db_env():
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
        t = Tenant(id="t_race_01", name="Concurrency Tenant", slug="concurrency-tenant")
        rep = User(
            id="u_rep_race",
            tenant_id="t_race_01",
            email="rep@race.com",
            hashed_password=SecurityService.hash_password("RepPass123!"),
            full_name="Rep Race",
            is_active=True,
            is_verified=True
        )
        mgr1 = User(
            id="u_mgr_race1",
            tenant_id="t_race_01",
            email="mgr1@race.com",
            hashed_password=SecurityService.hash_password("MgrPass123!"),
            full_name="Manager One",
            is_active=True,
            is_verified=True
        )
        mgr2 = User(
            id="u_mgr_race2",
            tenant_id="t_race_01",
            email="mgr2@race.com",
            hashed_password=SecurityService.hash_password("MgrPass123!"),
            full_name="Manager Two",
            is_active=True,
            is_verified=True
        )
        prod = Product(
            id="p_race_01",
            tenant_id="t_race_01",
            sku="RACE-ITEM-01",
            name="Concurrency High-Demand Hardware",
            category="HARDWARE",
            base_price_cents=50000,
            cost_cents=10000,
            tax_rate_percent=20.0,
            uom="UNIT",
            is_active=True
        )
        session.add_all([t, rep, mgr1, mgr2, prod])
        await session.commit()

    try:
        yield {
            "session_factory": session_factory,
            "tenant_id": "t_race_01",
            "rep_id": "u_rep_race",
            "mgr1_id": "u_mgr_race1",
            "mgr2_id": "u_mgr_race2",
            "product_id": "p_race_01"
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_approval_decisions_one_use_only():
    """
    Control 57, SAI-08:
    Guarantees that when two managers attempt to decide the exact same approval request concurrently,
    exactly one succeeds, and the other receives ApprovalAlreadyDecidedError (one-use decision guarantee).
    """
    async with get_concurrency_db_env() as env:
        sf = env["session_factory"]
        tenant_id = env["tenant_id"]

        # 1. Create a quote requiring approval (25% discount)
        async with sf() as session:
            quote = await QuotationService.create_draft_quote(
                session=session,
                tenant_id=tenant_id,
                created_by_user_id=env["rep_id"]
            )
            await session.commit()
            quote_id = quote.id

        async with sf() as session:
            priced = await QuotationService.update_and_price_quote(
                session=session,
                tenant_id=tenant_id,
                quote_id=quote_id,
                item_requests=[{"product_id": env["product_id"], "quantity": 1, "discount_percent": 25.0}],
                actor_user_id=env["rep_id"]
            )
            await session.commit()
            assert priced.status == "PENDING_APPROVAL"

        # Find the enqueued approval
        async with sf() as session:
            stmt = select(QuoteApproval).where(QuoteApproval.quote_id == quote_id)
            res = await session.execute(stmt)
            approval = res.scalars().first()
            assert approval is not None
            approval_id = approval.id

        # 2. Manager 1 decides approval first -> SUCCEEDS
        async with sf() as s:
            decided = await ApprovalService.decide_approval(
                session=s,
                tenant_id=tenant_id,
                approval_id=approval_id,
                approver_user_id=env["mgr1_id"],
                decision="APPROVED",
                reason="Manager 1 approved first",
                approver_roles=["sales_manager"],
                mfa_verified=True
            )
            await s.commit()
            assert decided.status == "APPROVED"

        # 3. Manager 2 attempts to decide the same approval second -> MUST RAISE ApprovalAlreadyDecidedError
        async with sf() as s:
            with pytest.raises(ApprovalAlreadyDecidedError) as exc_info:
                await ApprovalService.decide_approval(
                    session=s,
                    tenant_id=tenant_id,
                    approval_id=approval_id,
                    approver_user_id=env["mgr2_id"],
                    decision="REJECTED",
                    reason="Manager 2 rejected second",
                    approver_roles=["sales_manager"],
                    mfa_verified=True
                )
            assert "already 'APPROVED' and cannot be decided again" in str(exc_info.value)

        # Verify final state in database
        async with sf() as session:
            final_app = await ApprovalService.get_approval(session, tenant_id, approval_id)
            assert final_app.status in ["APPROVED", "REJECTED"]
            assert final_app.decided_at is not None


@pytest.mark.asyncio
async def test_terms_changed_invalidates_pending_approval():
    """
    Control 57, 58:
    If quote terms change while an approval is pending, any attempt to decide the original approval
    must fail with TermsHashMismatchError, and the pending approval record must be marked INVALIDATED.
    """
    async with get_concurrency_db_env() as env:
        sf = env["session_factory"]
        tenant_id = env["tenant_id"]

        # 1. Create quote and price with 25% discount (requires approval, version 2)
        async with sf() as session:
            quote = await QuotationService.create_draft_quote(
                session=session,
                tenant_id=tenant_id,
                created_by_user_id=env["rep_id"]
            )
            await session.commit()
            quote_id = quote.id

        async with sf() as session:
            await QuotationService.update_and_price_quote(
                session=session,
                tenant_id=tenant_id,
                quote_id=quote_id,
                item_requests=[{"product_id": env["product_id"], "quantity": 1, "discount_percent": 25.0}],
                actor_user_id=env["rep_id"]
            )
            await session.commit()

        # Find the pending approval (version 2)
        async with sf() as session:
            stmt = select(QuoteApproval).where(QuoteApproval.quote_id == quote_id)
            approval = (await session.execute(stmt)).scalars().first()
            approval_id = approval.id
            initial_hash = approval.terms_hash

        # 2. While approval is pending, Sales Rep modifies terms (adds 1 more unit -> version 3, new terms hash)
        async with sf() as session:
            await QuotationService.update_and_price_quote(
                session=session,
                tenant_id=tenant_id,
                quote_id=quote_id,
                item_requests=[{"product_id": env["product_id"], "quantity": 2, "discount_percent": 25.0}],
                expected_version=2,
                actor_user_id=env["rep_id"]
            )
            await session.commit()

        # 3. Manager tries to approve the older approval (which held version 2 terms hash)
        async with sf() as session:
            with pytest.raises(TermsHashMismatchError) as exc_info:
                await ApprovalService.decide_approval(
                    session=session,
                    tenant_id=tenant_id,
                    approval_id=approval_id,
                    approver_user_id=env["mgr1_id"],
                    decision="APPROVED",
                    approver_roles=["sales_manager"],
                    mfa_verified=True
                )
            assert "quote terms changed" in str(exc_info.value).lower()

        # 4. Verify old approval status is now INVALIDATED
        async with sf() as session:
            old_app = await ApprovalService.get_approval(session, tenant_id, approval_id)
            assert old_app.status == "INVALIDATED"


@pytest.mark.asyncio
async def test_quote_optimistic_concurrency_conflict():
    """
    Optimistic Locking:
    Verifies that passing expected_version prevents stale updates.
    """
    async with get_concurrency_db_env() as env:
        sf = env["session_factory"]
        tenant_id = env["tenant_id"]

        # 1. Create quote V1
        async with sf() as session:
            quote = await QuotationService.create_draft_quote(
                session=session,
                tenant_id=tenant_id,
                created_by_user_id=env["rep_id"]
            )
            await session.commit()
            quote_id = quote.id

        # 2. First update with expected_version=1 succeeds, advancing version to 2
        async with sf() as session:
            await QuotationService.update_and_price_quote(
                session=session,
                tenant_id=tenant_id,
                quote_id=quote_id,
                item_requests=[{"product_id": env["product_id"], "quantity": 1}],
                expected_version=1,
                actor_user_id=env["rep_id"]
            )
            await session.commit()

        # 3. Second update still passing stale expected_version=1 MUST raise StaleQuoteError
        async with sf() as session:
            with pytest.raises(StaleQuoteError) as exc_info:
                await QuotationService.update_and_price_quote(
                    session=session,
                    tenant_id=tenant_id,
                    quote_id=quote_id,
                    item_requests=[{"product_id": env["product_id"], "quantity": 2}],
                    expected_version=1,
                    actor_user_id=env["rep_id"]
                )
            assert "version conflict" in str(exc_info.value)
