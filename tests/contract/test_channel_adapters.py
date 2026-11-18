"""
Contract Tests for Channel Adapters: WhatsApp, Email, WebChat, Voice/SIP.
Verifies cryptographic signatures, payload normalization, XSS stripping, and media metadata.
(Baseline Controls 16, 19, 21, 22)
"""
import hmac
import hashlib
import json
import pytest

from src.backend.integrations.whatsapp import WhatsAppAdapter
from src.backend.integrations.email import EmailAdapter
from src.backend.integrations.webchat import WebChatAdapter
from src.backend.integrations.voice_sip import VoiceSIPAdapter

def test_whatsapp_signature_verification_valid():
    adapter = WhatsAppAdapter()
    secret = "test_webhook_secret_key_123"
    body = b'{"object": "whatsapp_business_account"}'
    valid_sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    headers = {"X-Hub-Signature-256": valid_sig}
    assert adapter.verify_webhook_signature(headers, body, secret) is True

def test_whatsapp_signature_verification_invalid():
    adapter = WhatsAppAdapter()
    secret = "test_webhook_secret_key_123"
    body = b'{"object": "whatsapp_business_account"}'
    
    # Forged signature
    headers = {"X-Hub-Signature-256": "sha256=forged_hash_value_that_does_not_match"}
    assert adapter.verify_webhook_signature(headers, body, secret) is False

    # Missing header
    assert adapter.verify_webhook_signature({}, body, secret) is False

def test_whatsapp_parse_inbound_text():
    adapter = WhatsAppAdapter()
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "wa_acc_01",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "contacts": [{"profile": {"name": "Omar Soubaibi"}, "wa_id": "212612345678"}],
                    "messages": [{
                        "from": "212612345678",
                        "id": "wamid.HBgLMjEyNjEyMzQ1Njc4",
                        "timestamp": "1710000000",
                        "type": "text",
                        "text": {"body": "Salam, bghina devis"}
                    }]
                }
            }]
        }]
    }

    events = adapter.parse_inbound_event({}, payload, tenant_id="t_test_01")
    assert len(events) == 1
    ev = events[0]
    assert ev.tenant_id == "t_test_01"
    assert ev.channel_type == "WHATSAPP"
    assert ev.provider_event_id == "wamid.HBgLMjEyNjEyMzQ1Njc4"
    assert ev.sender_identifier == "212612345678"
    assert ev.sender_name == "Omar Soubaibi"
    assert ev.content == "Salam, bghina devis"

def test_whatsapp_parse_media_attachment():
    adapter = WhatsAppAdapter()
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "wa_acc_01",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "contacts": [{"profile": {"name": "Driss Alami"}, "wa_id": "212688990011"}],
                    "messages": [{
                        "from": "212688990011",
                        "id": "wamid.MEDIA_ATTACH_01",
                        "type": "image",
                        "image": {
                            "id": "media_img_123",
                            "mime_type": "image/jpeg",
                            "caption": "Photo du bon de commande",
                            "url": "https://images.unsplash.com/media/doc1.jpg"
                        }
                    }]
                }
            }]
        }]
    }

    events = adapter.parse_inbound_event({}, payload, tenant_id="t_test_01")
    assert len(events) == 1
    ev = events[0]
    assert len(ev.attachments) == 1
    att = ev.attachments[0]
    assert att["type"] == "image"
    assert att["mime_type"] == "image/jpeg"
    assert att["is_safe"] is True

def test_email_signature_and_xss_sanitization():
    adapter = EmailAdapter()
    secret = "email_secret_token_abc"
    headers = {"Authorization": "Bearer email_secret_token_abc"}
    assert adapter.verify_webhook_signature(headers, b"", secret) is True

    # Bad token
    assert adapter.verify_webhook_signature({"Authorization": "Bearer wrong"}, b"", secret) is False

    # XSS sanitization
    raw_html = "Hello <script>alert('XSS')</script><b>World</b> <style>body{color:red;}</style>"
    clean = adapter.sanitize_content(raw_html)
    assert "<script>" not in clean
    assert "alert" not in clean
    assert "<style>" not in clean
    assert "Hello World" in clean

def test_email_parse_inbound_event():
    adapter = EmailAdapter()
    payload = {
        "message_id": "msg_email_001",
        "from": "Sara Tazi <sara.tazi@company.ma>",
        "subject": "Demande de partenariat",
        "text": "Bonjour, nous souhaitons integrer votre API.",
        "spf": "pass",
        "dkim": "pass"
    }

    events = adapter.parse_inbound_event({}, payload, tenant_id="t_test_01")
    assert len(events) == 1
    ev = events[0]
    assert ev.channel_type == "EMAIL"
    assert ev.sender_identifier == "sara.tazi@company.ma"
    assert ev.sender_name == "Sara Tazi"
    assert "Demande de partenariat" in ev.content
    assert ev.raw_payload["spf_authenticated"] is True

def test_webchat_parse_inbound_event():
    adapter = WebChatAdapter()
    payload = {
        "session_id": "sess_web_visitor_99",
        "customer_name": "Mehdi",
        "message": "Is there someone online?",
        "message_id": "web_msg_456"
    }
    events = adapter.parse_inbound_event({}, payload, tenant_id="t_test_01")
    assert len(events) == 1
    ev = events[0]
    assert ev.channel_type == "WEB_CHAT"
    assert ev.sender_identifier == "sess_web_visitor_99"
    assert ev.content == "Is there someone online?"

def test_voice_sip_event_ingestion_and_consent():
    adapter = VoiceSIPAdapter()
    payload = {
        "call_id": "sip_call_casablanca_001",
        "from_number": "+212522001122",
        "event": "RECORDING_CONSENT_ACCEPTED",
        "consent_disclosed": True,
        "duration_seconds": 15
    }
    events = adapter.parse_inbound_event({}, payload, tenant_id="t_test_01")
    assert len(events) == 1
    ev = events[0]
    assert ev.channel_type == "VOICE_SIP"
    assert ev.event_type == "CONSENT_RECORDING"
    assert "consented to call recording" in ev.content
    assert ev.raw_payload["consent_disclosed"] is True
