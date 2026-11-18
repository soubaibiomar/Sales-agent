# ADR-011: Local AI Hardware Constraints, VRAM Budgeting, and Multi-Model Orchestration

## Status
Accepted

## Date
2026-11-18

## Context
The platform is developed and deployed on laptop hardware with strict physical resource constraints:
- **CPU**: Intel Core i7-13620H (10 cores: 6 P-cores, 4 E-cores, 16 threads).
- **GPU**: NVIDIA GeForce RTX 4060 Laptop GPU with **8,188 MiB (8 GB) VRAM**.
- **System Memory**: **16 GB DDR5 RAM**.
- **Environment**: Windows 11 + Docker + Ollama (GPU passthrough enabled on port 11434).

The platform requires a multi-modal AI stack comprising:
- Primary conversational LLM: `qwen3.5:4b`
- Complex reasoning LLM: `qwen3.5:9b-q4_K_M`
- Dense text embeddings: `Qwen3-Embedding-0.6B`
- Semantic reranker: `Qwen3-Reranker-0.6B`
- Automated Speech Recognition (ASR): `faster-whisper-small-int8` (plus `atlasia/moulsot.v0.3` for Darija)
- Text-to-Speech (TTS): `Kokoro-82M` (FR/EN) and `Piper-ar_JO` (Arabic)
- Language Identification (LID): `atlasia/DarijaLID`
- Transliteration: `atlasia/Transliteration-Moroccan-Darija`

Attempting to load all models onto the 8 GB GPU simultaneously is physically impossible:
- 4B LLM: ~2.8 GB VRAM
- 9B Q4_K_M LLM: ~5.8 GB VRAM
- Combined LLMs alone: 2.8 + 5.8 = 8.6 GB > 8.0 GB available VRAM, causing immediate CUDA Out-Of-Memory (OOM), OS display driver crashes, or heavy system swapping.

## Decision
1. **Default Local Generation Model**:
   - `qwen3.5:4b` is the primary, default local generation model for all interactive conversational dialogue across all 18 agent roles.
2. **Strict GPU Co-Residency Prohibition**:
   - **Under no circumstances may `qwen3.5:4b` and `qwen3.5:9b-q4_K_M` reside in GPU VRAM simultaneously.**
   - The Model Lifecycle Manager enforces mutual exclusion: when an expensive request justifies the 9B model, the 4B model must be evicted from VRAM via Ollama's `keep_alive: 0` API before the 9B model is loaded. Once 9B reasoning finishes, it is evicted and 4B reloaded.
3. **Selective 9B Reasoning Escalation**:
   - The 9B model is invoked exclusively for high-complexity analytical tasks: multi-tier quotation discount risk analysis, legal contract ambiguity checks, multi-warehouse constraint optimization, and post-call quality audits.
4. **CPU Allocation for Auxiliary Models**:
   - To preserve GPU VRAM exclusively for the active LLM:
     - Dense embeddings (`Qwen3-Embedding-0.6B`): CPU (ONNX / HuggingFace runtime).
     - Semantic reranker (`Qwen3-Reranker-0.6B`): CPU.
     - ASR (`faster-whisper-small-int8`): CPU with CTranslate2 int8 quantization.
     - TTS (`Kokoro-82M` & `Piper-ar_JO`): CPU (sub-50ms synthesis).
   - This leaves ~5.2 GB of GPU VRAM free for the active 4B model (context window up to 8k tokens) without any GPU contention.
5. **On-Demand Loading for Moroccan Darija Models**:
   - `atlasia/DarijaLID`, `atlasia/Transliteration-Moroccan-Darija`, and `atlasia/moulsot.v0.3` are loaded into host RAM on demand only when Darija/Arabizi input is identified.
6. **Hardware Telemetry & Performance Tracking**:
   - The system tracks real-time RAM, VRAM, Time-to-First-Token (TTFT), and generation throughput (tokens/second), emitting warnings if VRAM exceeds 85% (6.8 GB) or RAM exceeds 85% (13.6 GB).
7. **Model-Provider Abstraction**:
   - Core domain logic interacts with `BaseModelProvider`. The platform supports seamless switching between `OllamaProvider` (offline local default) and cloud providers (`GeminiProvider`, `OpenAIProvider`, `AnthropicProvider`) via configuration flags.

## Invariants Enforced
- Maximum GPU VRAM consumption must never exceed 7.0 GB under any workload.
- Business domain authority, RLS tenant isolation, and deterministic pricing services remain completely decoupled from and independent of local LLM inference.
- Development and automated testing can run 100% offline without mandatory cloud API keys.

## Consequences
### Positive
- The entire multi-agent, voice-capable enterprise platform runs reliably on a standard 8 GB RTX 4060 laptop without CUDA crashes.
- Zero cloud API token expenses during local engineering, development, and unit testing.
- Clean path to migrate to dedicated multi-GPU or cloud infrastructure in production by swapping provider configuration.

### Negative / Trade-offs
- Switching between 4B and 9B models incurs a 2 to 4-second model load/unload delay.
- Running embeddings and ASR on CPU utilizes host CPU cycles, requiring careful threading allocation (`OMP_NUM_THREADS=4`).

### Mitigation
- Keep 9B escalations asynchronous or scoped to batch background agents (Temporal activities) where a 3-second model load latency is negligible.
