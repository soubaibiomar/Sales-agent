"""
Unit Tests for Voice Activity Detection, Audio Chunking, and Barge-in Interruption.
Step 07: Dual-Mode Customer & Manager Voice AI
(Controls 28, 70; SAI-04, SAI-05)
"""
import pytest
from src.backend.voice.audio_pipeline import (
    AudioChunk,
    VoiceActivityDetector,
    BargeInManager,
    SyntheticAudioGenerator
)


def test_audio_chunk_wav_conversion_and_rms():
    # 1. Generate 500ms sine tone at 440Hz
    chunk = SyntheticAudioGenerator.generate_sine_tone(frequency_hz=440.0, duration_ms=500, amplitude=8000.0)
    assert chunk.duration_ms == pytest.approx(500.0, rel=1e-2)
    assert chunk.sample_rate == 16000
    assert chunk.channels == 1
    assert chunk.rms_energy > 5000.0

    # 2. Convert to WAV bytes and reconstruct
    wav_bytes = chunk.to_wav_bytes()
    assert len(wav_bytes) > len(chunk.pcm_bytes)
    assert wav_bytes[:4] == b"RIFF"

    reconstructed = AudioChunk.from_wav_bytes(wav_bytes)
    assert reconstructed.duration_ms == pytest.approx(500.0, rel=1e-2)
    assert reconstructed.sample_rate == 16000
    assert reconstructed.rms_energy == pytest.approx(chunk.rms_energy, rel=1e-2)

    # 3. Base64 conversion
    b64 = chunk.to_base64_wav()
    from_b64 = AudioChunk.from_base64_wav(b64)
    assert from_b64.rms_energy == pytest.approx(chunk.rms_energy, rel=1e-2)


def test_silence_chunk_properties():
    silence = SyntheticAudioGenerator.generate_silence(duration_ms=200)
    assert silence.duration_ms == pytest.approx(200.0, rel=1e-2)
    assert silence.rms_energy == 0.0


def test_vad_speech_detection_and_turn_completion():
    vad = VoiceActivityDetector(energy_threshold=400.0, silence_timeout_ms=300.0, min_speech_duration_ms=100.0)

    # 1. Silence chunk should not trigger speech
    silence = SyntheticAudioGenerator.generate_silence(duration_ms=50)
    res_silence = vad.process_chunk(silence)
    assert res_silence["is_speech_frame"] is False
    assert res_silence["in_speech_turn"] is False

    # 2. Speech frames: feed 3x 50ms frames = 150ms > min_speech_duration_ms (100ms)
    speech_frame = SyntheticAudioGenerator.generate_sine_tone(duration_ms=50, amplitude=6000.0)
    vad.process_chunk(speech_frame)
    vad.process_chunk(speech_frame)
    res_speech3 = vad.process_chunk(speech_frame)
    assert res_speech3["is_speech_frame"] is True
    assert res_speech3["in_speech_turn"] is True
    assert res_speech3["turn_completed"] is False

    # 3. Trailing silence reaching/exceeding silence_timeout_ms (300ms) completes the turn
    silence_frame = SyntheticAudioGenerator.generate_silence(duration_ms=100)
    vad.process_chunk(silence_frame)  # 100ms
    vad.process_chunk(silence_frame)  # 200ms
    res_turn = vad.process_chunk(silence_frame)  # 300ms -> Completed!
    assert res_turn["turn_completed"] is True
    assert res_turn["in_speech_turn"] is False


def test_barge_in_interruption_triggers_cancellation():
    manager = BargeInManager(barge_in_energy_threshold=600.0, consecutive_frames_required=2)

    # Initially AI is idle; speech should not trigger barge-in
    speech = SyntheticAudioGenerator.generate_speech_like_waveform(duration_ms=50, amplitude=8000.0)
    assert manager.check_barge_in(speech) is False

    # AI starts speaking
    manager.set_ai_speaking(True)
    assert manager.is_ai_speaking is True
    assert manager.is_cancelled is False

    # First loud frame
    barge1 = manager.check_barge_in(speech)
    assert barge1 is False  # Requires 2 consecutive frames

    # Second consecutive loud frame -> Barge-in triggered!
    barge2 = manager.check_barge_in(speech)
    assert barge2 is True
    assert manager.is_cancelled is True
    assert manager.is_ai_speaking is False


def test_barge_in_manual_abort():
    manager = BargeInManager()
    manager.set_ai_speaking(True)
    assert manager.is_cancelled is False

    manager.abort_turn()
    assert manager.is_cancelled is True
    assert manager.is_ai_speaking is False
