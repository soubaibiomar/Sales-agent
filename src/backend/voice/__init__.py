"""
Voice AI Platform Package.
Dual-mode Customer Voice Agent and Manager Voice Copilot.
"""
from src.backend.voice.audio_pipeline import AudioChunk, VoiceActivityDetector, BargeInManager
from src.backend.voice.multilingual_voice import MultilingualVoiceEngine
from src.backend.voice.security import (
    VoicePIIRedactor,
    VoicePromptInjectionGuard,
    VoiceIdentityVerificationManager,
    ManagerPrivilegedActionGuard
)
from src.backend.voice.customer_agent import CustomerVoiceAgent
from src.backend.voice.manager_copilot import ManagerVoiceCopilot
from src.backend.voice.service import VoiceSessionService

__all__ = [
    "AudioChunk",
    "VoiceActivityDetector",
    "BargeInManager",
    "MultilingualVoiceEngine",
    "VoicePIIRedactor",
    "VoicePromptInjectionGuard",
    "VoiceIdentityVerificationManager",
    "ManagerPrivilegedActionGuard",
    "CustomerVoiceAgent",
    "ManagerVoiceCopilot",
    "VoiceSessionService"
]
