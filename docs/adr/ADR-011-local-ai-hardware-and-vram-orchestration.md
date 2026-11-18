# ADR-011: Local AI Hardware Constraints, VRAM Budgeting, and Multi-Model Orchestration

## Status
Accepted

## Date
2026-11-18 (Updated with Live Hardware Telemetry)

## Context
The platform is developed and deployed on laptop hardware with strict physical resource constraints:
- **CPU**: Intel Core i7-13620H (10 cores: 6 P-cores, 4 E-cores, 16 threads, up to 4.9 GHz).
- **GPU**: NVIDIA GeForce RTX 4060 Laptop GPU with **8,188 MiB (8.0 GB) VRAM**.
- **System Memory**: **16 GB DDR5 RAM** (15.71 GB usable).
- **Environment**: Windows 11 + Docker Engine 29.9.3 + Ollama (GPU passthrough enabled on port 11434).

Live hardware benchmarking revealed that previously published theoretical memory estimates were underestimated:
- **`qwen3.5:4b`**: Published model size is 3.1 GB disk / ~3.3–4.0 GB weights. Measured runtime GPU VRAM with KV cache (2k–4k context) is **4,283.0 to 4,345.0 MiB** (4.3 GB).
- **`qwen3.5:9b-q4_K_M`**: Published model size is 6.1 GB disk / ~6.6 GB weights. Measured runtime GPU VRAM with KV cache (2k–4k context) is **6,823.0 to 6,894.0 MiB** (6.9 GB).
- **Co-Residency Impossibility**: 4,345 + 6,894 = **11,239 MiB (11.24 GB)** >> 8,188 MiB physical VRAM. Co-residency will immediately crash the GPU with a CUDA Out-Of-Memory (OOM) error.
- **`atlasia/moulsot.v0.3` (Moroccan Darija ASR)**: Model has ~2B parameters with **4.08 GB of BF16 tensor weights**, requiring ~5.6 GB host RAM in BF16 (or ~2.6 GB in INT8), not 650 MB. Attempting to load this model in memory on a 16 GB laptop alongside Docker and the OS will cause pagefile swapping and performance degradation.

## Decision
1. **Default Local Generation Model**:
   - `qwen3.5:4b` is the primary, default local generation model for all interactive conversational dialogue across all 18 agent roles.
   - Measured live throughput: **58.33 to 59.53 tokens/second**; warm TTFT: **2,991 ms**.
2. **Strict GPU Co-Residency Prohibition & Verified Eviction**:
   - **Under no circumstances may `qwen3.5:4b` and `qwen3.5:9b-q4_K_M` reside in GPU VRAM simultaneously.**
   - The Model Lifecycle Manager enforces mutual exclusion: when an expensive request justifies the 9B model, the 4B model must be evicted from VRAM via Ollama's `keep_alive: 0` API.
   - Eviction is verified against Ollama's `/api/ps` endpoint. If eviction fails or times out, the transition fails closed (`VRAMMutualExclusionError`) and the second model is blocked from loading.
3. **Selective 9B Reasoning Escalation**:
   - The 9B model is invoked exclusively for high-complexity analytical tasks: multi-tier quotation discount risk analysis, legal contract ambiguity checks, multi-warehouse constraint optimization, and post-call quality audits.
   - Measured live throughput: **40.79 to 41.09 tokens/second**; warm TTFT: **2,749 ms**; peak VRAM: **6,894 MiB** (safely below 7,000 MiB ceiling).
4. **CPU Allocation for Auxiliary Models**:
   - To preserve GPU VRAM exclusively for the active LLM:
     - Dense embeddings (`Qwen3-Embedding-0.6B`): CPU (1,100 MiB RAM).
     - Semantic reranker (`Qwen3-Reranker-0.6B`): CPU (1,100 MiB RAM).
     - ASR (`faster-whisper-small-int8`): CPU with CTranslate2 int8 quantization (280 MiB RAM).
     - TTS (`Kokoro-82M` & `Piper-ar_JO`): CPU (180 MiB / 75 MiB RAM).
   - This leaves the entire 8 GB GPU VRAM dedicated to the active LLM with zero GPU VRAM contention.
5. **Experimental Benchmarking Isolation for MoulSot**:
   - `atlasia/moulsot.v0.3` is designated as an **Experimental Benchmark Candidate**, kept strictly unloaded by default to protect host RAM.
   - Production speech recognition defaults to `faster-whisper-small-int8` with text-level Arabizi transliteration (`atlasia/Transliteration-Moroccan-Darija`).
6. **Thread-Safe Transition Locking**:
   - Model switching is protected by thread synchronization (`_transition_lock`), ensuring concurrent or overlapping requests are serialized without GPU VRAM race conditions.

## Invariants Enforced
- Maximum GPU VRAM consumption must never exceed 7,000 MiB under any workload.
- Business domain authority, RLS tenant isolation, and deterministic pricing services remain completely decoupled from and independent of local LLM inference.
- Development and automated testing can run 100% offline without mandatory cloud API keys.

## Consequences
### Positive
- Fully verified with live Docker Ollama telemetry: 4B runs at ~4.3 GB VRAM / ~59 tok/s; 9B runs at ~6.9 GB VRAM / ~41 tok/s; clean mutual exclusion cycle (4B -> 9B -> 4B) verified.
- Prevents catastrophic GPU OOM crashes and host system RAM exhaustion.
- Zero cloud API token expenses during local engineering, development, and unit testing.

### Negative / Trade-offs
- Cold switching between 4B and 9B models incurs a 13 to 19-second NVMe-to-VRAM model load time.
- 9B model is restricted to 4096 context window on this GPU (8192 context window risks exceeding 7.5 GB VRAM).

### Mitigation
- Scope 9B model executions strictly to asynchronous background tasks (Temporal activities) where disk load latency does not impact real-time customer chat.
