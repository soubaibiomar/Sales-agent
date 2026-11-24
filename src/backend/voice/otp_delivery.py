"""
Out-of-band OTP delivery for customer voice verification (inspection finding F-05).

Verification codes must reach the customer through a channel the attacker does not
control (SMS / WhatsApp to the number on file). No provider is integrated yet, so the
default adapter refuses to deliver: verification then fails closed instead of falling
back to a static code. Deployments register a real adapter at startup; tests register
a capturing adapter.
"""
from typing import Optional, Protocol


class OtpDeliveryUnavailableError(Exception):
    """Raised when no OTP delivery provider is configured."""


class OtpDeliveryAdapter(Protocol):
    async def deliver(self, tenant_id: str, recipient: str, code: str, session_id: str) -> None: ...


class UnconfiguredOtpDelivery:
    async def deliver(self, tenant_id: str, recipient: str, code: str, session_id: str) -> None:
        raise OtpDeliveryUnavailableError(
            "No OTP delivery provider (SMS/WhatsApp) is configured; caller verification is unavailable."
        )


_adapter: OtpDeliveryAdapter = UnconfiguredOtpDelivery()


def register_otp_delivery_adapter(adapter: Optional[OtpDeliveryAdapter]) -> None:
    """Registers the process-wide OTP delivery adapter (None restores the fail-closed default)."""
    global _adapter
    _adapter = adapter or UnconfiguredOtpDelivery()


def get_otp_delivery_adapter() -> OtpDeliveryAdapter:
    return _adapter
