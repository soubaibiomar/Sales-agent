"""
Unit tests validating multilingual classification, Arabizi transliteration, and TTS/ASR routing.
Covers French, English, Modern Standard Arabic, Moroccan Darija, and Arabizi.
"""
import pytest
from src.ai.multilingual import MultilingualProcessor

def test_language_detection_french():
    text = "Bonjour, je voudrais recevoir un devis officiel pour 50 ordinateurs portables avec livraison."
    lang = MultilingualProcessor.detect_language(text)
    assert lang == "fr-FR"

def test_language_detection_english():
    text = "Hello, what is the current shipment status for order number ORD-9812?"
    lang = MultilingualProcessor.detect_language(text)
    assert lang == "en-US"

def test_language_detection_arabic_standard():
    text = "السلام عليكم ورحمة الله، نود الاستفسار عن تفاصيل عقد التوريد السنوي."
    lang = MultilingualProcessor.detect_language(text)
    assert lang == "ar-MA"

def test_language_detection_darija_arabic_script():
    text = "عفاك بغيت نعرف الثمن ديال هاد السلعة واش مزيانة وبزاف كاينة ف الستوك."
    lang = MultilingualProcessor.detect_language(text)
    assert lang == "ary-Arab"

def test_language_detection_darija_arabizi():
    text = "3afak bghit nchof taman dyal pc w wach kayn f stock daba."
    lang = MultilingualProcessor.detect_language(text)
    assert lang == "ary-Latn"

def test_arabizi_normalization():
    arabizi_input = "3afak choukrane bzaf 7it 3awnitina"
    normalized = MultilingualProcessor.normalize_arabizi_to_phonetic(arabizi_input)
    assert "عafak" in normalized
    assert "7" not in normalized
    assert "ح" in normalized

def test_tts_routing_french_and_english_to_kokoro_cpu():
    tts_fr = MultilingualProcessor.prepare_for_tts("Merci beaucoup", "fr-FR")
    assert tts_fr["synthesizer"] == "Piper-fr_FR/en_US"
    assert tts_fr["voice"] == "fr"
    assert tts_fr["device"] == "cpu"

    tts_en = MultilingualProcessor.prepare_for_tts("Thank you very much", "en-US")
    assert tts_en["synthesizer"] == "Piper-fr_FR/en_US"
    assert tts_en["voice"] == "en"
    assert tts_en["device"] == "cpu"

def test_tts_routing_arabic_and_darija_to_piper_cpu():
    tts_ar = MultilingualProcessor.prepare_for_tts("شكرا جزيلا", "ar-MA")
    assert tts_ar["synthesizer"] == "Piper-ar_JO"
    assert tts_ar["device"] == "cpu"

    tts_darija = MultilingualProcessor.prepare_for_tts("choukrane bzaf", "ary-Latn")
    assert tts_darija["synthesizer"] == "Piper-ar_JO"
    assert tts_darija["device"] == "cpu"

def test_asr_routing_darija_on_demand():
    asr_darija = MultilingualProcessor.prepare_for_asr("audio_chunk", "ary-Arab")
    assert asr_darija["pipeline"] == "atlasia/moulsot.v0.3"
    assert asr_darija["on_demand"] is True
    assert asr_darija["device"] == "cpu"

    asr_fr = MultilingualProcessor.prepare_for_asr("audio_chunk", "fr-FR")
    assert asr_fr["pipeline"] == "faster-whisper-small-int8"
    assert asr_fr["on_demand"] is False
    assert asr_fr["device"] == "cpu"
