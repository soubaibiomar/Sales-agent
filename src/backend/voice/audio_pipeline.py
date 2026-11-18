"""
Real-Time Audio Pipeline: VAD, Chunking, Barge-in Interruption, and WAV/PCM Utilities.
Step 07: Dual-Mode Customer & Manager Voice AI
(Controls 28, 70; SAI-04, SAI-05)
"""
import io
import wave
import struct
import math
import base64
import asyncio
from typing import Optional, Tuple, List, Dict, Any


class AudioPipelineError(Exception):
    pass


class AudioChunk:
    """Represents a discrete audio chunk (default 16kHz 16-bit mono PCM)."""
    def __init__(self, pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2):
        self.pcm_bytes = pcm_bytes
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width

    @property
    def duration_ms(self) -> float:
        bytes_per_sample = self.sample_width * self.channels
        if bytes_per_sample == 0 or self.sample_rate == 0:
            return 0.0
        num_samples = len(self.pcm_bytes) / bytes_per_sample
        return (num_samples / self.sample_rate) * 1000.0

    @property
    def rms_energy(self) -> float:
        """Computes Root-Mean-Square (RMS) amplitude of 16-bit PCM."""
        if not self.pcm_bytes:
            return 0.0
        num_samples = len(self.pcm_bytes) // 2
        if num_samples == 0:
            return 0.0
        try:
            samples = struct.unpack(f"<{num_samples}h", self.pcm_bytes[:num_samples * 2])
            sum_squares = sum(s * s for s in samples)
            return math.sqrt(sum_squares / num_samples)
        except Exception:
            return 0.0

    def to_wav_bytes(self) -> bytes:
        """Wraps raw PCM in a standard RIFF/WAV container."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sample_width)
            wf.setframerate(self.sample_rate)
            wf.writeframes(self.pcm_bytes)
        return buffer.getvalue()

    def to_base64_wav(self) -> str:
        return base64.b64encode(self.to_wav_bytes()).decode("utf-8")

    @classmethod
    def from_wav_bytes(cls, wav_bytes: bytes) -> "AudioChunk":
        """Extracts PCM data from a WAV container."""
        buffer = io.BytesIO(wav_bytes)
        with wave.open(buffer, "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            pcm_bytes = wf.readframes(wf.getnframes())
            return cls(pcm_bytes, sample_rate, channels, sample_width)

    @classmethod
    def from_base64_wav(cls, b64_str: str) -> "AudioChunk":
        raw = base64.b64decode(b64_str)
        return cls.from_wav_bytes(raw)


class VoiceActivityDetector:
    """
    Energy & zero-crossing rate VAD.
    Detects speech onset, speech offset, and user silence windows.
    Configured for 16kHz 16-bit mono PCM.
    """
    def __init__(
        self,
        energy_threshold: float = 400.0,
        silence_timeout_ms: float = 600.0,
        min_speech_duration_ms: float = 120.0
    ):
        self.energy_threshold = energy_threshold
        self.silence_timeout_ms = silence_timeout_ms
        self.min_speech_duration_ms = min_speech_duration_ms

        self._in_speech = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0

    def process_chunk(self, chunk: AudioChunk) -> Dict[str, Any]:
        """
        Processes an incoming chunk and updates speech tracking state.
        Returns:
            {
                "is_speech_frame": bool,
                "in_speech_turn": bool,
                "turn_completed": bool,
                "energy": float,
                "speech_duration_ms": float,
                "silence_duration_ms": float
            }
        """
        energy = chunk.rms_energy
        duration = chunk.duration_ms
        is_speech_frame = energy >= self.energy_threshold

        turn_completed = False

        if is_speech_frame:
            self._speech_ms += duration
            self._silence_ms = 0.0
            if self._speech_ms >= self.min_speech_duration_ms:
                self._in_speech = True
        else:
            if self._in_speech:
                self._silence_ms += duration
                if self._silence_ms >= self.silence_timeout_ms:
                    # User stopped speaking; turn completed
                    turn_completed = True
                    self._in_speech = False
                    self._speech_ms = 0.0
                    self._silence_ms = 0.0

        return {
            "is_speech_frame": is_speech_frame,
            "in_speech_turn": self._in_speech,
            "turn_completed": turn_completed,
            "energy": round(energy, 2),
            "speech_duration_ms": round(self._speech_ms, 1),
            "silence_duration_ms": round(self._silence_ms, 1)
        }

    def reset(self):
        self._in_speech = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0


class BargeInManager:
    """
    Real-Time Barge-in & Interruption Controller.
    Detects when user starts speaking while AI is streaming speech,
    instantly cancelling in-flight generation and audio playback.
    """
    def __init__(self, barge_in_energy_threshold: float = 600.0, consecutive_frames_required: int = 2):
        self.barge_in_energy_threshold = barge_in_energy_threshold
        self.consecutive_frames_required = consecutive_frames_required
        self._consecutive_loud_frames = 0
        self._is_ai_speaking = False
        self._cancellation_token = asyncio.Event()

    def set_ai_speaking(self, speaking: bool):
        self._is_ai_speaking = speaking
        if speaking:
            self._cancellation_token.clear()
            self._consecutive_loud_frames = 0

    @property
    def is_ai_speaking(self) -> bool:
        return self._is_ai_speaking

    @property
    def is_cancelled(self) -> bool:
        return self._cancellation_token.is_set()

    def check_barge_in(self, chunk: AudioChunk) -> bool:
        """
        Evaluates whether an incoming chunk triggers a barge-in interruption.
        If triggered, activates cancellation token and marks AI speaking as false.
        """
        if not self._is_ai_speaking:
            return False

        if chunk.rms_energy >= self.barge_in_energy_threshold:
            self._consecutive_loud_frames += 1
            if self._consecutive_loud_frames >= self.consecutive_frames_required:
                # Trigger interruption
                self._cancellation_token.set()
                self._is_ai_speaking = False
                return True
        else:
            self._consecutive_loud_frames = max(0, self._consecutive_loud_frames - 1)

        return False

    def abort_turn(self):
        """Manually forces turn cancellation."""
        self._cancellation_token.set()
        self._is_ai_speaking = False


class SyntheticAudioGenerator:
    """Generates synthetic test tones / speech waveforms for automated audio benchmarking."""

    @staticmethod
    def generate_silence(duration_ms: int = 500, sample_rate: int = 16000) -> AudioChunk:
        num_samples = int((duration_ms / 1000.0) * sample_rate)
        pcm_bytes = b"\x00" * (num_samples * 2)
        return AudioChunk(pcm_bytes, sample_rate=sample_rate)

    @staticmethod
    def generate_sine_tone(
        frequency_hz: float = 440.0,
        duration_ms: int = 500,
        amplitude: float = 8000.0,
        sample_rate: int = 16000
    ) -> AudioChunk:
        num_samples = int((duration_ms / 1000.0) * sample_rate)
        samples = []
        for i in range(num_samples):
            t = float(i) / sample_rate
            val = int(amplitude * math.sin(2.0 * math.pi * frequency_hz * t))
            samples.append(val)
        pcm_bytes = struct.pack(f"<{len(samples)}h", *samples)
        return AudioChunk(pcm_bytes, sample_rate=sample_rate)

    @staticmethod
    def generate_speech_like_waveform(
        duration_ms: int = 1000,
        amplitude: float = 12000.0,
        sample_rate: int = 16000
    ) -> AudioChunk:
        """Combines multiple harmonic frequencies to simulate speech formant bursts."""
        num_samples = int((duration_ms / 1000.0) * sample_rate)
        samples = []
        for i in range(num_samples):
            t = float(i) / sample_rate
            f1 = math.sin(2.0 * math.pi * 300.0 * t)
            f2 = 0.5 * math.sin(2.0 * math.pi * 1200.0 * t)
            f3 = 0.25 * math.sin(2.0 * math.pi * 2500.0 * t)
            env = math.sin(math.pi * (i / num_samples))  # Bell curve envelope
            val = int(amplitude * env * (f1 + f2 + f3) / 1.75)
            samples.append(max(-32768, min(32767, val)))
        pcm_bytes = struct.pack(f"<{len(samples)}h", *samples)
        return AudioChunk(pcm_bytes, sample_rate=sample_rate)
