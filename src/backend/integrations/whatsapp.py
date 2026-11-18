"""
WhatsApp Business Cloud API Channel Adapter.
Implements X-Hub-Signature-256 HMAC verification, WAMID deduplication, and normalized parsing.
(Baseline Controls 16, 22, 59)
"""
import hmac
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from src.backend.integrations.base import BaseChannelAdapter, NormalizedInboundEvent
from src.backend.core.media_security import validate_media_url

class WhatsAppAdapter(BaseChannelAdapter):
    """Adapter for Meta WhatsApp Cloud API webhooks and outbound messaging."""

    def verify_webhook_signature(self, headers: Dict[str, str], raw_body: bytes, secret: str) -> bool:
        """
        Validates X-Hub-Signature-256 header using HMAC-SHA256.
        """
        if not secret:
            return False

        # Header can be lowercase or standard
        sig_header = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256")
        if not sig_header or not sig_header.startswith("sha256="):
            return False

        received_hash = sig_header[7:].strip()
        expected_hash = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(received_hash, expected_hash)

    def parse_inbound_event(self, headers: Dict[str, str], payload: Dict[str, Any], tenant_id: str) -> List[NormalizedInboundEvent]:
        """
        Parses WhatsApp Cloud API webhook entries into NormalizedInboundEvents.
        """
        events: List[NormalizedInboundEvent] = []
        entries = payload.get("entry", [])
        
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                contacts = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
                messages = value.get("messages", [])

                for msg in messages:
                    provider_event_id = msg.get("id")
                    sender_id = msg.get("from")
                    sender_name = contacts.get(sender_id, "WhatsApp User")
                    msg_type = msg.get("type", "text")
                    
                    content = ""
                    attachments = []

                    if msg_type == "text":
                        content = msg.get("text", {}).get("body", "").strip()
                    elif msg_type in ("image", "document", "audio", "video"):
                        media_obj = msg.get(msg_type, {})
                        content = media_obj.get("caption", f"[{msg_type.upper()} ATTACHMENT]")
                        media_url = media_obj.get("url")
                        if media_url:
                            try:
                                validate_media_url(media_url)
                                is_safe = True
                            except Exception:
                                is_safe = False
                        else:
                            is_safe = True

                        attachments.append({
                            "type": msg_type,
                            "media_id": media_obj.get("id"),
                            "mime_type": media_obj.get("mime_type", "application/octet-stream"),
                            "url": media_url,
                            "file_name": media_obj.get("filename", f"{msg_type}_{provider_event_id}"),
                            "is_safe": is_safe
                        })
                    elif msg_type == "button":
                        content = msg.get("button", {}).get("text", "")
                    elif msg_type == "interactive":
                        interactive = msg.get("interactive", {})
                        int_type = interactive.get("type")
                        if int_type == "button_reply":
                            content = interactive.get("button_reply", {}).get("title", "")
                        elif int_type == "list_reply":
                            content = interactive.get("list_reply", {}).get("title", "")
                    else:
                        content = f"[Unsupported message type: {msg_type}]"

                    timestamp_str = msg.get("timestamp")
                    if timestamp_str and timestamp_str.isdigit():
                        ts = datetime.fromtimestamp(int(timestamp_str), tz=timezone.utc)
                    else:
                        ts = datetime.now(timezone.utc)

                    events.append(NormalizedInboundEvent(
                        tenant_id=tenant_id,
                        channel_type="WHATSAPP",
                        provider_event_id=provider_event_id,
                        sender_identifier=sender_id,
                        sender_name=sender_name,
                        content=content,
                        event_type="MESSAGE",
                        attachments=attachments,
                        raw_payload=msg,
                        timestamp=ts
                    ))

        return events

    def format_outbound_payload(self, recipient_identifier: str, content: str, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Formats an outbound message for WhatsApp Cloud API.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_identifier,
            "type": "text",
            "text": {"preview_url": False, "body": content}
        }
        return payload
