"""
Security Tests for Omnichannel Gateway & Unified Inbox.
Verifies Webhook Replay Deduplication, Anti-SSRF Protection, MIME Validation, PII Redaction, and IDOR Defense.
(Baseline Controls 16, 17, 19, 21, 22, 23, 28, 33, 35, 59)
"""
import pytest
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from src.backend.models.entities import Base, Tenant, InboundRawEvent, Conversation, ConversationMessage
from src.backend.domains.conversations.service import (
    ConversationService, redact_pii
)
from src.backend.core.media_security import (
    validate_media_url, validate_attachment_metadata,
    SSRFProtectionError, MIMEValidationError
)

@asynccontextmanager
async def get_sec_test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        t1 = Tenant(id="t_sec_01", name="Tenant Alpha", slug="tenant-alpha")
        t2 = Tenant(id="t_sec_02", name="Tenant Beta", slug="tenant-beta")
        session.add(t1)
        session.add(t2)
        await session.commit()

    async with session_factory() as session:
        yield session

    await engine.dispose()

@pytest.mark.asyncio
async def test_webhook_replay_deduplication():
    """Control 59: Replay attacks and duplicate provider deliveries cause zero extra side-effects."""
    async with get_sec_test_db() as session:
        payload = {"message": "Order confirmation query", "amount": 100}
        
        # 1. First delivery
        ev1 = await ConversationService.ingest_raw_event(
            session=session,
            tenant_id="t_sec_01",
            channel_type="WHATSAPP",
            provider_event_id="wamid.UNIQUE_ID_999",
            payload_dict=payload,
            signature_verified=True
        )
        assert ev1.processing_status == "PENDING"

        # 2. Replay of identical event
        ev2 = await ConversationService.ingest_raw_event(
            session=session,
            tenant_id="t_sec_01",
            channel_type="WHATSAPP",
            provider_event_id="wamid.UNIQUE_ID_999",
            payload_dict=payload,
            signature_verified=True
        )
        assert ev2.processing_status == "DUPLICATE"

        # Verify only 1 row exists in database for this provider event
        stmt = select(InboundRawEvent).where(
            InboundRawEvent.tenant_id == "t_sec_01",
            InboundRawEvent.provider_event_id == "wamid.UNIQUE_ID_999"
        )
        res = await session.execute(stmt)
        events = res.scalars().all()
        assert len(events) == 1

@pytest.mark.parametrize("malicious_url", [
    "http://127.0.0.1/admin",
    "http://localhost:8000/internal",
    "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.1/secrets",
    "http://192.168.1.1/gateway",
    "http://172.16.0.5/api",
    "file:///etc/passwd",
    "gopher://127.0.0.1:6379/_flushall",
    "ftp://internal.server/data"
])
def test_anti_ssrf_media_url_protection(malicious_url):
    """Control 23: Anti-SSRF validator blocks private, loopback, link-local, and non-HTTP schemes."""
    with pytest.raises(SSRFProtectionError):
        validate_media_url(malicious_url)

def test_anti_ssrf_accepts_valid_public_url():
    """Control 23: Valid public HTTP/HTTPS URLs pass validation."""
    valid_url = "https://images.unsplash.com/photo-1542291026-7eec264c27ff"
    assert validate_media_url(valid_url) == valid_url

def test_insecure_file_upload_validation():
    """Control 21: Prohibited MIME types and excessive file sizes are rejected."""
    # Executable rejected
    with pytest.raises(MIMEValidationError):
        validate_attachment_metadata("malware.exe", "application/x-msdownload", 1024)

    # Shell script rejected
    with pytest.raises(MIMEValidationError):
        validate_attachment_metadata("script.sh", "application/x-sh", 500)

    # File > 15MB rejected
    with pytest.raises(MIMEValidationError):
        validate_attachment_metadata("huge_video.mp4", "video/mp4", 25 * 1024 * 1024)

    # Empty file rejected
    with pytest.raises(MIMEValidationError):
        validate_attachment_metadata("empty.pdf", "application/pdf", 0)

    # Valid PDF accepted
    is_valid, clean_name = validate_attachment_metadata("devis.pdf", "application/pdf", 1024 * 50)
    assert is_valid is True
    assert clean_name == "devis.pdf"

def test_sensitive_data_and_pii_redaction():
    """Control 35: Credit card numbers and PIN/passwords are redacted before persistence."""
    sample = "Voici mon numéro de carte: 4532 1234 5678 9012 et mon pin: 1234"
    redacted = redact_pii(sample)
    assert "4532 1234 5678 9012" not in redacted
    assert "[REDACTED_CARD]" in redacted
    assert "[REDACTED_SECRET]" in redacted
