from src.backend.integrations.base import BaseChannelAdapter, NormalizedInboundEvent
from src.backend.integrations.whatsapp import WhatsAppAdapter
from src.backend.integrations.email import EmailAdapter
from src.backend.integrations.webchat import WebChatAdapter
from src.backend.integrations.voice_sip import VoiceSIPAdapter

__all__ = [
    "BaseChannelAdapter",
    "NormalizedInboundEvent",
    "WhatsAppAdapter",
    "EmailAdapter",
    "WebChatAdapter",
    "VoiceSIPAdapter"
]
