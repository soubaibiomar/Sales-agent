"""
Step 02 AI Model Governance & Hardware Safety Test Suite.
Tests:
1. Cross-process FileLock synchronization on GPU model lifecycle transitions (Req 3).
2. Enforcement of 4,096-token context limit for Qwen3.5 9B (Req 4).
3. Prevention of synchronous 9B invocation during live voice calls (Req 5).
4. Preservation of 4B/9B mutual exclusion (eviction before switch) (Req 6).
"""
import pytest
import os
import tempfile
import asyncio
from unittest.mock import patch, MagicMock
from filelock import FileLock

from src.ai.model_lifecycle import (
    ModelLifecycleManager, VRAMMutualExclusionError, VRAMEvictionConflictError,
    VoiceModelSafetyError, lifecycle_manager
)
from src.ai.providers.ollama_provider import OllamaProvider, MAX_9B_CONTEXT_TOKENS
from src.ai.config import ai_config

def test_cross_process_file_lock_synchronization():
    """
    Requirement 3:
    Verifies that ModelLifecycleManager uses a cross-process FileLock.
    Simulates another process holding the lock and confirms fail-safe timeout / blocking behavior.
    """
    temp_lock_file = os.path.join(tempfile.gettempdir(), f"test_gpu_lock_{os.getpid()}.lock")
    manager = ModelLifecycleManager(lock_path=temp_lock_file)
    
    # 1. Acquire the lock externally (simulating external worker process)
    external_lock = FileLock(temp_lock_file, timeout=0.1)
    external_lock.acquire()
    
    try:
        # 2. Manager instantiation with short timeout should detect file is locked
        conflict_manager = ModelLifecycleManager(lock_path=temp_lock_file)
        conflict_manager._file_lock.timeout = 0.2
        
        with pytest.raises(Exception): # FileLock.Timeout
            conflict_manager.prepare_for_inference("qwen3.5:4b")
    finally:
        external_lock.release()
        if os.path.exists(temp_lock_file):
            try:
                os.remove(temp_lock_file)
            except Exception:
                pass

def test_prevent_synchronous_9b_during_voice_calls():
    """
    Requirement 5 & SAI-08:
    Live voice calls cannot invoke the 9B model synchronously because model eviction
    and reload would introduce multiple seconds of latency, destroying real-time conversational cadence.
    Must raise VoiceModelSafetyError.
    """
    manager = ModelLifecycleManager()
    
    # 1. Attempting to request 9B in voice channel must fail immediately
    with pytest.raises(VoiceModelSafetyError) as exc_info:
        manager.prepare_for_inference(
            requested_model="qwen3.5:9b-q4_K_M",
            is_complex_reasoning=True,
            channel="voice"
        )
    assert "Synchronous 9B invocation is strictly prohibited during live voice calls" in str(exc_info.value)

    # 2. Attempting complex reasoning flag on voice channel must also fail
    with pytest.raises(VoiceModelSafetyError):
        manager.prepare_for_inference(
            requested_model="qwen3.5:4b",
            is_complex_reasoning=True,
            channel="voice"
        )

    # 3. Requesting primary 4B model in voice channel must succeed
    result_model = manager.prepare_for_inference(
        requested_model="qwen3.5:4b",
        is_complex_reasoning=False,
        channel="voice"
    )
    assert "4b" in result_model.lower()

@pytest.mark.asyncio
async def test_enforce_4096_context_limit_for_9b():
    """
    Requirement 4 & Hardware Envelope:
    Verifies that OllamaProvider clamps context window to 4096 tokens max for Qwen3.5 9B.
    Requests exceeding 4096 tokens (e.g. 8192) are clamped to 4096 tokens.
    """
    provider = OllamaProvider()

    # Test with 9B requested context exceeding 4096
    res = await provider.generate(
        prompt="Analyze complex financial statement.",
        model="qwen3.5:9b-q4_K_M",
        context_length=8192
    )

    # Effective num_ctx in result must be capped at 4096
    assert res["num_ctx"] == 4096
    assert res["num_ctx"] <= MAX_9B_CONTEXT_TOKENS

@pytest.mark.asyncio
async def test_voice_channel_guard_in_provider():
    """Verifies that OllamaProvider enforces the voice channel guard end-to-end."""
    provider = OllamaProvider()

    with pytest.raises(VoiceModelSafetyError):
        await provider.generate(
            prompt="Spoken inquiry from customer.",
            model="qwen3.5:9b-q4_K_M",
            channel="voice"
        )

def test_mutual_exclusion_cycle_preservation():
    """
    Requirement 6:
    Verifies that when 4B is active, loading 9B triggers eviction of 4B,
    and vice-versa, maintaining zero co-residency.
    """
    manager = ModelLifecycleManager()
    
    with patch.object(manager, "evict_gpu_model", return_value=True) as mock_evict:
        # Load 4B
        m1 = manager.prepare_for_inference("qwen3.5:4b")
        assert "4b" in m1.lower()
        mock_evict.assert_not_called()

        # Request 9B with complex reasoning justification -> must evict 4B
        m2 = manager.prepare_for_inference("qwen3.5:9b-q4_K_M", is_complex_reasoning=True)
        assert "9b" in m2.lower()
        mock_evict.assert_called_with("qwen3.5:4b", verify=True)

def test_active_generation_lease_blocks_eviction():
    """
    Finding AI-01 Remediation:
    Verifies that an active generation lease prevents model eviction,
    failing closed with VRAMEvictionConflictError to prevent truncating an active token stream.
    """
    manager = ModelLifecycleManager()
    model = "qwen3.5:4b"
    manager.active_gpu_model = model

    # 1. Acquire lease
    with manager.generation_lease(model) as lease_id:
        assert manager.get_active_lease_count(model) == 1
        # 2. Attempting eviction while leased must raise VRAMEvictionConflictError
        with pytest.raises(VRAMEvictionConflictError) as exc:
            manager.evict_gpu_model(model)
        assert "active generation lease(s) in flight" in str(exc.value)

    # 3. After lease release, lease count drops to 0 and eviction is permitted
    assert manager.get_active_lease_count(model) == 0
    with patch.object(manager, "get_running_ollama_models", return_value=[]):
        with patch("src.ai.model_lifecycle.httpx.post"):
            success = manager.evict_gpu_model(model, verify=False)
            assert success is True

def test_active_generation_lease_blocks_model_switching():
    """
    Finding AI-01 Remediation:
    Verifies that if Process 1 has an active generation lease on 4B,
    Process 2 requesting 9B cannot evict 4B and is rejected with VRAMEvictionConflictError.
    """
    manager = ModelLifecycleManager()
    manager.active_gpu_model = "qwen3.5:4b"

    with manager.generation_lease("qwen3.5:4b"):
        # Attempting to prepare 9B requires evicting 4B, which must be blocked
        with pytest.raises(VRAMEvictionConflictError) as exc:
            manager.prepare_for_inference("qwen3.5:9b-q4_K_M", is_complex_reasoning=True)
        assert "Cannot switch to" in str(exc.value)
        assert "active generation lease(s) in flight" in str(exc.value)

@pytest.mark.asyncio
async def test_streaming_holds_active_generation_lease():
    """
    Finding AI-01 Remediation:
    Verifies that OllamaProvider.stream holds a generation lease during token consumption,
    preventing eviction mid-stream.
    """
    provider = OllamaProvider()
    stream_gen = provider.stream("Stream prompt", model="qwen3.5:4b")

    # Fetch first chunk from generator
    # Real token from the local model (the provider no longer emits canned text)
    first_chunk = await stream_gen.__anext__()
    assert isinstance(first_chunk, str) and first_chunk

    # While stream is open, active lease must be held for 4B
    assert lifecycle_manager.get_active_lease_count("qwen3.5:4b") >= 1
    with pytest.raises(VRAMEvictionConflictError):
        lifecycle_manager.evict_gpu_model("qwen3.5:4b")

    # Consume remaining chunks until stream ends
    try:
        while True:
            await stream_gen.__anext__()
    except StopAsyncIteration:
        pass

    # Once stream completes, lease must be released
    assert lifecycle_manager.get_active_lease_count("qwen3.5:4b") == 0
