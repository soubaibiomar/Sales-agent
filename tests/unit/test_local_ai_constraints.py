"""
Unit tests validating Local AI Model Constraints, VRAM Mutual Exclusion, and Telemetry.
"""
import pytest
from src.ai.config import ai_config
from src.ai.resource_monitor import HardwareTelemetry, InferenceTracker
from src.ai.model_lifecycle import ModelLifecycleManager

def test_model_architecture_configuration():
    assert ai_config.primary_llm == "qwen3.5:4b"
    assert ai_config.reasoning_llm == "qwen3.5:9b-q4_K_M"
    assert ai_config.embedding_model == "Qwen3-Embedding-0.6B"
    assert ai_config.reranker_model == "Qwen3-Reranker-0.6B"
    assert ai_config.asr_model == "faster-whisper-small-int8"
    assert ai_config.darija_asr_candidate == "atlasia/moulsot.v0.3"
    assert ai_config.tts_fr_en == "Kokoro-82M"
    assert ai_config.tts_ar == "Piper-ar_JO"
    assert ai_config.darija_lid == "atlasia/DarijaLID"
    assert ai_config.arabizi_model == "atlasia/Transliteration-Moroccan-Darija"

def test_device_allocations_keep_auxiliaries_on_cpu():
    assert ai_config.embedding_device == "cpu"
    assert ai_config.reranker_device == "cpu"
    assert ai_config.asr_device == "cpu"
    assert ai_config.tts_device == "cpu"
    assert ai_config.primary_llm_device == "cuda"
    assert ai_config.reasoning_llm_device == "cuda"

def test_vram_mutual_exclusion_invariant():
    mgr = ModelLifecycleManager(ollama_url="http://localhost:11434")
    
    # Initial state
    assert mgr.active_gpu_model is None
    assert mgr.can_load_gpu_model("qwen3.5:4b") is True
    
    # Load 4B
    mgr.active_gpu_model = "qwen3.5:4b"
    assert mgr.can_load_gpu_model("qwen3.5:4b") is True
    
    # Attempting to co-load 9B while 4B is active must be rejected
    assert mgr.can_load_gpu_model("qwen3.5:9b-q4_K_M") is False
    
    # Preparing for inference with 9B must trigger eviction of 4B
    selected = mgr.prepare_for_inference("qwen3.5:9b-q4_K_M", is_complex_reasoning=True)
    assert selected == "qwen3.5:9b-q4_K_M"
    assert mgr.active_gpu_model == "qwen3.5:9b-q4_K_M"
    
    # While 9B is active, loading 4B directly without eviction must be rejected
    assert mgr.can_load_gpu_model("qwen3.5:4b") is False

def test_unjustified_9b_request_downgraded_to_4b():
    mgr = ModelLifecycleManager()
    # If is_complex_reasoning is False, request must be routed to 4B
    chosen = mgr.prepare_for_inference("qwen3.5:9b-q4_K_M", is_complex_reasoning=False)
    assert chosen == "qwen3.5:4b"
    assert mgr.active_gpu_model == "qwen3.5:4b"

def test_on_demand_darija_tools_lifecycle():
    mgr = ModelLifecycleManager()
    assert len(mgr.active_optional_cpu_models) == 0
    
    # Load Darija LID
    success = mgr.load_optional_darija_tool("atlasia/DarijaLID")
    assert success is True
    assert "atlasia/DarijaLID" in mgr.active_optional_cpu_models
    
    # Load Arabizi model
    success_trans = mgr.load_optional_darija_tool("atlasia/Transliteration-Moroccan-Darija")
    assert success_trans is True
    assert len(mgr.active_optional_cpu_models) == 2
    
    # Unload optional tools
    mgr.unload_optional_tools()
    assert len(mgr.active_optional_cpu_models) == 0

def test_hardware_telemetry_reads_ram_and_vram():
    ram = HardwareTelemetry.get_system_ram_mb()
    assert "total_mb" in ram
    assert ram["total_mb"] > 0
    assert "used_mb" in ram
    assert "free_mb" in ram
    
    gpu = HardwareTelemetry.get_gpu_vram_mb()
    assert "available" in gpu
    if gpu["available"]:
        assert gpu["total_mb"] >= 8000 # 8GB RTX 4060
        assert gpu["free_mb"] > 0

def test_inference_tracker_throughput_and_ttft():
    tracker = InferenceTracker("qwen3.5:4b")
    tracker.record_first_token()
    tracker.record_tokens(50)
    metrics = tracker.finish()
    
    assert metrics["model_name"] == "qwen3.5:4b"
    assert metrics["token_count"] == 50
    assert metrics["ttft_ms"] >= 0.0
    assert metrics["throughput_tok_per_sec"] >= 0.0
