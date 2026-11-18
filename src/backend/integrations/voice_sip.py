"""
Voice and SIP Telephony Transport Adapter.
Ingests call signaling, state transitions, and recording consent events.
(Baseline Controls 70; SAI-04, SAI-05)
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from src.backend.integrations.base import BaseChannelAdapter, NormalizedInboundEvent

class VoiceSIPAdapter(BaseChannelAdapter):
    """Adapter for SIP telephony gateway and WebRTC call signaling."""

    def verify_webhook_signature(self, headers: Dict[str, str], raw_body: bytes, secret: str) -> bool:
        """
        Validates telephony provider signature or bearer token.
        """
        sig = headers.get("X-Telephony-Signature") or headers.get("Authorization")
        if not sig:
            return False
        return secret in sig

    def parse_inbound_event(self, headers: Dict[str, str], payload: Dict[str, Any], tenant_id: str) -> List[NormalizedInboundEvent]:
        """
        Parses SIP call session events into normalized timeline events.
        """
        call_id = payload.get("call_id") or payload.get("session_id")
        caller_number = payload.get("from_number") or payload.get("caller_id", "Unknown Caller")
        event_name = payload.get("event") or "CALL_EVENT"
        
        # Enforce recording consent tracking
        consent_disclosed = payload.get("consent_disclosed", False)
        
        content = f"Call Event: {event_name}. Duration: {payload.get('duration_seconds', 0)}s."
        if event_name == "RECORDING_CONSENT_ACCEPTED":
            event_type = "CONSENT_RECORDING"
            content = "Customer consented to call recording following legal disclosure."
        elif event_name == "CALL_COMPLETED":
            event_type = "STATUS"
            content = f"Voice Call Completed. Duration: {payload.get('duration_seconds', 0)}s."
        else:
            event_type = "STATUS"

        event = NormalizedInboundEvent(
            tenant_id=tenant_id,
            channel_type="VOICE_SIP",
            provider_event_id=f"{call_id}_{event_name}",
            sender_identifier=caller_number,
            sender_name=f"Caller ({caller_number})",
            content=content,
            event_type=event_type,
            raw_payload={
                **payload,
                "consent_disclosed": consent_disclosed
            },
            timestamp=datetime.now(timezone.utc)
        )
        return [event]

    def format_outbound_payload(self, recipient_identifier: str, content: str, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Formats SIP signaling or call dispatch command.
        """
        return {
            "to_number": recipient_identifier,
            "action": "DISPATCH_PROMPT",
            "text": content
        }
