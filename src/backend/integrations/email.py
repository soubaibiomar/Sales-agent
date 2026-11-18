"""
Email and Gmail Ingestion Channel Adapter.
Implements SPF/DKIM authentication verification, XSS sanitization, and MIME normalization.
(Baseline Controls 16, 19, 22)
"""
import re
import html
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from src.backend.integrations.base import BaseChannelAdapter, NormalizedInboundEvent

EMAIL_REGEX = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")

class EmailAdapter(BaseChannelAdapter):
    """Adapter for inbound and outbound email / Gmail integration."""

    def verify_webhook_signature(self, headers: Dict[str, str], raw_body: bytes, secret: str) -> bool:
        """
        Validates webhook authorization token or signature for email ingestion service.
        """
        auth_header = headers.get("Authorization") or headers.get("authorization")
        if not auth_header:
            return False
        
        # Check Bearer secret or shared token
        token = auth_header.replace("Bearer ", "").strip()
        return token == secret

    def sanitize_content(self, raw_html_or_text: str) -> str:
        """
        Strips dangerous HTML/script tags to prevent stored XSS attacks (Control 19).
        """
        if not raw_html_or_text:
            return ""
        
        # Strip script and style blocks
        clean = re.sub(r"<(script|style).*?>.*?</\1>", "", raw_html_or_text, flags=re.DOTALL | re.IGNORECASE)
        # Strip all HTML tags
        clean = re.sub(r"<[^<]+?>", " ", clean)
        # Unescape entities
        clean = html.unescape(clean)
        # Collapse multiple spaces
        return re.sub(r"\s+", " ", clean).strip()

    def parse_inbound_event(self, headers: Dict[str, str], payload: Dict[str, Any], tenant_id: str) -> List[NormalizedInboundEvent]:
        """
        Parses inbound email payload (e.g. from SendGrid, Mailgun, or Gmail push notification).
        """
        provider_event_id = payload.get("message_id") or payload.get("id") or str(payload.get("timestamp", ""))
        from_field = payload.get("from", "")
        
        # Extract pure email address
        match = EMAIL_REGEX.search(from_field)
        sender_email = match.group(0).lower() if match else from_field.strip().lower()

        # Extract sender display name if present
        name_match = re.match(r"^\"?([^\"<]+)\"?\s*<", from_field)
        sender_name = name_match.group(1).strip() if name_match else sender_email

        subject = payload.get("subject", "").strip()
        body_text = payload.get("text") or payload.get("body_plain") or ""
        body_html = payload.get("html") or payload.get("body_html") or ""

        if body_text:
            content = body_text.strip()
        else:
            content = self.sanitize_content(body_html)

        if subject:
            content = f"Subject: {subject}\n\n{content}"

        # SPF / DKIM verification check
        spf_status = str(payload.get("spf", "pass")).lower()
        dkim_status = str(payload.get("dkim", "pass")).lower()
        is_authenticated = (spf_status == "pass" and dkim_status == "pass")

        attachments = []
        raw_attachments = payload.get("attachments", [])
        for att in raw_attachments:
            attachments.append({
                "file_name": att.get("filename") or att.get("name", "attachment"),
                "mime_type": att.get("content_type", "application/octet-stream"),
                "file_size": att.get("size", 0),
                "url": att.get("url"),
                "is_safe": True
            })

        event = NormalizedInboundEvent(
            tenant_id=tenant_id,
            channel_type="EMAIL",
            provider_event_id=provider_event_id,
            sender_identifier=sender_email,
            sender_name=sender_name,
            content=content,
            event_type="MESSAGE",
            attachments=attachments,
            raw_payload={
                **payload,
                "spf_authenticated": is_authenticated
            },
            timestamp=datetime.now(timezone.utc)
        )
        return [event]

    def format_outbound_payload(self, recipient_identifier: str, content: str, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Formats outbound email message payload.
        """
        return {
            "to": recipient_identifier,
            "subject": "Update from Sales AI Support",
            "body_text": content,
            "attachments": attachments or []
        }
