"""
HMAC-signed capability links for public customer actions (inspection finding F-14).

A link carries a purpose, the tenant, the resource id, the resource version and an
expiry, signed with a server secret. Public endpoints derive the tenant from a verified
link (never from client input), so they also work under Row-Level Security, and any
change to the resource version (e.g. quote terms edited) invalidates older links.
"""
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Optional

from src.backend.core.config import settings


class SignedLinkError(Exception):
    """Missing, forged, expired or mismatched link token."""


@dataclass(frozen=True)
class SignedLinkClaims:
    purpose: str
    tenant_id: str
    resource_id: str
    version: int
    expires_at: int


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(body: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()


def issue_link_token(purpose: str, tenant_id: str, resource_id: str, version: int,
                     ttl_seconds: int, secret: Optional[str] = None) -> str:
    payload = {"p": purpose, "t": tenant_id, "r": resource_id, "v": int(version), "exp": int(time.time()) + int(ttl_seconds)}
    body = _b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{body}.{_mac(body, secret or settings.quote_link_secret)}"


def verify_link_token(token: Optional[str], purpose: str, resource_id: str,
                      secret: Optional[str] = None) -> SignedLinkClaims:
    if not token or token.count(".") != 1:
        raise SignedLinkError("Missing or malformed link token.")
    body, mac = token.split(".")
    if not hmac.compare_digest(_mac(body, secret or settings.quote_link_secret), mac):
        raise SignedLinkError("Invalid link token signature.")
    try:
        p = json.loads(_b64d(body))
        claims = SignedLinkClaims(purpose=p["p"], tenant_id=p["t"], resource_id=p["r"], version=int(p["v"]), expires_at=int(p["exp"]))
    except Exception as exc:  # noqa: BLE001
        raise SignedLinkError("Malformed link token payload.") from exc
    if claims.purpose != purpose or claims.resource_id != resource_id:
        raise SignedLinkError("Link token is not valid for this resource.")
    if claims.expires_at < int(time.time()):
        raise SignedLinkError("Link token has expired.")
    return claims
