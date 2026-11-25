"""
SaaS Administration, Subscription Management & Usage Quota Metering Service.
Enforces multi-tenant billing separation, quota exhaustion guards, and noisy-neighbor bounds.
(Controls 05-07, 33-35, 42-43, 49; Invariants 2, 4)
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError

from src.backend.models.entities import (
    TenantSubscription,
    TenantUsageMeter,
    TenantQuotaLimit,
    SystemAlertEvent,
    generate_uuid
)

logger = logging.getLogger("SalesAI.SaaSAdmin")


class QuotaExhaustedError(Exception):
    """Raised when a tenant attempts an operation that exceeds their plan's hard quota cap."""
    pass


class SaaSAdminService:
    # Standard plan profiles
    PLAN_PROFILES = {
        "starter": {
            "name": "Starter Plan",
            "monthly_token_limit": 1_000_000,       # 1M tokens
            "monthly_voice_minutes_limit": 200,      # 200 mins
            "monthly_api_call_limit": 25_000,        # 25k requests
            "max_seats": 5,
            "max_concurrent_turns": 2
        },
        "professional": {
            "name": "Professional Plan",
            "monthly_token_limit": 5_000_000,       # 5M tokens
            "monthly_voice_minutes_limit": 1_000,    # 1,000 mins
            "monthly_api_call_limit": 100_000,       # 100k requests
            "max_seats": 25,
            "max_concurrent_turns": 10
        },
        "enterprise": {
            "name": "Enterprise Plan",
            "monthly_token_limit": 25_000_000,      # 25M tokens
            "monthly_voice_minutes_limit": 5_000,    # 5,000 mins
            "monthly_api_call_limit": 500_000,       # 500k requests
            "max_seats": 100,
            "max_concurrent_turns": 50
        }
    }

    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    async def get_or_create_subscription(self, plan_id: str = "professional") -> TenantSubscription:
        """Retrieves or provisions the tenant's active SaaS subscription."""
        stmt = select(TenantSubscription).where(TenantSubscription.tenant_id == self.tenant_id)
        sub = (await self.session.execute(stmt)).scalar_one_or_none()

        if not sub:
            profile = self.PLAN_PROFILES.get(plan_id, self.PLAN_PROFILES["professional"])
            now = datetime.now(timezone.utc)
            period_end = now + timedelta(days=30)

            sub = TenantSubscription(
                id=generate_uuid(),
                tenant_id=self.tenant_id,
                plan_id=plan_id,
                status="ACTIVE",
                current_period_start=now,
                current_period_end=period_end,
                monthly_token_limit=profile["monthly_token_limit"],
                monthly_voice_minutes_limit=profile["monthly_voice_minutes_limit"],
                monthly_api_call_limit=profile["monthly_api_call_limit"],
                max_seats=profile["max_seats"],
                features_json={"plan_name": profile["name"], "max_concurrency": profile["max_concurrent_turns"]},
                created_at=now,
                updated_at=now
            )
            # Concurrent first requests (e.g. two dashboard calls) may both try to create the
            # row: insert inside a savepoint and re-read on the unique-constraint conflict.
            try:
                async with self.session.begin_nested():
                    self.session.add(sub)
                    await self.session.flush()
            except IntegrityError:
                sub = (await self.session.execute(stmt)).scalar_one()

        return sub

    async def get_or_create_monthly_meter(self, period_month: Optional[str] = None) -> TenantUsageMeter:
        """Retrieves or creates the usage meter record for the specified month (format 'YYYY-MM')."""
        if not period_month:
            period_month = datetime.now(timezone.utc).strftime("%Y-%m")

        stmt = select(TenantUsageMeter).where(
            and_(
                TenantUsageMeter.tenant_id == self.tenant_id,
                TenantUsageMeter.period_month == period_month
            )
        )
        meter = (await self.session.execute(stmt)).scalar_one_or_none()

        if not meter:
            meter = TenantUsageMeter(
                id=generate_uuid(),
                tenant_id=self.tenant_id,
                period_month=period_month,
                llm_input_tokens=0,
                llm_output_tokens=0,
                total_tokens=0,
                voice_seconds=0,
                api_requests_count=0,
                storage_bytes_used=0,
                active_users_count=1,
                last_updated_at=datetime.now(timezone.utc)
            )
            try:
                async with self.session.begin_nested():
                    self.session.add(meter)
                    await self.session.flush()
            except IntegrityError:
                meter = (await self.session.execute(stmt)).scalar_one()

        return meter

    async def check_quota_available(
        self,
        metric: str,  # 'tokens', 'voice_minutes', 'api_calls'
        units_requested: int = 1
    ) -> bool:
        """
        Validates whether the requested consumption is within the tenant's plan limits.
        Raises QuotaExhaustedError if hard cap is exceeded.
        """
        sub = await self.get_or_create_subscription()
        meter = await self.get_or_create_monthly_meter()

        if sub.status != "ACTIVE":
            raise QuotaExhaustedError(f"Tenant subscription is inactive (status: {sub.status}).")

        if metric == "tokens":
            current = meter.total_tokens
            limit = sub.monthly_token_limit
            if (current + units_requested) > limit:
                await self._trigger_quota_alert(metric, current, limit)
                raise QuotaExhaustedError(
                    f"Monthly LLM token quota exhausted ({current}/{limit} tokens). "
                    "Please upgrade your subscription plan to continue."
                )

        elif metric == "voice_minutes":
            current_minutes = meter.voice_seconds // 60
            limit_minutes = sub.monthly_voice_minutes_limit
            if (current_minutes + units_requested) > limit_minutes:
                await self._trigger_quota_alert(metric, current_minutes, limit_minutes)
                raise QuotaExhaustedError(
                    f"Monthly voice minutes quota exhausted ({current_minutes}/{limit_minutes} minutes). "
                    "Please upgrade your plan to continue."
                )

        elif metric == "api_calls":
            current = meter.api_requests_count
            limit = sub.monthly_api_call_limit
            if (current + units_requested) > limit:
                await self._trigger_quota_alert(metric, current, limit)
                raise QuotaExhaustedError(
                    f"Monthly API request quota exhausted ({current}/{limit} calls)."
                )

        return True

    async def record_usage(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        voice_seconds: int = 0,
        api_requests: int = 1
    ) -> TenantUsageMeter:
        """Atomically records consumption of platform resources in the monthly ledger."""
        meter = await self.get_or_create_monthly_meter()
        tot_tokens = prompt_tokens + completion_tokens

        meter.llm_input_tokens += prompt_tokens
        meter.llm_output_tokens += completion_tokens
        meter.total_tokens += tot_tokens
        meter.voice_seconds += voice_seconds
        meter.api_requests_count += api_requests
        meter.last_updated_at = datetime.now(timezone.utc)

        await self.session.flush()

        # Check for 80% soft warning threshold
        sub = await self.get_or_create_subscription()
        if sub.monthly_token_limit > 0:
            pct = (meter.total_tokens / sub.monthly_token_limit) * 100.0
            if pct >= 80.0:
                await self._trigger_quota_warning_if_needed("tokens", pct)

        return meter

    async def _trigger_quota_alert(self, metric: str, current: int, limit: int):
        """Dispatches an urgent CRITICAL alert when hard quota cap is hit."""
        alert = SystemAlertEvent(
            id=generate_uuid(),
            tenant_id=self.tenant_id,
            alert_id=f"QUOTA_EXHAUSTED_{metric.upper()}",
            severity="CRITICAL",
            source="SAAS_QUOTA",
            title=f"Tenant Quota Exhausted: {metric}",
            description=f"Monthly quota limit for {metric} reached ({current}/{limit}). Further operations blocked.",
            metadata_json={"metric": metric, "current": current, "limit": limit},
            status="ACTIVE",
            created_at=datetime.now(timezone.utc)
        )
        self.session.add(alert)
        await self.session.flush()

    async def _trigger_quota_warning_if_needed(self, metric: str, pct: float):
        """Dispatches a WARNING alert when tenant approaches 80% consumption threshold."""
        alert_id = f"QUOTA_WARNING_80_{metric.upper()}"
        # Avoid duplicate active warnings
        stmt = select(SystemAlertEvent).where(
            and_(
                SystemAlertEvent.tenant_id == self.tenant_id,
                SystemAlertEvent.alert_id == alert_id,
                SystemAlertEvent.status == "ACTIVE"
            )
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if not existing:
            alert = SystemAlertEvent(
                id=generate_uuid(),
                tenant_id=self.tenant_id,
                alert_id=alert_id,
                severity="WARNING",
                source="SAAS_QUOTA",
                title=f"Approaching Quota Limit: {metric} ({pct:.1f}%)",
                description=f"Tenant has consumed {pct:.1f}% of monthly {metric} quota.",
                metadata_json={"metric": metric, "consumed_pct": pct},
                status="ACTIVE",
                created_at=datetime.now(timezone.utc)
            )
            self.session.add(alert)
            await self.session.flush()

    async def get_usage_summary(self) -> Dict[str, Any]:
        """Returns complete usage and quota dashboard payload for management console."""
        sub = await self.get_or_create_subscription()
        meter = await self.get_or_create_monthly_meter()

        token_pct = round((meter.total_tokens / sub.monthly_token_limit * 100.0), 1) if sub.monthly_token_limit > 0 else 0.0
        voice_minutes = meter.voice_seconds // 60
        voice_pct = round((voice_minutes / sub.monthly_voice_minutes_limit * 100.0), 1) if sub.monthly_voice_minutes_limit > 0 else 0.0
        api_pct = round((meter.api_requests_count / sub.monthly_api_call_limit * 100.0), 1) if sub.monthly_api_call_limit > 0 else 0.0

        return {
            "tenant_id": self.tenant_id,
            "plan_id": sub.plan_id,
            "status": sub.status,
            "period_month": meter.period_month,
            "current_period_end": sub.current_period_end.isoformat(),
            "quotas": {
                "tokens": {
                    "used": meter.total_tokens,
                    "limit": sub.monthly_token_limit,
                    "percentage": token_pct,
                    "exhausted": meter.total_tokens >= sub.monthly_token_limit
                },
                "voice_minutes": {
                    "used": voice_minutes,
                    "limit": sub.monthly_voice_minutes_limit,
                    "percentage": voice_pct,
                    "exhausted": voice_minutes >= sub.monthly_voice_minutes_limit
                },
                "api_calls": {
                    "used": meter.api_requests_count,
                    "limit": sub.monthly_api_call_limit,
                    "percentage": api_pct,
                    "exhausted": meter.api_requests_count >= sub.monthly_api_call_limit
                },
                "seats": {
                    "used": meter.active_users_count,
                    "limit": sub.max_seats,
                    "percentage": round((meter.active_users_count / sub.max_seats * 100.0), 1) if sub.max_seats > 0 else 0.0,
                    "exhausted": meter.active_users_count >= sub.max_seats
                }
            }
        }

    async def adjust_quota_limit(
        self,
        metric_name: str,
        new_limit: int,
        reason: Optional[str] = None
    ) -> TenantQuotaLimit:
        """Adjusts or overrides a tenant's quota limit for a given metric."""
        stmt = select(TenantQuotaLimit).where(
            and_(
                TenantQuotaLimit.tenant_id == self.tenant_id,
                TenantQuotaLimit.metric_name == metric_name
            )
        )
        limit_entry = (await self.session.execute(stmt)).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if not limit_entry:
            limit_entry = TenantQuotaLimit(
                id=generate_uuid(),
                tenant_id=self.tenant_id,
                metric_name=metric_name,
                limit_value=new_limit,
                warning_threshold_pct=80,
                enforce_hard_cap=True,
                is_exhausted=False,
                created_at=now,
                updated_at=now
            )
            self.session.add(limit_entry)
        else:
            limit_entry.limit_value = new_limit
            limit_entry.updated_at = now
        limit_entry.adjustment_reason = reason
        await self.session.flush()
        return limit_entry
