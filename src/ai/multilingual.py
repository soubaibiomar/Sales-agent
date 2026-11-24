"""
Multilingual Text Normalization and Dialect Identification Module.
Supports French, English, Modern Standard Arabic, Moroccan Darija, and Arabizi.
"""
import re
from typing import Dict, Any

class MultilingualProcessor:
    """Handles text preprocessing, dialect tagging, and Arabizi normalization."""

    # Common Arabizi phonetic substitutions (numbers used for Arabic letters)
    ARABIZI_MAP = {
        "3": "ع",  # Ayn
        "7": "ح",  # Haa
        "9": "ق",  # Qaf
        "5": "خ",  # Khaa
        "2": "ء",  # Hamza
        "8": "غ",  # Ghayn
    }

    @classmethod
    def detect_language(cls, text: str) -> str:
        """
        Classifies input text into one of 5 supported language matrices:
        - 'en-US' (English)
        - 'fr-FR' (French)
        - 'ar-MA' (Modern Standard Arabic)
        - 'ary-Arab' (Moroccan Darija in Arabic Script)
        - 'ary-Latn' (Moroccan Darija in Latin Arabizi)
        """
        stripped = text.strip()
        if not stripped:
            return "en-US"

        # Check for Arabic script characters
        has_arabic_script = bool(re.search(r"[\u0600-\u06FF]", stripped))
        if has_arabic_script:
            # Check for Darija lexical markers (e.g. dyal, bghit, wach, kifach, daba) in Arabic
            darija_arabic_markers = ["ديال", "بغيت", "واش", "كيفاش", "دابا", "عفاك", "بزاف", "مزيان"]
            for marker in darija_arabic_markers:
                if marker in stripped:
                    return "ary-Arab"
            return "ar-MA"

        # Check for Arabizi patterns (Latin text with digits 3, 7, 9, 5 acting as letters within words)
        arabizi_word_match = re.search(r"\b(?=[a-zA-Z0-9]*[379528])(?=[a-zA-Z0-9]*[a-zA-Z])[a-zA-Z0-9]+\b", stripped)
        darija_latin_markers = [
            "dyal", "bghit", "wach", "kifach", "daba", "3afak", "bzaf", "choukrane",
            "salam", "fina", "ch7al", "m3a", "kayn", "kaynin", "ndiro", "n9dro", "tri9", "khdma",
            "chouf", "homa", "ntoma", "hadi", "hada", "hadou", "chwia", "wakha", "marhaban"
        ]
        has_darija_latin = bool(arabizi_word_match or any(re.search(r"\b" + re.escape(m) + r"\b", stripped, re.IGNORECASE) for m in darija_latin_markers))

        # French lexical vocabulary markers
        french_words = [
            "bonjour", "merci", "devis", "prix", "commande", "livraison", "s'il", "vous", "plaît",
            "avec", "facture", "notre", "panne", "garantie", "quelle", "est", "pour", "nous",
            "je", "des", "les", "le", "la", "une", "un", "dans", "sur", "qui", "que", "ce",
            "cette", "vos", "votre", "souhaite", "obtenir", "serveur", "réseau", "matériel",
            "statut", "possible", "fixer", "rendez-vous", "heures", "parler", "responsable",
            "délais", "envoi", "express", "vers", "reçu", "par", "constructeur", "stockage"
        ]
        french_count = sum(1 for w in french_words if re.search(r"\b" + re.escape(w) + r"\b", stripped, re.IGNORECASE))

        # English lexical vocabulary markers
        english_words = [
            "hello", "hi", "please", "order", "status", "price", "workstations", "servers",
            "available", "stock", "delivery", "support", "demonstration", "architect", "network",
            "gateway", "errors", "shipping", "lead", "times", "certification", "what", "how",
            "can", "we", "our", "is", "for", "the", "with", "from", "you", "demand"
        ]
        english_count = sum(1 for w in english_words if re.search(r"\b" + re.escape(w) + r"\b", stripped, re.IGNORECASE))

        # If it has Arabizi/Darija markers, prioritize Darija Latin
        if has_darija_latin:
            return "ary-Latn"

        if french_count > english_count:
            return "fr-FR"
        elif english_count > french_count:
            return "en-US"

        # Fallback to French if any French marker found
        if french_count > 0:
            return "fr-FR"

        return "en-US"

    @classmethod
    def normalize_arabizi_to_phonetic(cls, text: str) -> str:
        """
        Replaces Arabizi numerals with standard transliterated phonetic placeholders.
        """
        normalized = text
        for digit, char in cls.ARABIZI_MAP.items():
            normalized = normalized.replace(digit, char)
        return normalized

    @classmethod
    def prepare_for_asr(cls, text: str, detected_lang: str) -> Dict[str, Any]:
        """Directs audio segment to the optimal ASR pipeline."""
        if detected_lang in ["ary-Arab", "ary-Latn"]:
            return {
                "pipeline": "atlasia/moulsot.v0.3",
                "device": "cpu",
                "on_demand": True
            }
        return {
            "pipeline": "faster-whisper-small-int8",
            "device": "cpu",
            "on_demand": False
        }

    @classmethod
    def prepare_for_tts(cls, text: str, detected_lang: str) -> Dict[str, Any]:
        """Directs synthesized speech to the optimal TTS synthesizer."""
        if detected_lang in ["fr-FR", "en-US"]:
            return {
                "synthesizer": "Piper-fr_FR/en_US",
                "voice": "fr" if detected_lang == "fr-FR" else "en",
                "device": "cpu"
            }
        return {
            "synthesizer": "Piper-ar_JO",
            "voice": "ar",
            "device": "cpu"
        }
