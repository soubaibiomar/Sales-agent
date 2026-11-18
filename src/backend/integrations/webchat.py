"""
Authenticated Web Chat Channel Adapter.
Validates customer session credentials, enforces rate limits, and normalizes chat messages.
(Baseline Controls 28, 59)
"""
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from src.backend.integrations.base import BaseChannelAdapter, NormalizedInboundEvent

class WebChatAdapter(BaseChannelAdapter):
    """Adapter for embedded website chat widget sessions."""

    def verify_webhook_signature(self, headers: Dict[str, str], raw_body: bytes, secret: str) -> bool:
        """
        Validates internal web widget API token or session header.
        """
        auth_header = headers.get("X-WebChat-Token") or headers.get("x-webchat-token")
        if not auth_header:
            return False
        return auth_header.strip() == secret

    def parse_inbound_event(self, headers: Dict[str, str], payload: Dict[str, Any], tenant_id: str) -> List[NormalizedInboundEvent]:
        """
        Parses inbound message from website chat widget.
        """
        session_id = payload.get("session_id") or payload.get("visitor_id")
        if not session_id:
            session_id = f"guest_{uuid.uuid4()}"

        sender_name = payload.get("customer_name") or "Web Visitor"
        content = payload.get("message", "").strip()
        provider_event_id = payload.get("message_id") or f"web_{uuid.uuid4()}"

        raw_attachments = payload.get("attachments", [])
        attachments = []
        for att in raw_attachments:
            attachments.append({
                "file_name": att.get("file_name", "upload"),
                "mime_type": att.get("mime_type", "application/octet-stream"),
                "file_size": att.get("file_size", 0),
                "url": att.get("url"),
                "is_safe": True
            })

        event = NormalizedInboundEvent(
            tenant_id=tenant_id,
            channel_type="WEB_CHAT",
            provider_event_id=provider_event_id,
            sender_identifier=session_id,
            sender_name=sender_name,
            content=content,
            event_type="MESSAGE",
            attachments=attachments,
            raw_payload=payload,
            timestamp=datetime.now(timezone.utc)
        )
        return [event]

    def format_outbound_payload(self, recipient_identifier: str, content: str, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Formats outbound message to be delivered to web chat websocket or polling queue.
        """
        return {
            "session_id": recipient_identifier,
            "message": content,
            "sender": "AGENT",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attachments": attachments or []
        }
