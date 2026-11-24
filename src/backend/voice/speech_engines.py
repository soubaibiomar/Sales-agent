"""
Real local speech engines (inspection finding F-15).

Replaces the placeholders that returned the constant text "Audio utterance processed"
for any loud audio and synthesized sine-wave "speech":

  * Speech-to-text: faster-whisper (CTranslate2), CPU, int8 - AGENTS.md keeps auxiliary
    models off the GPU. Model weights load from the local Hugging Face cache.
  * Text-to-speech: Piper (ONNX, CPU) voices fr_FR-siwis-medium, en_US-lessac-medium,
    ar_JO-kareem-medium, stored outside the repository (PIPER_VOICES_DIR).

There is no synthetic fallback: if an engine or voice is missing, SpeechEngineUnavailableError
is raised and the caller degrades to text + human hand-off.

Known limits (measured/declared, not hidden):
  * Moroccan Darija has no dedicated Piper voice; Arabic-script text uses the Jordanian
    Arabic voice and Arabizi (Latin script) uses the French voice - pronunciation is
    approximate. Whisper has no Darija language code; it is detected as "ar".
  * CPU ASR is slow: ~6.9 s to transcribe 3.7 s of audio with the "small" model on the
    reference laptop (evidence/claude-inspection/benchmarks).
"""
import io
import logging
import os
import threading
import wave
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger("SalesAI.SpeechEngines")

WHISPER_TO_APP_LANG = {"fr": "fr-FR", "en": "en-US", "ar": "ar-MA"}
APP_TO_WHISPER_LANG = {"fr-FR": "fr", "en-US": "en", "ar-MA": "ar", "ary-Arab": "ar", "ary-Latn": "fr"}
APP_LANG_TO_VOICE = {
    "fr-FR": "fr_FR-siwis-medium",
    "en-US": "en_US-lessac-medium",
    "ar-MA": "ar_JO-kareem-medium",
    "ary-Arab": "ar_JO-kareem-medium",   # approximate: no Darija voice exists
    "ary-Latn": "fr_FR-siwis-medium",    # approximate: Arabizi read by the French voice
}
APPROXIMATE_VOICES = {"ary-Arab", "ary-Latn"}


class SpeechEngineUnavailableError(RuntimeError):
    """A speech engine, model or voice is not installed / failed to run."""


@dataclass
class Transcription:
    text: str
    language: str
    confidence: float
    audio_seconds: float


def _settings():
    from src.backend.core.config import settings
    return settings


def pcm16_to_float32(pcm_bytes: bytes, sample_rate: int, target_rate: int = 16000) -> np.ndarray:
    """Mono 16-bit PCM -> float32 at 16 kHz (linear resampling)."""
    pcm = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if sample_rate == target_rate or len(pcm) == 0:
        return pcm
    n = int(len(pcm) * target_rate / sample_rate)
    return np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm).astype(np.float32)


class SpeechToTextEngine:
    _model = None
    _lock = threading.Lock()

    @classmethod
    def _load(cls):
        if cls._model is None:
            with cls._lock:
                if cls._model is None:
                    try:
                        from faster_whisper import WhisperModel
                        s = _settings()
                        cls._model = WhisperModel(s.stt_model_size, device="cpu", compute_type=s.stt_compute_type)
                    except Exception as exc:  # noqa: BLE001
                        raise SpeechEngineUnavailableError(f"Speech-to-text engine unavailable: {exc}") from exc
        return cls._model

    @classmethod
    def transcribe(cls, pcm_bytes: bytes, sample_rate: int = 16000, hint_language: Optional[str] = None) -> Transcription:
        audio = pcm16_to_float32(pcm_bytes, sample_rate)
        model = cls._load()
        try:
            segments, info = model.transcribe(
                audio, language=APP_TO_WHISPER_LANG.get(hint_language or ""), beam_size=1,
                vad_filter=True, condition_on_previous_text=False
            )
            segments = list(segments)
        except Exception as exc:  # noqa: BLE001
            raise SpeechEngineUnavailableError(f"Transcription failed: {exc}") from exc
        text = " ".join(seg.text.strip() for seg in segments).strip()
        conf = float(np.exp(np.mean([seg.avg_logprob for seg in segments]))) if segments else 0.0
        return Transcription(text=text, language=WHISPER_TO_APP_LANG.get(info.language, hint_language or "fr-FR"),
                             confidence=round(conf, 3), audio_seconds=round(len(audio) / 16000.0, 3))


class TextToSpeechEngine:
    _voices = {}
    _lock = threading.Lock()

    @classmethod
    def _voice(cls, voice_name: str):
        if voice_name not in cls._voices:
            with cls._lock:
                if voice_name not in cls._voices:
                    path = os.path.join(_settings().piper_voices_dir, f"{voice_name}.onnx")
                    if not os.path.exists(path):
                        raise SpeechEngineUnavailableError(f"Piper voice not installed: {path}")
                    try:
                        from piper import PiperVoice
                        cls._voices[voice_name] = PiperVoice.load(path)
                    except Exception as exc:  # noqa: BLE001
                        raise SpeechEngineUnavailableError(f"Text-to-speech engine unavailable: {exc}") from exc
        return cls._voices[voice_name]

    @classmethod
    def synthesize(cls, text: str, language: str) -> Tuple[bytes, int, str]:
        """Returns (pcm16 mono bytes, sample_rate, voice_name)."""
        voice_name = APP_LANG_TO_VOICE.get(language, APP_LANG_TO_VOICE["fr-FR"])
        voice = cls._voice(voice_name)
        buf = io.BytesIO()
        try:
            with wave.open(buf, "wb") as w:
                voice.synthesize_wav(text, w)
            buf.seek(0)
            with wave.open(buf, "rb") as w:
                return w.readframes(w.getnframes()), w.getframerate(), voice_name
        except Exception as exc:  # noqa: BLE001
            raise SpeechEngineUnavailableError(f"Speech synthesis failed: {exc}") from exc
