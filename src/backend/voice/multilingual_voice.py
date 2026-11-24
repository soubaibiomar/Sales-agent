"""
Multilingual Speech & Dialect Engine for Voice AI.
Supports French (fr-FR), English (en-US), Modern Standard Arabic (ar-MA),
Moroccan Darija (ary-Arab), Arabizi (ary-Latn), and Darija-French code-switching.
Step 07: Dual-Mode Customer & Manager Voice AI
(Controls 39, 40, 65, 66; SAI-09, SAI-10)
"""
import re
from typing import Dict, Any, List, Optional, Tuple
from src.ai.multilingual import MultilingualProcessor
from src.backend.voice.audio_pipeline import AudioChunk, SyntheticAudioGenerator


class MultilingualVoiceEngine:
    """
    Manages speech-to-text (ASR) and text-to-speech (TTS) across multilingual Moroccan matrices.
    Distinguishes verified model support (FR, EN, AR) from experimental support (Darija/Arabizi).
    """

    SUPPORTED_LANGUAGES = {
        "fr-FR": {"name": "French", "tts_profile": "Piper fr_FR-siwis-medium", "verified": True},
        "en-US": {"name": "English", "tts_profile": "Piper en_US-lessac-medium", "verified": True},
        "ar-MA": {"name": "Modern Standard Arabic", "tts_profile": "Piper ar_JO-kareem-medium", "verified": True},
        "ary-Arab": {"name": "Moroccan Darija (Arabic)", "tts_profile": "Piper ar_JO-kareem-medium (approximate)", "verified": False},
        "ary-Latn": {"name": "Moroccan Darija (Arabizi)", "tts_profile": "Piper fr_FR-siwis-medium (approximate)", "verified": False}
    }

    # Darija to MSA / French phonetic normalization map
    DARIJA_KEYWORDS_MAP = {
        "bghit": "je souhaite",
        "dyal": "de",
        "wach": "est-ce que",
        "kifach": "comment",
        "daba": "maintenant",
        "3afak": "s'il vous plaît",
        "bzaf": "beaucoup",
        "choukrane": "merci",
        "tamane": "prix",
        "sl3a": "marchandise",
        "devis": "devis",
        "facture": "facture",
        "livraison": "livraison"
    }

    @classmethod
    def identify_language_and_dialect(cls, text_or_transcript: str) -> Dict[str, Any]:
        """
        Classifies speech transcript into language, dialect, and detects code-switching.
        """
        detected = MultilingualProcessor.detect_language(text_or_transcript)
        text_lower = text_or_transcript.lower()

        # Detect Code-Switching (e.g. Darija + French loan words)
        is_code_switching = False
        darija_markers = [
            "bghit", "dyal", "wach", "kifach", "daba", "3afak", "bzaf", "choukrane", "salam",
            "ch7al", "m3a", "kayn", "kaynin", "ndiro", "n9dro", "tri9", "khdma", "chouf", "wakha",
            "ديال", "بغيت", "واش", "عفاك", "بزاف", "كيفاش", "دابا", "مزيان"
        ]
        french_markers = [
            "devis", "prix", "commande", "livraison", "facture", "catalogue", "merci", "bonjour",
            "urgent", "matériel", "materiel", "informatique", "livreur", "problème", "probleme",
            "technique", "serveur", "messagerie", "réunion", "reunion", "opérateur", "operateur",
            "humain", "remise", "spéciale", "speciale", "laptops", "pc", "portables", "confirmation",
            "bonne", "journée", "journee", "assistance", "rapide", "achats", "achat", "volume",
            "pour", "avec", "dans", "sur", "par", "le", "la", "les", "un", "une", "des", "svp",
            "mot", "passe", "admin", "code"
        ]

        has_arabizi_digits = bool(re.search(r"\b(?=[a-zA-Z0-9]*[379528])(?=[a-zA-Z0-9]*[a-zA-Z])[a-zA-Z0-9]+\b", text_lower))
        has_darija = has_arabizi_digits or any(re.search(r"\b" + re.escape(m) + r"\b", text_lower) for m in darija_markers)
        has_french = any(re.search(r"\b" + re.escape(m) + r"\b", text_lower) for m in french_markers)

        if has_darija and has_french:
            is_code_switching = True

        lang_info = cls.SUPPORTED_LANGUAGES.get(detected, cls.SUPPORTED_LANGUAGES["en-US"])

        return {
            "language_code": detected,
            "language_name": lang_info["name"],
            "tts_profile": lang_info["tts_profile"],
            "is_verified_support": lang_info["verified"],
            "is_code_switching": is_code_switching,
            "normalized_phonetic": MultilingualProcessor.normalize_arabizi_to_phonetic(text_or_transcript)
        }

    @classmethod
    def transcribe_audio_chunk(
        cls,
        chunk: AudioChunk,
        hint_language: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribes a PCM audio chunk with faster-whisper on CPU (F-15).
        Silence/very short audio is skipped without running the model.
        Raises SpeechEngineUnavailableError when the engine is not installed - there is
        no synthetic fallback text.
        """
        from src.backend.voice.speech_engines import SpeechToTextEngine
        if chunk.rms_energy < 300.0 or chunk.duration_ms < 100.0:
            return {"text": "", "confidence": 0.0, "language": hint_language or "fr-FR", "is_empty": True}
        result = SpeechToTextEngine.transcribe(chunk.pcm_bytes, chunk.sample_rate, hint_language=hint_language)
        return {
            "text": result.text,
            "confidence": result.confidence,
            "language": result.language,
            "is_empty": not result.text,
            "engine": "faster-whisper",
            "audio_seconds": result.audio_seconds,
        }

    @classmethod
    def synthesize_speech(
        cls,
        text: str,
        language: str = "fr-FR",
        sample_rate: int = 16000
    ) -> Tuple[AudioChunk, Dict[str, Any]]:
        """
        Synthesizes speech with a local Piper voice (F-15), resampled to `sample_rate`.
        Raises SpeechEngineUnavailableError when the engine/voice is missing.
        """
        from src.backend.voice.speech_engines import TextToSpeechEngine, APPROXIMATE_VOICES, pcm16_to_float32
        import numpy as np
        lang = language if language in cls.SUPPORTED_LANGUAGES else "fr-FR"
        pcm, native_rate, voice_name = TextToSpeechEngine.synthesize(text, lang)
        if native_rate != sample_rate:
            audio = pcm16_to_float32(pcm, native_rate, target_rate=sample_rate)
            pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        audio_chunk = AudioChunk(pcm, sample_rate=sample_rate)
        metadata = {
            "language": lang,
            "tts_engine": f"Piper ({voice_name})",
            "is_verified": cls.SUPPORTED_LANGUAGES[lang]["verified"],
            "pronunciation_approximate": lang in APPROXIMATE_VOICES,
            "duration_ms": int(audio_chunk.duration_ms),
            "sample_rate": sample_rate,
            "samples_count": len(pcm) // 2
        }
        return audio_chunk, metadata
