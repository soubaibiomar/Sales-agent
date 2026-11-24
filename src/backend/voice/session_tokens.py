"""
Signed customer voice session tokens (inspection findings F-01 / F-13).

Anonymous callers (web voice widget, PSTN) never get a user JWT, so they previously
identified their tenant with a client-controlled `X-Tenant-ID` header or query string.
A session token is issued by the server when the session is created (by an
authenticated caller or by a signature-verified telephony webhook) and binds
(tenant_id, session_id, expiry) with HMAC-SHA256. Only the server can mint it, so the
tenant is never taken from client input.
"""
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Optional

from src.backend.core.config import settings

TOKEN_VERSION = "v1"


class VoiceSessionTokenError(Exception):
    """Raised for missing, malformed, forged or expired voice session tokens."""


@dataclass(frozen=True)
class VoiceSessionClaims:
    tenant_id: str
    session_id: str
    expires_at: int


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload_b64: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"{TOKEN_VERSION}.{payload_b64}".encode("ascii"), hashlib.sha256).hexdigest()


def issue_voice_session_token(tenant_id: str, session_id: str, ttl_seconds: Optional[int] = None,
                              secret: Optional[str] = None) -> str:
    ttl = ttl_seconds if ttl_seconds is not None else settings.voice_session_token_ttl_seconds
    payload = {"t": tenant_id, "s": session_id, "exp": int(time.time()) + int(ttl)}
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{TOKEN_VERSION}.{payload_b64}.{_sign(payload_b64, secret or settings.voice_session_secret)}"


def verify_voice_session_token(token: Optional[str], secret: Optional[str] = None) -> VoiceSessionClaims:
    if not token:
        raise VoiceSessionTokenError("Missing voice session token.")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_VERSION:
        raise VoiceSessionTokenError("Malformed voice session token.")
    _, payload_b64, signature = parts
    expected = _sign(payload_b64, secret or settings.voice_session_secret)
    if not hmac.compare_digest(expected, signature):
        raise VoiceSessionTokenError("Invalid voice session token signature.")
    try:
        payload = json.loads(_b64d(payload_b64))
        claims = VoiceSessionClaims(tenant_id=str(payload["t"]), session_id=str(payload["s"]), expires_at=int(payload["exp"]))
    except Exception as exc:  # noqa: BLE001 - any decoding problem is a rejection
        raise VoiceSessionTokenError("Malformed voice session token payload.") from exc
    if claims.expires_at < int(time.time()):
        raise VoiceSessionTokenError("Voice session token has expired.")
    return claims
