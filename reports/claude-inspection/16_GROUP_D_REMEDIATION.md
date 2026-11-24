# 16 — Group D (AI and voice) Remediation Record

- **Branch:** `fix/group-a-p0-remediation`, continuing after commit `3864e34`.
- **Scope:** remediation group D of report 11.
- **Approved downloads** (you chose them on 2026-11-24):
  - `faster-whisper` 1.2.1 + `ctranslate2` + `av`; the model weights (`faster-whisper-small`) were already in the local Hugging Face cache;
  - `piper-tts` 1.8.0;
  - Piper voices `fr_FR-siwis-medium`, `en_US-lessac-medium` and `ar_JO-kareem-medium` (~63 MB each), stored outside the repo in `%LOCALAPPDATA%\sales-ai\piper-voices`.

## What changed, per finding
| Finding | Fix | Main files |
|---|---|---|
| **F-15** placeholder speech | <ul><li>**Speech recognition:** the constant "Audio utterance processed" is replaced by real faster-whisper (`small`, CPU, int8) speech-to-text.</li><li>**Speech output:** the sine-wave "speech" is replaced by real Piper text-to-speech (CPU).</li><li>Both run off the event loop (`asyncio.to_thread`).</li><li>There is **no synthetic fallback**: a missing engine or voice raises `SpeechEngineUnavailableError`, and the turn degrades to text-only (no audio) and empty recognition. Nothing is invented.</li><li>Darija has no dedicated voice. Arabic-script replies use the Jordanian Arabic voice and Arabizi uses the French voice; both are flagged `pronunciation_approximate`.</li><li>TTS engine names in the configs (`Kokoro-82M`, which was never installed) now match the voices actually used.</li></ul> | `src/backend/voice/speech_engines.py`, `voice/multilingual_voice.py`, `voice/service.py`, `core/config.py`, `src/ai/config.py`, `src/ai/multilingual.py` |
| **F-17** keyword agents with hardcoded IDs | The keyword triggers with fixed parameters (`SKU-SOLAR-01`, `ORD-2026-99182`, `ACC-9921`, `INV-00442`, …) are removed. <ul><li>Each agent offers the model JSON-schema definitions of its **allowlisted** tools through Ollama native tool calling (`/api/chat`, `think: false`).</li><li>Proposed calls are capped at 3 per turn, re-checked against the role allowlist, and schema-validated by the Tool Gateway.</li><li>The instructions say identifiers must come from the user's message, and the domain handlers fail closed on unknown IDs.</li><li>If planning fails, the turn simply has no tool evidence, so the OutputGuard blocks any commercial claim.</li></ul> | `src/ai/agents/base.py`, `src/ai/providers/ollama_provider.py` (`plan_tool_calls`), `src/ai/model_gateway.py` |
| **F-18** RAG | <ul><li>The `/ai/rag/query` endpoint takes document ACL roles **only from the verified token**; client-supplied `user_roles` are ignored.</li><li>Agents retrieve with the **end user's** roles, limited to the agent's scope (`ServerSecurityContext.end_user_roles`); anonymous and customer callers get public documents only. This fixes the confused-deputy problem.</li><li>The embedding backend is explicit: real `embeddinggemma` via Ollama by default, or `RAG_EMBEDDING_BACKEND=hashing` for offline tests.</li><li>The silent MD5 fallback is gone. If the model is down, ingestion marks the document `PENDING_EMBEDDING` and retrieval raises (HTTP 503).</li><li>Each chunk records its `embedding_model` (migration `017`), and retrieval compares only vectors from the same model.</li></ul> | `src/ai/rag/service.py`, `src/backend/api/ai_governance.py`, `src/backend/api/agent_ecosystem.py`, `src/ai/tool_gateway.py`, `migrations/017_rag_embedding_model.sql` |
| **F-27** VRAM residency | The model lifecycle now reads what Ollama **actually** has resident (`/api/ps`) inside the cross-process lock, and evicts a conflicting 4B or 9B model even if another process loaded it. Embedding models are not treated as conflicts. | `src/ai/model_lifecycle.py` |

## Measured evidence (honest numbers)
- **`real_voice_turn_benchmark.json`** (`evidence/claude-inspection/benchmarks/`), from `scripts/benchmark_real_voice_turn.py`.
  - **Setup:** 6 audio-to-audio turns (fr, en, ar). Each turn: speech in → faster-whisper → warm `qwen3.5:4b` → Piper speech out. All timings are real.

| Measure | Result |
|---|---|
| Median total turn | **6,859 ms** |
| Max total turn | **7,596 ms** |
| Median recognition (ASR) | 1,591 ms |
| Median model reply (LLM, 48 tokens) | 4,879 ms |
| Median speech synthesis (TTS) | 194 ms |
| Word error rate: en | **0.0** |
| Word error rate: fr | **0.375** ("devis" heard as "de vie") |
| Word error rate: ar | **0.369** |

  - **Verdict:** the **600 ms target is not met.** The previously reported 518–569 ms was never a measurement.
  - **Caveat:** the caller audio was Piper-synthesized, not consented human recordings, so the WER figures are optimistic. There is no Darija or Arabizi audio corpus yet.
- **`live_agent_tool_calling.json`**, from `scripts/live_agent_tool_calling_check.py`: real `qwen3.5:4b` agent turns.
  - "Is PANEL-400 in stock?" → the model called `inventory.check_atp(PANEL-400)` and answered the correct 10 units.
  - Unknown order SO-999 → it called `orders.get_status`, got "not found", and invented nothing.
  - A greeting → no tool call.
  - **But** for the existing order SO-778 the model did **not** call the tool and asked for an email instead, so tool-selection recall is imperfect.
  - Turns took 17–81 s on this laptop (memory pressure: about 0.6 GB RAM free while Docker/WSL used 4 GB).

## Tests
- **New `tests/security/test_group_d_regressions.py`** (10 tests):
  - a model-proposed call runs against real domain data and grounds a "paid" claim;
  - disallowed or invented calls produce no evidence, so the claim is blocked;
  - no hardcoded tool IDs remain;
  - the embedding model is recorded and vector spaces never mix;
  - an embedding outage gives `PENDING_EMBEDDING` and a 503, not fake vectors;
  - the API ignores forged `user_roles`;
  - VRAM eviction is based on Ollama's live residency, and embedding models are exempt;
  - a missing voice fails closed;
  - Piper output is speech, not the old 3-sine tone (spectral check).
- **Updated tests:**

| Test | Change |
|---|---|
| `test_multilingual_voice_matrix.py` | Real TTS→STT round trip, and a sine tone is no longer turned into invented text. |
| TTS name assertions | Updated to the voices actually used. |
| Agent stub | Gained a `plan_tool_calls` method that proposes nothing. |

- **Full suite:** **440 passed, exit 0, 469 s** (`test-logs/remediation_d_full.log`), with the real speech engines and models.

## Still open after group D
- **Voice speed:** voice latency is ~7 s per turn. Reaching < 600 ms needs streaming STT/TTS, a smaller or faster ASR, a GPU or a stronger host, and LLM streaming into TTS.
- **Speech evaluation data:** there is no consented human audio corpus (fr, en, ar, ary-Arab, ary-Latn, code-switching), so speech WER is not established.
- **Tool selection:** tool recall is imperfect (the SO-778 case). Per-role held-out evaluations with real model outputs are still needed (the evaluators remain rule checks).
- **Vector index:** pgvector is not adopted (it needs a different Postgres image); similarity is still a full scan in Python.
- **Browser voice:** there is still no microphone capture or playback in the web UI (group E), and no WebRTC/SIP media server.
- **Other groups:** E (frontend) and F (TLS, observability, deployment) remain.
