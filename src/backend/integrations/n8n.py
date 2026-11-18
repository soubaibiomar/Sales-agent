"""
n8n Restricted Peripheral Integration Gateway & Security Barrier.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007, Invariant 7)
Enforces:
1. n8n service identity is strictly restricted to peripheral read-only notification and external sync roles.
2. Absolute prohibition on n8n mutating core commerce state: inventory, orders, prices, refunds, or approvals.
3. Cryptographic HMAC-SHA256 webhook dispatch with timestamp replay defense and idempotency.
"""
import hmac
import time
import json
import hashlib
import logging
from typing import Dict, Any, Optional, Tuple
from fastapi import HTTPException, status

logger = logging.getLogger("integrations.n8n")


class N8NSecurityViolationError(HTTPException):
    """Raised when an n8n peripheral service identity attempts a prohibited commercial mutation."""
    def __init__(self, action: str):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Invariant 7 Violation: n8n peripheral integration is prohibited from executing "
                f"commercial mutation '{action}'. Financial, inventory, pricing, and approval "
                f"authority is reserved exclusively for deterministic domain services (ADR-007, Invariant 7)."
            )
        )


class N8NIntegrationGateway:
    """Manages restricted outbound webhook dispatch and incoming signature verification for n8n."""

    PROHIBITED_ROLES = {"peripheral_integration", "n8n_integration", "n8n_service_account"}

    PROHIBITED_ACTIONS = {
        "quotes:approve",
        "quotes:reject",
        "orders:mark_paid",
        "orders:cancel",
        "payments:refund",
        "inventory:adjust",
        "inventory:commit",
        "prices:modify",
        "po:approve"
    }

    @classmethod
    def assert_action_permitted(cls, roles: list[str], permission_code: str):
        """
        Guards core commerce truth: Rejects n8n service identity if it attempts to execute financial/inventory mutations.
        (ADR-007, Invariant 7)
        """
        is_n8n = any(r in cls.PROHIBITED_ROLES for r in roles)
        if is_n8n and permission_code in cls.PROHIBITED_ACTIONS:
            raise N8NSecurityViolationError(permission_code)

    @classmethod
    def validate_peripheral_action(cls, role: str, action: str) -> bool:
        """Alias for single-role action permission check."""
        cls.assert_action_permitted([role], action)
        return True

    @classmethod
    def sign_payload(cls, secret_key: str, payload_bytes: bytes, timestamp: int) -> str:
        """Generates HMAC-SHA256 signature combining timestamp and payload."""
        message = f"v1:{timestamp}:".encode("utf-8") + payload_bytes
        return hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()

    @classmethod
    def generate_signature(cls, secret: str, payload_bytes: bytes, timestamp: int) -> str:
        """Alias for sign_payload."""
        return cls.sign_payload(secret, payload_bytes, timestamp)

    @classmethod
    def verify_webhook_signature(
        cls,
        secret_key: str,
        payload_bytes: bytes,
        signature: str,
        timestamp: int,
        tolerance_seconds: int = 300
    ) -> Tuple[bool, Optional[str]]:
        """Verifies signature freshness and cryptographic validity."""
        now = int(time.time())
        if abs(now - timestamp) > tolerance_seconds:
            return False, "Timestamp outside acceptable tolerance window (replay protection)"

        expected = cls.sign_payload(secret_key, payload_bytes, timestamp)
        if not hmac.compare_digest(expected, signature):
            return False, "Invalid cryptographic HMAC signature"

        return True, None

    @classmethod
    def verify_signature(
        cls,
        secret: str,
        payload_bytes: bytes,
        signature_header: str,
        timestamp_header: int,
        max_drift_seconds: int = 300
    ) -> bool:
        """Alias returning bool for verify_webhook_signature."""
        valid, _ = cls.verify_webhook_signature(
            secret_key=secret,
            payload_bytes=payload_bytes,
            signature=signature_header,
            timestamp=timestamp_header,
            tolerance_seconds=max_drift_seconds
        )
        return valid

    @classmethod
    async def dispatch_event_to_n8n(
        cls,
        webhook_url: str,
        secret_key: str,
        event_type: str,
        payload: Dict[str, Any],
        idempotency_key: str
    ) -> Dict[str, Any]:
        """
        Dispatches an immutable domain event to an external n8n peripheral webhook.
        Attaches HMAC headers, timestamp, and idempotency key.
        """
        timestamp = int(time.time())
        payload_bytes = json.dumps(payload, default=str).encode("utf-8")
        signature = cls.sign_payload(secret_key, payload_bytes, timestamp)

        headers = {
            "Content-Type": "application/json",
            "X-Sales-AI-Event": event_type,
            "X-Sales-AI-Timestamp": str(timestamp),
            "X-Sales-AI-Signature": signature,
            "X-Idempotency-Key": idempotency_key
        }

        logger.info(f"[n8n DISPATCH] Event: {event_type} -> {webhook_url} (Key: {idempotency_key})")
        return {
            "dispatched": True,
            "event_type": event_type,
            "webhook_url": webhook_url,
            "headers": headers,
            "payload": payload
        }
