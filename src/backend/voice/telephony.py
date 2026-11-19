"""
Telephony, SIP and WebRTC Transport Gateway.
Signature-authenticated webhooks, anti-replay guards, call flood rate limiters,
callback queues, and ITU-T G.711 mu-law / linear 16kHz PCM audio transcoding.
Step 10: Complete Customer Voice AI & Manager Voice AI Copilot
(Controls 04, 05, 06, 28, 70; SAI-04, SAI-05)
"""
import io
import time
import hmac
import hashlib
import struct
import math
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger("SalesAI.Telephony")


class TelephonySecurityError(Exception):
    pass


class ReplayAttackDetectedError(TelephonySecurityError):
    pass


class CallRateLimitExceededError(TelephonySecurityError):
    pass


class G711Codec:
    """
    Pure-Python ITU-T G.711 mu-law / 16-bit linear PCM codec with sample rate conversion.
    Zero external C dependencies, fully compatible with Python 3.14+.
    """
    # Precomputed mu-law expansion table (8-bit mu-law -> 16-bit signed integer)
    _ULAW_EXPANSION_TABLE: List[int] = []

    @classmethod
    def _init_table(cls):
        if cls._ULAW_EXPANSION_TABLE:
            return
        table = []
        for b in range(256):
            ub = ~b & 0xFF
            sign = (ub & 0x80)
            exponent = (ub >> 4) & 0x07
            mantissa = ub & 0x0F
            sample = ((mantissa << 3) + 0x84) << exponent
            sample -= 0x84
            table.append(-sample if sign else sample)
        cls._ULAW_EXPANSION_TABLE = table

    @classmethod
    def ulaw_to_linear16(cls, ulaw_bytes: bytes) -> bytes:
        """Decodes 8-bit ITU-T G.711 mu-law into 16-bit signed mono PCM."""
        cls._init_table()
        table = cls._ULAW_EXPANSION_TABLE
        num_samples = len(ulaw_bytes)
        samples = [table[b] for b in ulaw_bytes]
        return struct.pack(f"<{num_samples}h", *samples)

    @classmethod
    def linear16_to_ulaw(cls, pcm_bytes: bytes) -> bytes:
        """Encodes 16-bit signed mono PCM into 8-bit ITU-T G.711 mu-law."""
        num_samples = len(pcm_bytes) // 2
        if num_samples == 0:
            return b""
        samples = struct.unpack(f"<{num_samples}h", pcm_bytes[:num_samples * 2])
        ulaw_out = bytearray(num_samples)

        bias = 0x84
        clip = 32635

        for i, sample in enumerate(samples):
            sign = 0x80 if sample < 0 else 0x00
            sample = abs(sample)
            if sample > clip:
                sample = clip
            sample += bias

            exponent = 7
            mask = 0x4000
            while exponent > 0 and (sample & mask) == 0:
                exponent -= 1
                mask >>= 1

            mantissa = (sample >> (exponent + 3)) & 0x0F
            byte_val = ~(sign | (exponent << 4) | mantissa) & 0xFF
            ulaw_out[i] = byte_val

        return bytes(ulaw_out)

    @classmethod
    def resample_8k_to_16k(cls, pcm_8k: bytes) -> bytes:
        """Upsamples 8kHz 16-bit linear PCM to 16kHz via linear interpolation."""
        num_samples = len(pcm_8k) // 2
        if num_samples == 0:
            return b""
        samples = struct.unpack(f"<{num_samples}h", pcm_8k)
        upsampled = []
        for i in range(num_samples - 1):
            s1 = samples[i]
            s2 = samples[i + 1]
            upsampled.append(s1)
            upsampled.append((s1 + s2) // 2)
        if samples:
            upsampled.append(samples[-1])
            upsampled.append(samples[-1])
        return struct.pack(f"<{len(upsampled)}h", *upsampled)

    @classmethod
    def resample_16k_to_8k(cls, pcm_16k: bytes) -> bytes:
        """Downsamples 16kHz 16-bit linear PCM to 8kHz via decimation."""
        num_samples = len(pcm_16k) // 2
        if num_samples == 0:
            return b""
        samples = struct.unpack(f"<{num_samples}h", pcm_16k)
        downsampled = samples[0::2]
        return struct.pack(f"<{len(downsampled)}h", *downsampled)


class TelephonySignatureVerifier:
    """
    Verifies cryptographic signatures for inbound telephony webhooks (Twilio/SIP).
    Enforces replay protection with timestamp freshness window and nonce caching.
    """
    def __init__(self, replay_window_seconds: float = 300.0):
        self.replay_window_seconds = replay_window_seconds
        # In-memory nonce cache {nonce: timestamp}
        self._nonce_cache: Dict[str, float] = {}

    def _purge_expired_nonces(self):
        now = time.time()
        expired = [n for n, ts in self._nonce_cache.items() if now - ts > self.replay_window_seconds]
        for n in expired:
            del self._nonce_cache[n]

    def verify_twilio_signature(
        self,
        auth_token: str,
        webhook_url: str,
        params: Dict[str, Any],
        signature: str,
        timestamp: Optional[float] = None,
        nonce: Optional[str] = None
    ) -> bool:
        """
        Validates Twilio webhook HMAC-SHA1 signature and timestamp freshness.
        """
        now = time.time()
        if timestamp is not None:
            if abs(now - timestamp) > self.replay_window_seconds:
                raise ReplayAttackDetectedError(
                    f"Telephony webhook rejected: Timestamp delta {abs(now - timestamp):.1f}s exceeds window {self.replay_window_seconds}s."
                )

        if nonce is not None:
            self._purge_expired_nonces()
            if nonce in self._nonce_cache:
                raise ReplayAttackDetectedError(f"Telephony webhook rejected: Duplicate nonce detected '{nonce}'.")
            self._nonce_cache[nonce] = now

        # Construct Twilio payload: URL followed by sorted key+value pairs
        data_to_sign = webhook_url
        for k in sorted(params.keys()):
            data_to_sign += f"{k}{params[k]}"

        computed = hmac.new(
            auth_token.encode("utf-8"),
            data_to_sign.encode("utf-8"),
            hashlib.sha1
        ).digest()
        import base64
        expected_sig = base64.b64encode(computed).decode("utf-8")

        return hmac.compare_digest(expected_sig, signature)

    def verify_sip_hmac_sha256(
        self,
        api_secret: str,
        raw_body: bytes,
        signature_header: str,
        timestamp: Optional[float] = None
    ) -> bool:
        """
        Validates SIP signaling WebRTC HMAC-SHA256 signature.
        """
        now = time.time()
        if timestamp is not None and abs(now - timestamp) > self.replay_window_seconds:
            raise ReplayAttackDetectedError("SIP event rejected: Timestamp expired.")

        computed = hmac.new(
            api_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        # Handle 'sha256=...' prefix
        clean_sig = signature_header.replace("sha256=", "").strip()
        return hmac.compare_digest(computed, clean_sig)


class VoiceCallRateLimiter:
    """
    Prevents telephony denial-of-service, call flooding and toll-fraud.
    Enforces per-caller concurrent call limits and call velocity caps.
    (Control 28, 70; SAI-04)
    """
    def __init__(self, max_concurrent: int = 3, max_calls_per_minute: int = 10):
        self.max_concurrent = max_concurrent
        self.max_calls_per_minute = max_calls_per_minute
        # Active calls count per caller identifier {caller_id: active_count}
        self._active_calls: Dict[str, int] = {}
        # Call history timestamps per caller {caller_id: [t1, t2, ...]}
        self._call_history: Dict[str, List[float]] = {}

    def acquire_call_slot(self, caller_id: str):
        now = time.time()
        # Clean history older than 60s
        history = [t for t in self._call_history.get(caller_id, []) if now - t < 60.0]
        if len(history) >= self.max_calls_per_minute:
            raise CallRateLimitExceededError(
                f"Rate limit exceeded: Caller {caller_id} reached {len(history)} calls in the last minute (max {self.max_calls_per_minute})."
            )

        current_active = self._active_calls.get(caller_id, 0)
        if current_active >= self.max_concurrent:
            raise CallRateLimitExceededError(
                f"Concurrent call limit exceeded: Caller {caller_id} has {current_active} active calls (max {self.max_concurrent})."
            )

        self._active_calls[caller_id] = current_active + 1
        history.append(now)
        self._call_history[caller_id] = history

    def release_call_slot(self, caller_id: str):
        current_active = self._active_calls.get(caller_id, 0)
        if current_active > 0:
            self._active_calls[caller_id] = current_active - 1


class VoiceCallbackQueue:
    """
    Manages customer scheduled and overflow callback queues.
    Registers callback requests when all operator lines are busy or after business hours.
    """
    def __init__(self):
        # In-memory priority queue {tenant_id: [callback_record, ...]}
        self._queues: Dict[str, List[Dict[str, Any]]] = {}

    def enqueue_callback(
        self,
        tenant_id: str,
        caller_id: str,
        customer_name: Optional[str] = None,
        reason: str = "Operator queue busy",
        preferred_time: Optional[datetime] = None,
        priority: str = "NORMAL"
    ) -> Dict[str, Any]:
        """Enqueues a verified callback request."""
        import uuid
        callback_id = f"CB-{uuid.uuid4().hex[:8].upper()}"
        queue = self._queues.setdefault(tenant_id, [])
        record = {
            "callback_id": callback_id,
            "tenant_id": tenant_id,
            "caller_id": caller_id,
            "customer_name": customer_name or "Anonymous Caller",
            "reason": reason,
            "priority": priority,
            "preferred_time": preferred_time or datetime.now(timezone.utc),
            "status": "QUEUED",
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
            "queue_position": len(queue) + 1
        }
        queue.append(record)
        return record

    def list_callbacks(self, tenant_id: str, status: Optional[str] = "QUEUED") -> List[Dict[str, Any]]:
        queue = self._queues.get(tenant_id, [])
        if status:
            return [c for c in queue if c["status"] == status]
        return list(queue)

    def complete_callback(self, tenant_id: str, callback_id: str) -> bool:
        queue = self._queues.get(tenant_id, [])
        for c in queue:
            if c["callback_id"] == callback_id:
                c["status"] = "COMPLETED"
                c["completed_at"] = datetime.now(timezone.utc).isoformat()
                return True
        return False
