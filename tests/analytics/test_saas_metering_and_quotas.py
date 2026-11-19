"""
Unit & Integration Tests for SaaS Subscription Management and Quota Metering (Step 11).
Validates multi-tenant subscription tiers (Starter, Pro, Enterprise),
resource consumption recording (tokens, voice, API calls), 80% warning alerts,
hard cap enforcement (QuotaExhaustedError), and administrative quota adjustments.
"""
import uuid
import asyncio
import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.backend.models.entities import Base, TenantSubscription, TenantUsageMeter, TenantQuotaLimit
from src.backend.domains.saas.service import SaaSAdminService, QuotaExhaustedError


@pytest.fixture(scope="module")
def saas_async_session():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_saas_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _init_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_init_tables())

    return session_factory


@pytest.mark.asyncio
async def test_subscription_creation_and_defaults(saas_async_session):
    """
    Validates automatic provisioning of tenant subscriptions with tier-specific limits.
    """
    async with saas_async_session() as session:
        tenant_id = f"t_sub_test_{uuid.uuid4().hex[:6]}"
        service = SaaSAdminService(session=session, tenant_id=tenant_id)

        # 1. Default to Professional plan
        sub = await service.get_or_create_subscription(plan_id="professional")
        assert sub.tenant_id == tenant_id
        assert sub.plan_id == "professional"
        assert sub.status == "ACTIVE"
        assert sub.monthly_token_limit == 5_000_000
        assert sub.monthly_voice_minutes_limit == 1_000
        assert sub.monthly_api_call_limit == 100_000
        assert sub.max_seats == 25


@pytest.mark.asyncio
async def test_record_usage_and_monthly_metering(saas_async_session):
    """
    Validates atomic usage tracking in the monthly ledger (tokens, voice seconds, API calls).
    """
    async with saas_async_session() as session:
        tenant_id = f"t_usage_{uuid.uuid4().hex[:6]}"
        service = SaaSAdminService(session=session, tenant_id=tenant_id)

        await service.get_or_create_subscription(plan_id="starter")

        # Record turn 1: 500 prompt tokens, 200 completion tokens, 30s voice, 1 API call
        meter1 = await service.record_usage(
            prompt_tokens=500,
            completion_tokens=200,
            voice_seconds=30,
            api_requests=1
        )
        assert meter1.total_tokens == 700
        assert meter1.voice_seconds == 30
        assert meter1.api_requests_count == 1

        # Record turn 2: 1000 prompt tokens, 500 completion tokens, 0s voice, 2 API calls
        meter2 = await service.record_usage(
            prompt_tokens=1000,
            completion_tokens=500,
            voice_seconds=0,
            api_requests=2
        )
        assert meter2.total_tokens == 2200
        assert meter2.voice_seconds == 30
        assert meter2.api_requests_count == 3


@pytest.mark.asyncio
async def test_quota_exhaustion_hard_cap(saas_async_session):
    """
    Validates that exceeding the subscription limits raises QuotaExhaustedError
    and prevents further un-metered usage.
    """
    async with saas_async_session() as session:
        tenant_id = f"t_cap_{uuid.uuid4().hex[:6]}"
        service = SaaSAdminService(session=session, tenant_id=tenant_id)

        # Provision a Starter subscription: limit is 1,000,000 tokens
        sub = await service.get_or_create_subscription(plan_id="starter")

        # Set usage near limit: 999,000 tokens
        meter = await service.get_or_create_monthly_meter()
        meter.total_tokens = 999_000
        await session.flush()

        # 1. Allowed: request 500 tokens (999,000 + 500 <= 1,000,000)
        assert await service.check_quota_available("tokens", units_requested=500) is True

        # 2. Blocked: request 2,000 tokens (999,000 + 2,000 > 1,000,000) -> Raises QuotaExhaustedError
        with pytest.raises(QuotaExhaustedError) as exc_info:
            await service.check_quota_available("tokens", units_requested=2000)
        assert "quota exhausted" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_custom_quota_adjustment(saas_async_session):
    """
    Validates tenant admin adjustment of specific resource quotas with justification.
    """
    async with saas_async_session() as session:
        tenant_id = f"t_adj_{uuid.uuid4().hex[:6]}"
        service = SaaSAdminService(session=session, tenant_id=tenant_id)

        # Set custom limit for voice_seconds: 120,000 (2,000 mins)
        limit_entry = await service.adjust_quota_limit(
            metric_name="voice_seconds",
            new_limit=120000,
            reason="Enterprise Ramadan Sales Campaign"
        )

        assert limit_entry.metric_name == "voice_seconds"
        assert limit_entry.limit_value == 120000
        assert limit_entry.adjustment_reason == "Enterprise Ramadan Sales Campaign"
