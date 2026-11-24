# 06 — AI Agents, RAG and Model Infrastructure

## Agent catalog (registry `src/ai/agents/registry.py`)
The registry has 19 entries: the router classifier plus the 18 roles.
- **Supervisors (2):** `conversation_supervisor`, `operations_supervisor`.
- **Interactive (9):** `qualification_crm`, `product_knowledge`, `quote_pricing`, `order_payment`, `scheduling`, `negotiation_objections`, `support_returns`, `account_management`, `documents`.
- **Background (6):** `outreach`, `research`, `pipeline_coach`, `analyst` (the only `REASONING_9B` role), `knowledge_curator`, `incident_responder`.
- **Copilot (1):** `sales_copilot`.

How the roles are actually built:
- **All share one execution path:** `BaseAgent.execute` (`src/ai/agents/base.py:61-262`). Steps:
  1. Optional RAG lookup.
  2. **Keyword-triggered** tool calls with **hardcoded parameters**: `SKU-SOLAR-01`, `ORD-2026-99182`, `ACC-9921`, `INV-00442`, `date 2026-11-20`.
  3. One Model Gateway call.
  4. OutputGuard.
  5. Execution log row.
- **Role-specific code is 10–25 lines per role.** Example: `NegotiationAgent.evaluate_discount_request` is a single `>15%` comparison.
- **Supervisors:** 170 and 57 lines.
- **Verdict:** the agents are **thin wrappers around a shared prompt template**, not distinct, operational agents. The roles differ only in their prompt text and tool allowlist.

| Property | Observed |
|---|---|
| Tool permissions | Per-role allowlist enforced in `ToolGateway.is_tool_allowed` (good). |
| Tool execution | **No real handlers registered anywhere in `src/`**. `_execute_builtin_tool` returns constants: ATP 15, price 100000+VAT, order PAID, tracking `AMN-2026-88741` (F-07). |
| Model selection | 4B by default; 9B for the analyst only; the 9B request is downscaled unless `is_complex_reasoning`. All roles share one Ollama instance — matches the invariant. |
| Retrieval scope | Tenant-filtered. Uses the **role's** `retrieval_roles`, not the end user's (confused deputy, F-17). |
| Single conversation owner / human takeover | Implemented in the conversation service and supervisor with version fencing. Tested (`tests/concurrency/test_conversation_races.py`, `tests/voice/test_voice_agent_ecosystem_integration.py`). **Credit.** |
| Stale AI response | Turn/version fencing rejects stale turns (tested). |
| Background agents | No job dispatcher or scheduler exists. They run only when tests call them. Their tools are fixtures, so they cannot exceed their permissions, but that is because they do nothing real. |
| Auditability | `agent_execution_logs` row per execution (good). |

## RAG pipeline (9 stages)
| Stage | Status |
|---|---|
| 1 Ingestion | Implemented (`KnowledgeService.ingest_document`), SHA-256 dedup. |
| 2 Text extraction | Text only; no PDF/DOCX extraction. |
| 3 Chunking | Implemented. |
| 4 Embeddings | **Real `embeddinggemma` via Ollama** when it answers within 1.5 s; otherwise a **silent fallback to MD5-hash bag-of-words** vectors (`rag/service.py:33-90`). Spaces can mix. |
| 5 Vector storage | `DOUBLE PRECISION[]` in PostgreSQL; no pgvector; O(n) Python cosine. |
| 6 Permission filtering | Tenant filter OK; ACL roles = request body ∪ token (F-18). |
| 7 Context construction | Concatenated snippets in the prompt. |
| 8 Source attribution | Chunk/document IDs returned by the API; not cited in agent output. |
| 9 Grounded generation | Not grounded: guard fails open and tool evidence is fabricated. |

## Claim verification (F-08)
| Case | Result |
|---|---|
| `evidence=None` | Every claim passes (SEC-PROBE-10). |
| Currency before the number (`MAD 999`) or `dirhams` | Not parsed (SEC-PROBE-11). |
| Units | Evidence prices in cents vs claims in MAD — not normalised. |
| Stock claims | Pass when `verified_stock_atp` is empty. |

Prompt-injection defence is keyword/regex (`voice/security.py:73-115`, router). That is useful as a tripwire, but it is not comprehensive.

## Model infrastructure — measured on this laptop
Source: `evidence/claude-inspection/benchmarks/model_inference_benchmark.json`.
- Run: 2026-11-24, Ollama local, `num_predict` 128, `num_ctx` 4096, `think: false`, one French prompt.
- Hardware: i7-13620H, RTX 4060 Laptop 8 GB.

| Run | TTFT | Total | Load | Tokens | tok/s | Peak VRAM | Peak host RAM used |
|---|---|---|---|---|---|---|---|
| 4B cold | 15,154 ms | 16,791 ms | 14,586 ms | 95 | 57.96 | 3,749 MiB | 15,961 MiB |
| 4B warm #1 | 674 ms | 2,439 ms | 342 ms | 114 | 64.66 | 3,749 MiB | 15,571 MiB |
| 4B warm #2 | 744 ms | 2,577 ms | 287 ms | 118 | 64.58 | 3,749 MiB | 15,596 MiB |
| 9B cold (after 4B eviction) | 27,556 ms | 29,982 ms | 27,044 ms | 91 | 37.63 | 6,331 MiB | 15,845 MiB |

Notes on these numbers:
- Peak host RAM is the whole system, including the browser and Docker. It shows the 16 GB laptop running near its limit.
- **Timeout vs cold start:** the provider's default timeout is **5 s** (`ollama_provider.py:33`). Every cold start (15–28 s) therefore hits the fallback that returns *"[Local Ollama Simulated Output…] Processed request successfully"*. This is F-16.
- **Thinking text leaks:** the 9B answer returned through the project provider began with "Thinking Process:", because the provider returns `response or thinking` and does not disable thinking.

**VRAM mutual exclusion test:**
- Setup: a separate client left 4B resident (`keep_alive` 10 min). A fresh project process then asked for 9B through `OllamaProvider`.
- Result: no snapshot showed both models resident (max 1 model at a time).
- Why: the eviction was done by **Ollama's own scheduler** (8 GB could not hold both). The project process had `active_gpu_model=None` and did not evict.
- Verdict: the invariant held on this hardware, but **not because of the project's code** (F-27).

## Evaluation integrity
- `src/ai/evaluations/*.py` and `src/ai/voice/evaluator.py` run **deterministic rule checks**: keyword routing, regex guards. They never call a model.
- The "90 % LID / 100 % injection blocked" figures measure rule code on a **90-row text set written by the same author**. No held-out set, no audio, no model outputs.
- These figures are not evidence of production AI quality.
