"""
Channel Delivery Adapters for Notifications.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger("notifications.channels")


class BaseNotificationChannel:
    """Abstract interface for provider notification delivery."""
    async def deliver(
        self,
        recipient: str,
        content: str,
        subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        raise NotImplementedError


class EmailNotificationChannel(BaseNotificationChannel):
    """Simulated production SMTP / Email notification sender."""
    async def deliver(
        self,
        recipient: str,
        content: str,
        subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        # Validate email address basic format
        if "@" not in recipient or "." not in recipient:
            raise ValueError(f"Invalid email address: {recipient}")
        logger.info(f"[EMAIL DELIVERED] To: {recipient} | Subject: {subject} | Bytes: {len(content)}")
        return True


class WhatsAppNotificationChannel(BaseNotificationChannel):
    """Simulated WhatsApp Cloud API delivery adapter."""
    async def deliver(
        self,
        recipient: str,
        content: str,
        subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        # Validate phone format (+...)
        cleaned = recipient.replace(" ", "").replace("-", "")
        if not cleaned.startswith("+") and not cleaned.isdigit():
            raise ValueError(f"Invalid WhatsApp recipient phone number: {recipient}")
        logger.info(f"[WHATSAPP DELIVERED] To: {recipient} | Length: {len(content)}")
        return True


class InAppNotificationChannel(BaseNotificationChannel):
    """In-app operational alert dispatcher."""
    async def deliver(
        self,
        recipient: str,
        content: str,
        subject: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        logger.info(f"[IN_APP DELIVERED] Recipient: {recipient} | Subject: {subject}")
        return True


NOTIFICATION_CHANNELS: Dict[str, BaseNotificationChannel] = {
    "EMAIL": EmailNotificationChannel(),
    "WHATSAPP": WhatsAppNotificationChannel(),
    "IN_APP": InAppNotificationChannel()
}
