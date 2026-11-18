"""
Base Channel Adapter Interface and Normalized Inbound Event Models.
(Step 03 Omnichannel Architecture)
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

@dataclass
class NormalizedInboundEvent:
    tenant_id: str
    channel_type: str  # WEB_CHAT, WHATSAPP, EMAIL, VOICE_SIP
    provider_event_id: str
    sender_identifier: str  # Phone number, email address, or web session UUID
    content: str
    sender_name: Optional[str] = None
    event_type: str = "MESSAGE"  # MESSAGE, STATUS, CONSENT_STOP, HANDOFF_REQUEST
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class BaseChannelAdapter(ABC):
    """Abstract base class for all omnichannel provider adapters."""

    @abstractmethod
    def verify_webhook_signature(self, headers: Dict[str, str], raw_body: bytes, secret: str) -> bool:
        """Verifies cryptographic signature of incoming provider webhook payload."""
        pass

    @abstractmethod
    def parse_inbound_event(self, headers: Dict[str, str], payload: Dict[str, Any], tenant_id: str) -> List[NormalizedInboundEvent]:
        """Normalizes provider-specific webhook into standard NormalizedInboundEvents."""
        pass

    @abstractmethod
    def format_outbound_payload(self, recipient_identifier: str, content: str, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Formats an outgoing normalized message into provider-specific API payload."""
        pass
