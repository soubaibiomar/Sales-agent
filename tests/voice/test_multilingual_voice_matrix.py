"""
Unit Tests for Multilingual Speech, Dialects, Arabizi, and Code-Switching.
Step 07: Dual-Mode Customer & Manager Voice AI
(Controls 39, 40, 65, 66; SAI-09, SAI-10)
"""
import pytest
from src.backend.voice.multilingual_voice import MultilingualVoiceEngine
from src.backend.voice.audio_pipeline import SyntheticAudioGenerator


def test_multilingual_matrix_classification():
    # 1. French
    fr_res = MultilingualVoiceEngine.identify_language_and_dialect("Bonjour, quel est le prix de votre devis pour la livraison ?")
    assert fr_res["language_code"] == "fr-FR"
    assert fr_res["is_verified_support"] is True
    assert "Kokoro-82M" in fr_res["tts_profile"]

    # 2. English
    en_res = MultilingualVoiceEngine.identify_language_and_dialect("Hello, can you give me the status of our commercial invoice?")
    assert en_res["language_code"] == "en-US"
    assert en_res["is_verified_support"] is True

    # 3. Modern Standard Arabic
    ar_res = MultilingualVoiceEngine.identify_language_and_dialect("السلام عليكم، أود الاستفسار عن تفاصيل الفاتورة التجارية")
    assert ar_res["language_code"] == "ar-MA"
    assert ar_res["is_verified_support"] is True
    assert "Piper" in ar_res["tts_profile"]

    # 4. Moroccan Darija (Arabic script)
    darija_ar = MultilingualVoiceEngine.identify_language_and_dialect("عفاك بغيت نعرف واش كاين هاد البيسي ديسبونيبل دابا وبشحال الثمن ديالو")
    assert darija_ar["language_code"] == "ary-Arab"
    assert darija_ar["is_verified_support"] is False  # Correctly labeled experimental

    # 5. Moroccan Darija Arabizi (Latin digits)
    arabizi = MultilingualVoiceEngine.identify_language_and_dialect("Salam 3afak bghit n3ref wach kayen stock dyal had l-produit w ch7al taman")
    assert arabizi["language_code"] == "ary-Latn"
    assert "ع" in arabizi["normalized_phonetic"]  # 3 -> Ayn
    assert "ح" in arabizi["normalized_phonetic"]  # 7 -> Haa


def test_code_switching_detection_darija_french():
    # Mix of Darija verbs/particles with French commercial terms
    mixed = "Salam 3afak bghit un devis express pour la commande dyal les ordinateurs portables"
    res = MultilingualVoiceEngine.identify_language_and_dialect(mixed)
    assert res["is_code_switching"] is True
    assert res["language_code"] in ("ary-Latn", "fr-FR")


def test_speech_synthesis_profiles_and_durations():
    # French
    chunk_fr, meta_fr = MultilingualVoiceEngine.synthesize_speech("Merci pour votre commande", language="fr-FR")
    assert chunk_fr.duration_ms >= 400
    assert meta_fr["language"] == "fr-FR"
    assert "Kokoro" in meta_fr["tts_engine"]

    # Arabic
    chunk_ar, meta_ar = MultilingualVoiceEngine.synthesize_speech("شكرا لك على اتصالك بنا", language="ar-MA")
    assert chunk_ar.duration_ms >= 400
    assert meta_ar["language"] == "ar-MA"
    assert "Piper" in meta_ar["tts_engine"]

    # Fallback for unknown language
    chunk_fb, meta_fb = MultilingualVoiceEngine.synthesize_speech("Fallback test", language="es-ES")
    assert meta_fb["language"] == "fr-FR"  # Defaults cleanly to French


def test_transcribe_audio_chunk_empty_vs_valid():
    # 1. Low energy / silence
    silence = SyntheticAudioGenerator.generate_silence(duration_ms=100)
    res_silence = MultilingualVoiceEngine.transcribe_audio_chunk(silence)
    assert res_silence["is_empty"] is True
    assert res_silence["text"] == ""

    # 2. Valid speech-like waveform
    speech = SyntheticAudioGenerator.generate_speech_like_waveform(duration_ms=800, amplitude=9000.0)
    res_speech = MultilingualVoiceEngine.transcribe_audio_chunk(speech, hint_language="fr-FR")
    assert res_speech["is_empty"] is False
    assert len(res_speech["text"]) > 0
    assert res_speech["language"] == "fr-FR"
