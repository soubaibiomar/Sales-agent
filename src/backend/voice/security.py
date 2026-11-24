"""
Voice AI Security, Identity Verification, PII Redaction & High-Risk Guard.
Step 07: Dual-Mode Customer & Manager Voice AI
(Controls 04, 05, 06, 35, 39, 40, 48, 55, 65, 66; SAI-01, SAI-02, SAI-03, SAI-04, SAI-08)
"""
import re
import uuid
import time
import hmac
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple, List


class VoiceSecurityError(Exception):
    pass


class CallerUnverifiedError(VoiceSecurityError):
    """Raised when unverified caller attempts to access sensitive customer/order data."""
    pass


class PrivilegedActionConfirmationRequired(VoiceSecurityError):
    """Raised when a manager voice command requires second-factor MFA or explicit UI confirmation."""
    def __init__(self, action_preview: Dict[str, Any]):
        super().__init__("This high-risk management action requires explicit confirmation.")
        self.action_preview = action_preview


class PromptInjectionDetectedError(VoiceSecurityError):
    """Raised when an adversarial injection attempt is detected in transcribed audio."""
    pass


class VoicePIIRedactor:
    """
    Automated PII/PCI-DSS Redactor for Voice Transcripts.
    Redacts credit cards, Moroccan CINs, passwords, and verification PINs before storage.
    """
    # Credit cards: 13-19 digits, space or dash separated
    CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
    # Moroccan National ID (CIN): 1-2 uppercase letters + 5-7 digits
    CIN_PATTERN = re.compile(r"\b[A-Z]{1,2}\s?[0-9]{5,7}\b", re.IGNORECASE)
    # Generic password / pin declarations: e.g. "code 123456", "code est 123456", "mot de passe secret"
    PIN_PATTERN = re.compile(r"\b(?:code|pin|otp|mot de passe|password)(?:\s+est|[:\s]+)\s*([0-9a-zA-Z]{4,8})\b", re.IGNORECASE)

    @classmethod
    def redact_transcript(cls, text: str) -> str:
        if not text:
            return ""

        redacted = text

        # 1. Redact credit card numbers
        redacted = cls.CARD_PATTERN.sub("[REDACTED_CREDIT_CARD]", redacted)

        # 2. Redact Moroccan CIN
        redacted = cls.CIN_PATTERN.sub("[REDACTED_CIN]", redacted)

        # 3. Redact PINs & Passwords
        def replace_pin(match):
            full = match.group(0)
            val = match.group(1)
            return full.replace(val, "[REDACTED_PIN]")

        redacted = cls.PIN_PATTERN.sub(replace_pin, redacted)

        return redacted


class VoicePromptInjectionGuard:
    """
    Detects adversarial jailbreaks and prompt injections within spoken transcripts.
    Covers English, French, Modern Standard Arabic, Moroccan Darija, and Arabizi.
    (Controls 39, 40; SAI-10)
    """

    SUSPICIOUS_PATTERNS = [
        # English patterns
        re.compile(r"ignore\s+(all\s+)?(previous\s+|prior\s+)?instructions", re.IGNORECASE),
        re.compile(r"system\s+prompt", re.IGNORECASE),
        re.compile(r"developer\s+mode", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+dan", re.IGNORECASE),
        re.compile(r"grant\s+(me\s+)?(admin|superuser|role)", re.IGNORECASE),
        re.compile(r"bypass\s+(rls|security|permission)", re.IGNORECASE),
        re.compile(r"drop\s+table", re.IGNORECASE),
        re.compile(r"reveal\s+(system|secret|token)", re.IGNORECASE),
        # French patterns
        re.compile(r"ignore[rz]?\s+(toutes?\s+)?(les\s+)?(instructions|consignes)", re.IGNORECASE),
        re.compile(r"invite\s+syst[eè]me", re.IGNORECASE),
        re.compile(r"mode\s+d[eé]veloppeur", re.IGNORECASE),
        re.compile(r"donne[rz]?\s+(moi\s+)?(le\s+)?r[oô]le\s+admin", re.IGNORECASE),
        re.compile(r"contourne[rz]?\s+(la\s+)?s[eé]curit[eé]", re.IGNORECASE),
        # Arabic & Darija patterns
        re.compile(r"تجاهل\s+(كل\s+)?(التعليمات|الأوامر)", re.IGNORECASE),
        re.compile(r"تجاوز\s+(الأمان|الحماية|الصلاحيات)", re.IGNORECASE),
        re.compile(r"اعرض\s+(الكود|النظام|البرمجي|السر)", re.IGNORECASE),
        re.compile(r"سمح\s+ف\s+التعليمات", re.IGNORECASE),
        re.compile(r"عطيني\s+(لي\s+)?مودباس", re.IGNORECASE)
    ]

    @classmethod
    def inspect_transcript(cls, text: str) -> Tuple[bool, Optional[str]]:
        """Returns (is_safe, violation_reason)."""
        if not text:
            return True, None

        for pattern in cls.SUSPICIOUS_PATTERNS:
            if pattern.search(text):
                return False, f"Potential prompt injection pattern detected: '{pattern.pattern}'"

        return True, None


class VoiceIdentityVerificationManager:
    """
    Customer OTP challenges for caller verification (Control SAI-01, SAI-03).
    F-29: stored in PostgreSQL (`voice_otp_challenges`, RLS) so any API worker can verify
    a code issued by another one, and state survives restarts. Only an HMAC of the code is
    stored; codes are single-use, expire after 5 minutes and allow 3 attempts.
    """
    TTL_SECONDS = 300
    MAX_ATTEMPTS = 3

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _code_hash(tenant_id: str, session_id: str, code: str) -> str:
        from src.backend.core.config import settings
        msg = f"{tenant_id}:{session_id}:{code.strip()}".encode("utf-8")
        return hmac.new(settings.voice_session_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    async def generate_otp(self, tenant_id: str, session_id: str) -> str:
        """Creates (or replaces) the session's challenge and returns the plain code for delivery."""
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import delete
        from src.backend.models.entities import VoiceOtpChallenge
        code = f"{secrets.randbelow(900000) + 100000}"
        await self.db.execute(delete(VoiceOtpChallenge).where(
            VoiceOtpChallenge.tenant_id == tenant_id, VoiceOtpChallenge.session_id == session_id))
        self.db.add(VoiceOtpChallenge(
            tenant_id=tenant_id, session_id=session_id,
            code_hash=self._code_hash(tenant_id, session_id, code),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.TTL_SECONDS)
        ))
        await self.db.flush()
        return code

    async def discard(self, tenant_id: str, session_id: str) -> None:
        from sqlalchemy import delete
        from src.backend.models.entities import VoiceOtpChallenge
        await self.db.execute(delete(VoiceOtpChallenge).where(
            VoiceOtpChallenge.tenant_id == tenant_id, VoiceOtpChallenge.session_id == session_id))

    async def verify_otp(self, tenant_id: str, session_id: str, submitted_otp: str) -> bool:
        from datetime import datetime, timezone
        from sqlalchemy import select
        from src.backend.models.entities import VoiceOtpChallenge
        if not submitted_otp or not submitted_otp.strip().isdigit():
            return False
        ch = (await self.db.execute(select(VoiceOtpChallenge).where(
            VoiceOtpChallenge.tenant_id == tenant_id, VoiceOtpChallenge.session_id == session_id
        ).with_for_update())).scalars().first()
        if not ch or ch.consumed_at is not None:
            return False
        now = datetime.now(timezone.utc)
        expires = ch.expires_at if ch.expires_at.tzinfo else ch.expires_at.replace(tzinfo=timezone.utc)
        if now > expires or ch.attempts >= self.MAX_ATTEMPTS:
            return False
        ch.attempts += 1
        ok = hmac.compare_digest(ch.code_hash, self._code_hash(tenant_id, session_id, submitted_otp))
        if ok:
            ch.consumed_at = now
        await self.db.flush()
        return ok


class ManagerPrivilegedActionGuard:
    """
    Guards manager voice commands from executing high-risk mutations without second-factor.
    (Control 55; SAI-02, Invariant 6)
    F-29: previews live in PostgreSQL (`manager_action_previews`, RLS): single-use,
    bound to tenant + user, 5-minute expiry, valid across API workers.
    """
    # Thresholds requiring step-up confirmation
    MAX_UNCONFIRMED_DISCOUNT_PERCENT = 25
    MAX_UNCONFIRMED_REFUND_CENTS = 500000       # 5,000 MAD
    MAX_UNCONFIRMED_PO_CENTS = 5000000          # 50,000 MAD
    TTL_SECONDS = 300

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _as_dict(p) -> Dict[str, Any]:
        expires = p.expires_at
        return {
            "action_token": p.id,
            "tenant_id": p.tenant_id,
            "user_id": p.user_id,
            "action_type": p.action_type,
            "requires_step_up_mfa": p.requires_step_up_mfa,
            "risk_level": p.risk_level,
            "parameters": p.parameters or {},
            "summary": p.summary,
            "expires_at_ms": int(expires.timestamp() * 1000) if expires else None,
        }

    async def create_action_preview(
        self,
        tenant_id: str,
        user_id: str,
        action_type: str,
        parameters: Dict[str, Any],
        summary: str,
        risk_level: str = "HIGH"
    ) -> Dict[str, Any]:
        """Creates a time-bounded action preview requiring confirmation."""
        from datetime import datetime, timedelta, timezone
        from src.backend.models.entities import ManagerActionPreview
        preview = ManagerActionPreview(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id, action_type=action_type,
            parameters=parameters or {}, summary=summary, risk_level=risk_level,
            requires_step_up_mfa=(risk_level == "HIGH"),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.TTL_SECONDS)
        )
        self.db.add(preview)
        await self.db.flush()
        return self._as_dict(preview)

    async def consume_action(
        self,
        action_token: str,
        *,
        tenant_id: str,
        user_id: str,
        step_up_verified: bool
    ) -> Dict[str, Any]:
        """
        F-06/F-29: consumes a pending high-risk action only when the token belongs to the
        same tenant AND user, is unexpired and unused, and the second factor was verified
        server-side by the caller. A failed second factor does not consume it.
        """
        from datetime import datetime, timezone
        from sqlalchemy import select
        from src.backend.models.entities import ManagerActionPreview
        p = (await self.db.execute(select(ManagerActionPreview).where(
            ManagerActionPreview.id == action_token, ManagerActionPreview.tenant_id == tenant_id
        ).with_for_update())).scalars().first()
        now = datetime.now(timezone.utc)
        if not p or p.consumed_at is not None:
            raise VoiceSecurityError("Action preview not found or expired.")
        expires = p.expires_at if p.expires_at.tzinfo else p.expires_at.replace(tzinfo=timezone.utc)
        if now > expires:
            raise VoiceSecurityError("Action preview not found or expired.")
        if p.user_id != user_id:
            raise VoiceSecurityError("Action preview was not issued to this user.")
        if p.requires_step_up_mfa and not step_up_verified:
            raise VoiceSecurityError("Valid Step-Up TOTP code required for this high-risk action.")
        p.consumed_at = now
        await self.db.flush()
        return self._as_dict(p)
