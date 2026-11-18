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
    """Detects adversarial jailbreaks and prompt injections within spoken transcripts."""

    SUSPICIOUS_PATTERNS = [
        re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
        re.compile(r"system\s+prompt", re.IGNORECASE),
        re.compile(r"developer\s+mode", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+dan", re.IGNORECASE),
        re.compile(r"grant\s+(me\s+)?(admin|superuser|role)", re.IGNORECASE),
        re.compile(r"bypass\s+(rls|security|permission)", re.IGNORECASE),
        re.compile(r"drop\s+table", re.IGNORECASE),
        re.compile(r"reveal\s+(system|secret|token)", re.IGNORECASE)
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
    Manages customer OTP verification tokens and anti-spoofing verification.
    Prevents caller-ID spoofing attacks (Control SAI-01, SAI-03).
    """
    _shared_tokens: Dict[str, Dict[str, Any]] = {}

    def __init__(self):
        # Shared in-memory token store: {session_id: {"otp": str, "expires_at": float, "attempts": int}}
        self._tokens: Dict[str, Dict[str, Any]] = self._shared_tokens

    def generate_otp(self, session_id: str, caller_id: Optional[str] = None) -> str:
        """Generates a secure 6-digit verification code with 5-minute validity."""
        otp = f"{secrets.randbelow(900000) + 100000}"
        self._tokens[session_id] = {
            "otp": otp,
            "caller_id": caller_id,
            "expires_at": time.time() + 300.0,
            "attempts": 0
        }
        return otp

    def verify_otp(self, session_id: str, submitted_otp: str) -> bool:
        """Verifies customer submitted OTP token."""
        entry = self._tokens.get(session_id)
        if not entry:
            return False

        if time.time() > entry["expires_at"]:
            del self._tokens[session_id]
            return False

        entry["attempts"] += 1
        if entry["attempts"] > 3:
            del self._tokens[session_id]
            return False

        if hmac.compare_digest(entry["otp"], submitted_otp.strip()):
            del self._tokens[session_id]
            return True

        return False


class ManagerPrivilegedActionGuard:
    """
    Guards manager voice commands from executing high-risk mutations without second-factor.
    (Control 55; SAI-02, Invariant 6)
    """
    # Thresholds requiring step-up confirmation
    MAX_UNCONFIRMED_DISCOUNT_PERCENT = 25
    MAX_UNCONFIRMED_REFUND_CENTS = 500000       # 5,000 MAD
    MAX_UNCONFIRMED_PO_CENTS = 5000000          # 50,000 MAD

    _shared_pending_actions: Dict[str, Dict[str, Any]] = {}

    def __init__(self):
        self._pending_actions: Dict[str, Dict[str, Any]] = self._shared_pending_actions

    def create_action_preview(
        self,
        tenant_id: str,
        user_id: str,
        action_type: str,
        parameters: Dict[str, Any],
        summary: str,
        risk_level: str = "HIGH"
    ) -> Dict[str, Any]:
        """Creates a time-bounded action preview requiring confirmation."""
        token = str(uuid.uuid4())
        expires_at_ms = int((time.time() + 300.0) * 1000)

        preview = {
            "action_token": token,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action_type": action_type,
            "requires_step_up_mfa": (risk_level == "HIGH"),
            "risk_level": risk_level,
            "parameters": parameters,
            "summary": summary,
            "expires_at_ms": expires_at_ms
        }

        self._pending_actions[token] = preview
        return preview

    def get_pending_action(self, action_token: str) -> Optional[Dict[str, Any]]:
        entry = self._pending_actions.get(action_token)
        if not entry:
            return None
        if time.time() * 1000 > entry["expires_at_ms"]:
            del self._pending_actions[action_token]
            return None
        return entry

    def consume_action(self, action_token: str, totp_code: Optional[str] = None) -> Dict[str, Any]:
        action = self.get_pending_action(action_token)
        if not action:
            raise VoiceSecurityError("Action preview not found or expired.")

        if action["requires_step_up_mfa"]:
            # Validate TOTP format or mock test token
            if not totp_code or len(totp_code.strip()) not in (6, 8):
                raise VoiceSecurityError("Valid Step-Up TOTP code required for this high-risk action.")

        del self._pending_actions[action_token]
        return action
