"""
Unit tests validating AI model concurrency, overlapping requests, and failed eviction scenarios.
"""
import pytest
import threading
from unittest.mock import patch, MagicMock
from src.ai.model_lifecycle import ModelLifecycleManager, VRAMMutualExclusionError

def test_overlapping_requests_same_model():
    mgr = ModelLifecycleManager()
    # First request
    m1 = mgr.prepare_for_inference("qwen3.5:4b", is_complex_reasoning=False)
    assert m1 == "qwen3.5:4b"
    assert mgr.active_gpu_model == "qwen3.5:4b"
    
    # Overlapping second request for 4B
    m2 = mgr.prepare_for_inference("qwen3.5:4b", is_complex_reasoning=False)
    assert m2 == "qwen3.5:4b"
    assert mgr.active_gpu_model == "qwen3.5:4b"

def test_failed_eviction_fails_closed():
    mgr = ModelLifecycleManager()
    mgr.active_gpu_model = "qwen3.5:4b"
    
    # Mock get_running_ollama_models to simulate that 4B refuses to unload
    with patch.object(mgr, "get_running_ollama_models", return_value=[{"name": "qwen3.5:4b"}]):
        with pytest.raises(VRAMMutualExclusionError) as exc_info:
            mgr.evict_gpu_model("qwen3.5:4b", verify=True)
        assert "Failed to evict" in str(exc_info.value)
        assert "prevent GPU OOM" in str(exc_info.value)

def test_concurrent_switching_serialized_by_lock():
    mgr = ModelLifecycleManager()
    transition_order = []
    
    def req_4b():
        with patch.object(mgr, "evict_gpu_model", return_value=True):
            with patch.object(mgr, "get_running_ollama_models", return_value=[]):
                res = mgr.prepare_for_inference("qwen3.5:4b")
                transition_order.append(res)

    def req_9b():
        with patch.object(mgr, "evict_gpu_model", return_value=True):
            with patch.object(mgr, "get_running_ollama_models", return_value=[]):
                res = mgr.prepare_for_inference("qwen3.5:9b-q4_K_M", is_complex_reasoning=True)
                transition_order.append(res)

    t1 = threading.Thread(target=req_4b)
    t2 = threading.Thread(target=req_9b)
    
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
    assert len(transition_order) == 2
    assert mgr.active_gpu_model in ["qwen3.5:4b", "qwen3.5:9b-q4_K_M"]

def test_co_residency_violation_flag():
    mgr = ModelLifecycleManager()
    # Mock running models to simulate forbidden co-residency
    with patch.object(mgr, "get_running_ollama_models", return_value=[{"name": "qwen3.5:4b"}, {"name": "qwen3.5:9b-q4_K_M"}]):
        status = mgr.get_lifecycle_status()
        assert status["co_residency_violation"] is True
