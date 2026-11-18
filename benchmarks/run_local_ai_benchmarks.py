"""
Live Benchmark Suite for Local AI Models in Docker Ollama.
Measures cold start, warm inference, TTFT, tok/s, peak GPU VRAM, peak RAM,
and 4B -> 9B -> 4B mutual exclusion switching.
"""
import json
import os
import shutil
import subprocess
import time
import urllib.request
from typing import Dict, Any, List, Optional
import psutil

OLLAMA_URL = "http://127.0.0.1:11434"
EVIDENCE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evidence", "local-ai")
os.makedirs(EVIDENCE_DIR, exist_ok=True)

def get_vram_mb() -> float:
    """Returns GPU VRAM used in MB."""
    if not shutil.which("nvidia-smi"):
        return 0.0
    try:
        cmd = ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,nounits,noheader"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=3)
        return float(res.stdout.strip().splitlines()[0].strip())
    except Exception:
        return 0.0

def get_ram_mb() -> float:
    """Returns host RAM used in MB."""
    return round(psutil.virtual_memory().used / (1024 * 1024), 2)

def get_running_ollama_models() -> List[Dict[str, Any]]:
    """Queries /api/ps to see models resident in memory."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("models", [])
    except Exception as e:
        print("Error checking /api/ps:", e)
        return []

def unload_model(model_name: str) -> bool:
    """Evicts a model from VRAM."""
    try:
        payload = json.dumps({"model": model_name, "keep_alive": 0}).encode("utf-8")
        req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            pass
        time.sleep(1.0)
        return True
    except Exception as e:
        print(f"Error unloading {model_name}:", e)
        return False

def run_streaming_inference(model: str, prompt: str, num_ctx: int = 2048, max_tokens: int = 128) -> Dict[str, Any]:
    """Runs streaming inference and measures TTFT, duration, throughput, and memory peaks."""
    start_vram = get_vram_mb()
    start_ram = get_ram_mb()
    
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": max_tokens,
            "temperature": 0.2
        }
    }
    
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=req_data, headers={"Content-Type": "application/json"})
    
    start_time = time.perf_counter()
    first_token_time = None
    token_count = 0
    peak_vram = start_vram
    peak_ram = start_ram
    generated_text = []
    ollama_meta = {}

    with urllib.request.urlopen(req, timeout=120) as resp:
        for line in resp:
            if not line:
                continue
            chunk = json.loads(line.decode("utf-8"))
            if not first_token_time and chunk.get("response"):
                first_token_time = time.perf_counter()
            
            if chunk.get("response"):
                token_count += 1
                generated_text.append(chunk.get("response"))
                
            cur_vram = get_vram_mb()
            cur_ram = get_ram_mb()
            if cur_vram > peak_vram:
                peak_vram = cur_vram
            if cur_ram > peak_ram:
                peak_ram = cur_ram
                
            if chunk.get("done"):
                ollama_meta = chunk

    end_time = time.perf_counter()
    total_sec = end_time - start_time
    ttft_ms = (first_token_time - start_time) * 1000.0 if first_token_time else total_sec * 1000.0
    
    eval_count = ollama_meta.get("eval_count", token_count)
    eval_duration_ns = ollama_meta.get("eval_duration", 0)
    
    tok_per_sec = 0.0
    if eval_duration_ns > 0:
        tok_per_sec = round(eval_count / (eval_duration_ns / 1e9), 2)
    elif total_sec > 0:
        tok_per_sec = round(token_count / total_sec, 2)

    return {
        "model": model,
        "num_ctx": num_ctx,
        "token_count": eval_count,
        "ttft_ms": round(ttft_ms, 2),
        "total_duration_sec": round(total_sec, 3),
        "tokens_per_sec": tok_per_sec,
        "start_vram_mb": start_vram,
        "peak_vram_mb": peak_vram,
        "delta_vram_mb": round(peak_vram - start_vram, 2),
        "start_ram_mb": start_ram,
        "peak_ram_mb": peak_ram,
        "delta_ram_mb": round(peak_ram - start_ram, 2),
        "ollama_meta": {
            "load_duration_ms": round(ollama_meta.get("load_duration", 0) / 1e6, 2),
            "prompt_eval_duration_ms": round(ollama_meta.get("prompt_eval_duration", 0) / 1e6, 2),
            "eval_duration_ms": round(ollama_meta.get("eval_duration", 0) / 1e6, 2),
        }
    }

def main():
    print("=== LIVE HARDWARE BENCHMARK: LOCAL OLLAMA INFERENCE & VRAM TELEMETRY ===")
    
    # 0. Clean initial state: ensure no models in memory
    for m in get_running_ollama_models():
        unload_model(m.get("name"))
    time.sleep(2)
    
    initial_running = get_running_ollama_models()
    baseline_vram = get_vram_mb()
    baseline_ram = get_ram_mb()
    print(f"Baseline State: Running models={len(initial_running)}, GPU VRAM={baseline_vram} MB, Host RAM={baseline_ram} MB")
    
    results = {
        "hardware": {
            "cpu": "Intel Core i7-13620H",
            "gpu": "NVIDIA GeForce RTX 4060 Laptop (8188 MiB)",
            "total_ram_mb": round(psutil.virtual_memory().total / (1024 * 1024), 2),
            "baseline_vram_mb": baseline_vram,
            "baseline_ram_mb": baseline_ram
        },
        "benchmarks": {}
    }

    # 1. Benchmark Qwen3.5 4B Cold Start
    print("\n--- 1. Testing qwen3.5:4b (Cold Start, ctx=2048) ---")
    cold_4b = run_streaming_inference("qwen3.5:4b", "Explain enterprise sales pipeline in two sentences.", num_ctx=2048, max_tokens=60)
    print(f"Cold Start 4B: TTFT={cold_4b['ttft_ms']}ms, Tok/s={cold_4b['tokens_per_sec']}, Peak VRAM={cold_4b['peak_vram_mb']}MB, Load={cold_4b['ollama_meta']['load_duration_ms']}ms")
    results["benchmarks"]["4b_cold_start"] = cold_4b

    # 2. Benchmark Qwen3.5 4B Warm Inference
    print("\n--- 2. Testing qwen3.5:4b (Warm Inference, ctx=2048) ---")
    warm_4b = run_streaming_inference("qwen3.5:4b", "List 3 key metrics for sales forecasting.", num_ctx=2048, max_tokens=60)
    print(f"Warm 4B: TTFT={warm_4b['ttft_ms']}ms, Tok/s={warm_4b['tokens_per_sec']}, Peak VRAM={warm_4b['peak_vram_mb']}MB")
    results["benchmarks"]["4b_warm_inference"] = warm_4b

    # 3. Benchmark Qwen3.5 4B High Context (4096 tokens)
    print("\n--- 3. Testing qwen3.5:4b (Context=4096) ---")
    ctx_prompt_4b = "Context summary: " + ("Enterprise procurement and inventory contract requirements. " * 50) + "Question: summarize in 3 bullets."
    ctx_4b = run_streaming_inference("qwen3.5:4b", ctx_prompt_4b, num_ctx=4096, max_tokens=60)
    print(f"High-Ctx 4B (4096): TTFT={ctx_4b['ttft_ms']}ms, Tok/s={ctx_4b['tokens_per_sec']}, Peak VRAM={ctx_4b['peak_vram_mb']}MB")
    results["benchmarks"]["4b_ctx_4096"] = ctx_4b

    # Check active models in memory
    mid_running = get_running_ollama_models()
    print(f"Currently in Ollama memory after 4B: {[m['name'] for m in mid_running]}")
    results["benchmarks"]["4b_resident_models"] = mid_running

    # 4. Evict 4B
    print("\n--- 4. Evicting qwen3.5:4b from VRAM ---")
    unload_model("qwen3.5:4b")
    post_4b_unload_vram = get_vram_mb()
    running_after_unload = get_running_ollama_models()
    print(f"Post-Unload 4B: Running models={len(running_after_unload)}, VRAM={post_4b_unload_vram} MB")
    results["benchmarks"]["4b_post_unload"] = {
        "running_models": len(running_after_unload),
        "vram_mb": post_4b_unload_vram
    }

    # 5. Benchmark Qwen3.5 9B Q4_K_M Cold Start
    print("\n--- 5. Testing qwen3.5:9b-q4_K_M (Cold Start, ctx=2048) ---")
    cold_9b = run_streaming_inference("qwen3.5:9b-q4_K_M", "Analyze risk factors in a 30% discount approval for an enterprise customer in two sentences.", num_ctx=2048, max_tokens=60)
    print(f"Cold Start 9B: TTFT={cold_9b['ttft_ms']}ms, Tok/s={cold_9b['tokens_per_sec']}, Peak VRAM={cold_9b['peak_vram_mb']}MB, Load={cold_9b['ollama_meta']['load_duration_ms']}ms")
    results["benchmarks"]["9b_cold_start"] = cold_9b

    # 6. Benchmark Qwen3.5 9B Warm Inference
    print("\n--- 6. Testing qwen3.5:9b-q4_K_M (Warm Inference, ctx=2048) ---")
    warm_9b = run_streaming_inference("qwen3.5:9b-q4_K_M", "Evaluate contract ambiguity in supply chain agreements.", num_ctx=2048, max_tokens=60)
    print(f"Warm 9B: TTFT={warm_9b['ttft_ms']}ms, Tok/s={warm_9b['tokens_per_sec']}, Peak VRAM={warm_9b['peak_vram_mb']}MB")
    results["benchmarks"]["9b_warm_inference"] = warm_9b

    # 7. Benchmark Qwen3.5 9B Context=4096
    print("\n--- 7. Testing qwen3.5:9b-q4_K_M (Context=4096) ---")
    ctx_prompt_9b = "Legal review clauses: " + ("Standard indemnity and warranty limitations in B2B SaaS agreements. " * 40) + "Conclusion in 2 sentences."
    ctx_9b = run_streaming_inference("qwen3.5:9b-q4_K_M", ctx_prompt_9b, num_ctx=4096, max_tokens=60)
    print(f"High-Ctx 9B (4096): TTFT={ctx_9b['ttft_ms']}ms, Tok/s={ctx_9b['tokens_per_sec']}, Peak VRAM={ctx_9b['peak_vram_mb']}MB")
    results["benchmarks"]["9b_ctx_4096"] = ctx_9b

    # Verify 9B memory residency
    mid_running_9b = get_running_ollama_models()
    print(f"Currently in Ollama memory after 9B: {[m['name'] for m in mid_running_9b]}")
    results["benchmarks"]["9b_resident_models"] = mid_running_9b

    # 8. Evict 9B
    print("\n--- 8. Evicting qwen3.5:9b-q4_K_M from VRAM ---")
    unload_model("qwen3.5:9b-q4_K_M")
    post_9b_unload_vram = get_vram_mb()
    running_after_9b_unload = get_running_ollama_models()
    print(f"Post-Unload 9B: Running models={len(running_after_9b_unload)}, VRAM={post_9b_unload_vram} MB")
    results["benchmarks"]["9b_post_unload"] = {
        "running_models": len(running_after_9b_unload),
        "vram_mb": post_9b_unload_vram
    }

    # 9. Mutual Exclusion Cycle Test: 4B -> 9B -> 4B
    print("\n--- 9. Executing Full Mutual Exclusion Cycle: 4B -> 9B -> 4B ---")
    cycle_history = []
    
    # Step A: Load 4B
    run_streaming_inference("qwen3.5:4b", "Step A: quick ping.", max_tokens=10)
    mods_a = get_running_ollama_models()
    vram_a = get_vram_mb()
    print(f"Cycle Step A (4B loaded): Models={[m['name'] for m in mods_a]}, VRAM={vram_a}MB")
    cycle_history.append({"step": "Load 4B", "models": [m['name'] for m in mods_a], "vram_mb": vram_a})
    assert len(mods_a) == 1 and "4b" in mods_a[0]['name']

    # Step B: Transition to 9B (Evict 4B first, then load 9B)
    unload_model("qwen3.5:4b")
    run_streaming_inference("qwen3.5:9b-q4_K_M", "Step B: reasoning ping.", max_tokens=10)
    mods_b = get_running_ollama_models()
    vram_b = get_vram_mb()
    print(f"Cycle Step B (9B loaded, 4B evicted): Models={[m['name'] for m in mods_b]}, VRAM={vram_b}MB")
    cycle_history.append({"step": "Transition to 9B", "models": [m['name'] for m in mods_b], "vram_mb": vram_b})
    # Check that 4B is NOT in memory
    assert not any("4b" in m['name'] for m in mods_b), "Mutual exclusion violation: 4B still resident with 9B!"
    assert len(mods_b) == 1 and "9b" in mods_b[0]['name']

    # Step C: Transition back to 4B (Evict 9B first, then load 4B)
    unload_model("qwen3.5:9b-q4_K_M")
    run_streaming_inference("qwen3.5:4b", "Step C: restore 4B ping.", max_tokens=10)
    mods_c = get_running_ollama_models()
    vram_c = get_vram_mb()
    print(f"Cycle Step C (4B restored, 9B evicted): Models={[m['name'] for m in mods_c]}, VRAM={vram_c}MB")
    cycle_history.append({"step": "Restore 4B", "models": [m['name'] for m in mods_c], "vram_mb": vram_c})
    assert not any("9b" in m['name'] for m in mods_c), "Mutual exclusion violation: 9B still resident with 4B!"
    assert len(mods_c) == 1 and "4b" in mods_c[0]['name']

    results["benchmarks"]["mutual_exclusion_cycle"] = cycle_history

    # Final cleanup
    unload_model("qwen3.5:4b")
    
    # Save full JSON evidence
    json_path = os.path.join(EVIDENCE_DIR, "live_benchmark_evidence.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nAll benchmark results saved to: {json_path}")

if __name__ == "__main__":
    main()
