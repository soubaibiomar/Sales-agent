"""
Tests for Omnichannel Notification Orchestrator, Moroccan Quiet Hours,
Multi-Script STOP Opt-Outs, and Frequency Capping.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
import pytest
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from src.backend.models.entities import Base, Tenant, NotificationLog, NotificationTemplate
from src.backend.notifications.orchestrator import (
    NotificationOrchestrator,
    QuietHoursPolicy,
    MultiScriptOptOutManager
)
from src.backend.notifications.templates import render_template_string, DEFAULT_TEMPLATES


@asynccontextmanager
async def get_notify_test_db():
    unique_id = uuid.uuid4().hex
    engine = create_async_engine(
        f"sqlite+aiosqlite:///file:memdb_notify_{unique_id}?mode=memory&cache=shared&uri=true",
        echo=False
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tenant_id = "tenant_notify_test"
    async with session_factory() as session:
        tenant = Tenant(id=tenant_id, name="Notification Tenant", slug=f"notify-tenant-{unique_id}")
        session.add(tenant)
        await session.commit()

    async with session_factory() as session:
        yield {"session": session, "tenant_id": tenant_id}

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def test_template_variable_substitution():
    """Verifies that templates render placeholders correctly in both {{var}} and {var} syntax."""
    template = "Salam {{customer_name}}, your order #{{order_id}} of {total_amount} is ready."
    rendered = render_template_string(template, {
        "customer_name": "Yassine",
        "order_id": "ORD-123",
        "total_amount": "450 MAD"
    })
    assert rendered == "Salam Yassine, your order #ORD-123 of 450 MAD is ready."


def test_moroccan_quiet_hours_detection():
    """
    Verifies that Moroccan quiet hours policy flags 21:00-09:00 and all day Sunday,
    while allowing 09:00-21:00 Monday-Saturday.
    """
    # Wednesday 14:00 (Business hours) -> Not quiet hours
    wed_afternoon = datetime(2026, 11, 18, 14, 0, 0, tzinfo=timezone.utc)
    assert QuietHoursPolicy.is_quiet_hours(wed_afternoon) is False

    # Wednesday 22:30 (Night) -> Quiet hours
    wed_night = datetime(2026, 11, 18, 22, 30, 0, tzinfo=timezone.utc)
    assert QuietHoursPolicy.is_quiet_hours(wed_night) is True

    # Wednesday 07:15 (Early morning) -> Quiet hours
    wed_morning = datetime(2026, 11, 18, 7, 15, 0, tzinfo=timezone.utc)
    assert QuietHoursPolicy.is_quiet_hours(wed_morning) is True

    # Sunday 12:00 -> Quiet hours (Whole day restricted for marketing)
    sunday_noon = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    assert QuietHoursPolicy.is_quiet_hours(sunday_noon) is True


def test_multiscript_stop_opt_out_keywords():
    """
    Verifies that multi-script opt-out manager catches English, French,
    Arabic, and Moroccan Darija (Arabizi) stop keywords.
    """
    # English / French
    is_opt, kw = MultiScriptOptOutManager.is_opt_out_phrase("STOP sending messages please")
    assert is_opt is True
    assert kw == "stop"

    is_opt, kw = MultiScriptOptOutManager.is_opt_out_phrase("Arretez svp")
    assert is_opt is True
    assert kw == "arretez"

    # Moroccan Darija (Arabizi)
    is_opt, kw = MultiScriptOptOutManager.is_opt_out_phrase("Baraka 3likom ma bghitch")
    assert is_opt is True
    assert kw == "baraka"

    is_opt, kw = MultiScriptOptOutManager.is_opt_out_phrase("Hbsou el rassayel")
    assert is_opt is True
    assert kw in ("hbsou", "hbs")

    # Arabic script
    is_opt, kw = MultiScriptOptOutManager.is_opt_out_phrase("قف عن إرسال الرسائل")
    assert is_opt is True
    assert kw == "قف"

    # Normal inquiry (not opt-out)
    is_opt, _ = MultiScriptOptOutManager.is_opt_out_phrase("Bonjour, quel est le prix du pc ?")
    assert is_opt is False


@pytest.mark.asyncio
async def test_marketing_suppressed_by_opt_out():
    """
    Verifies that once a recipient opts out, marketing messages are SUPPRESSED,
    while TRANSACTIONAL messages are still DELIVERED.
    """
    async with get_notify_test_db() as db_ctx:
        session = db_ctx["session"]
        tenant_id = db_ctx["tenant_id"]
        recipient = "+212611998877"

        # Record opt-out
        await MultiScriptOptOutManager.record_opt_out(
            tenant_id=tenant_id,
            recipient=recipient,
            channel="WHATSAPP",
            keyword="baraka"
        )

        orchestrator = NotificationOrchestrator(session)

        # 1. Attempt MARKETING send -> must be CANCELLED (Suppressed)
        log_mkt = await orchestrator.send_notification(
            tenant_id=tenant_id,
            recipient=recipient,
            channel="WHATSAPP",
            message_class="MARKETING",
            template_name="MARKETING_PROMOTION",
            variables={"promo_code": "PROMO20", "discount": "20%"}
        )
        assert log_mkt.status in ("CANCELLED", "SUPPRESSED")
        assert "Opted out" in log_mkt.error_reason

        # 2. Attempt TRANSACTIONAL send -> must be DELIVERED (bypasses marketing opt-out)
        log_tx = await orchestrator.send_notification(
            tenant_id=tenant_id,
            recipient=recipient,
            channel="WHATSAPP",
            message_class="TRANSACTIONAL",
            template_name="ORDER_CONFIRMED",
            variables={"order_id": "ORD-777", "total": "500 MAD"}
        )
        assert log_tx.status in ("DELIVERED", "SENT")


@pytest.mark.asyncio
async def test_frequency_capping_suppresses_rapid_marketing():
    """
    Verifies that the orchestrator enforces frequency capping (max 1 marketing message / 24 hours).
    """
    async with get_notify_test_db() as db_ctx:
        session = db_ctx["session"]
        tenant_id = db_ctx["tenant_id"]
        recipient = "+212622334455"

        orchestrator = NotificationOrchestrator(session)

        # Create a prior sent log within 2 hours
        log_existing = NotificationLog(
            id=f"log-{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            recipient_identifier=recipient,
            channel_type="WHATSAPP",
            message_class="MARKETING",
            content="Earlier marketing promo",
            status="DELIVERED",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2)
        )
        session.add(log_existing)
        await session.commit()

        # Second send within 24h during daytime business hours -> must be SUPPRESSED by frequency cap
        daytime = datetime(2026, 11, 18, 14, 0, 0, tzinfo=timezone.utc)
        log_second = await orchestrator.send_notification(
            tenant_id=tenant_id,
            recipient=recipient,
            channel="WHATSAPP",
            message_class="MARKETING",
            template_name="MARKETING_PROMOTION",
            variables={"promo_code": "SECOND", "discount": "10%"},
            now=daytime
        )
        assert log_second.status in ("CANCELLED", "SUPPRESSED")
        assert "Frequency cap" in log_second.error_reason
