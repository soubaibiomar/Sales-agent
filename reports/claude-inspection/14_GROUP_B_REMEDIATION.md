# 14 — Group B Remediation Record

- **Branch:** `fix/group-a-p0-remediation`, continuing after commit `5d3abb0`.
- **Scope:** remediation group B of report 11.

## What changed, per finding
| Finding | Fix | Main files |
|---|---|---|
| **F-16** fabricated model output | <ul><li>The Ollama provider uses async `httpx`. It no longer blocks the event loop with `urllib`.</li><li>Every failure raises `ModelUnavailableError`. The "[Local Ollama Simulated Output] … Processed request successfully" fallback is gone.</li><li>Requests send `think: false`, and only the `response` field is returned, so reasoning text no longer leaks.</li><li>Timeouts are sized from the measured cold starts (60 s for 4B, 90 s for 9B). The gateway's 5 s default budget is removed; an explicit budget is still honoured.</li><li>Streaming and embeddings now call the model for real. The reranker refuses, because no reranker model is installed.</li><li>The cloud "fallback" no longer returns canned text; it raises until a real client exists.</li><li>When the model is unavailable, the gateway returns status `UNAVAILABLE_HANDOFF` with a human hand-off message, and the agent records `MODEL_UNAVAILABLE_HANDOFF`.</li><li>New optional setting `AI_WARMUP_ON_STARTUP` preloads the 4B model at startup.</li></ul> | `src/ai/providers/ollama_provider.py`, `src/ai/providers/cloud_provider.py`, `src/ai/model_gateway.py`, `src/ai/agents/base.py`, `src/backend/main.py` |
| **F-14** public quote accept/reject | `/quotes/{id}/send` returns an HMAC-signed link token bound to (purpose, tenant, quote, **version**, expiry). Accept and reject require that token. The tenant comes from the verified token, so the endpoints also work under RLS. Editing the quote bumps its version and voids old links (HTTP 409). The client IP is recorded with the acceptance note. New secret `QUOTE_LINK_SECRET` is covered by the startup secret guard. | `src/backend/core/signed_links.py`, `src/backend/api/quotes.py`, `schemas/quotes.py`, `core/config.py` |
| **F-11** cross-tenant foreign keys | Migration `012` adds `UNIQUE (tenant_id, id)` on 29 parent tables and a same-tenant composite foreign key alongside each of the **122** foreign keys between tenant-scoped tables. The migration was generated from the live catalog; the original foreign keys are kept for their ON DELETE behaviour. Re-running the inspection probe gives `REJECTED: ForeignKeyViolation` (`evidence/claude-inspection/db/cross_tenant_fk_probe_post_fix.json`). | `migrations/012_same_tenant_fks_and_commerce_invariants.sql` (also appended to `infra/init-db.sql` and applied to the dev DB) |
| **F-28** missing business constraints | <ul><li>Unique `(tenant_id, quote_id)` on orders.</li><li>Unique idempotency keys on refunds and on payment intents.</li><li>CHECKs on refund amount (> 0), payment and order amounts (≥ 0), item quantities (> 0) and inventory quantities (≥ 0).</li><li>A `btree_gist` exclusion constraint prevents overlapping active bookings for the same staff member.</li><li>The booking advisory-lock key used Python's per-process randomised `hash()`; it is now a deterministic SHA-256-derived key.</li></ul>**Defect caught by the new CHECK:** dispatching a shipment for a SKU with no stock created the item and drove it to −1. Dispatch now refuses with `InsufficientStockForShipmentError`. | migration `012`, `domains/scheduling/service.py`, `domains/logistics/service.py` |
| **F-34** permission catalog | 18 permission codes required by routes (CRM, logistics, support, scheduling, procurement, orders, AI, voice copilot…) were granted to **no** role except `super_admin`. The default role map is now complete, migration `013` seeds the 4 codes missing from the catalog, and a new test enforces that every route permission is both seeded and granted to a regular role. | `core/policy_service.py`, `migrations/013_permission_catalog_completion.sql`, `tests/security/test_permission_catalog_coverage.py` |
| **F-31** analytics honesty | <ul><li>New `holdout_backtest`: the model is trained on the first n−k days and scored on the last k (k ≤ 14) against two naive baselines (last value, 7-day mean).</li><li>`is_superior_to_baseline` now comes only from that held-out comparison. It is `null` when history is too short.</li><li>The in-sample metric is labelled `in_sample_fit_metrics`; the `backtest_metrics` key is kept for API compatibility.</li><li>The executive overview adds cash revenue (`collected_revenue_cents`, `collected_net_revenue_cents`, from successful CAPTURE/REFUND transactions) and documents each revenue definition.</li><li>Refunds are now filtered by currency.</li></ul> | `domains/analytics/forecasting.py`, `domains/analytics/sales_analytics.py` |
| **F-19** no worker | New process `python -m src.backend.worker` (`--once` for cron or tests). For each active tenant, under RLS, it relays the outbox (SKIP LOCKED + fencing, so several workers are safe) and expires stale stock reservations. Its default dispatcher **fails closed**, so nothing is ever marked DELIVERED unless a real provider sent it. ADR-012 records the PostgreSQL engine as an interim Temporal substitute and lists what it does not provide. | `src/backend/worker.py`, `docs/adr/ADR-012-postgresql-durable-engine-and-worker.md` |

## Tests
- **New `tests/security/test_group_b_regressions.py`** (13 tests):
  - the provider and gateway never fabricate output, and the cloud slot refuses;
  - the 9B context clamp;
  - signed-link binding (wrong quote, wrong purpose, tampered, expired);
  - superiority is claimed only from the held-out backtest;
  - the worker relays and expires, is idempotent, and never marks unsent events delivered;
  - cross-tenant FK, negative stock and zero-amount refund are rejected by **real PostgreSQL**.
- **New `tests/security/test_permission_catalog_coverage.py`** (4 tests).
- **Updated tests:**

| Test | Change |
|---|---|
| `test_quote_lifecycle_and_approvals.py` | Uses the signed link; asserts that no token and a forged token are refused. |
| `test_step06_real_postgres.py` | Seeds the stock it ships (it used to ship stock that did not exist). |
| `test_ai_model_governance.py` stream test | Asserts that a real token arrives, instead of the canned "Stream" text. |

- **More updated tests:**

| Test | Change |
|---|---|
| `test_carrier_webhooks_and_logistics_security.py` | Seeds the stock it ships, like `test_step06`. |
| `test_procurement_and_logistics.py` | Seeds the stock it ships, like `test_step06`. |

- **New `tests/agents/conftest.py`:** the agent orchestration tests now run against an explicit, labelled deterministic model stub. No assertion was changed.
  - **Why:** these tests used to "pass" only because the 5 s timeout produced the fabricated placeholder text. With honest provider errors, the real model answered with prices and stock it had no evidence for, and the guard correctly rejected them, so 4 tests failed.
  - **Why a stub is the honest fix:** asserting SUCCESS on non-deterministic live model output is not a reliable unit test.
  - **Grounding tests:** `test_agent_output_is_grounded_or_rejected` proves that a model-computed price (6000 MAD) and an unverified "payée" claim are rejected, and that a price matching verified evidence passes.
  - **Hand-off test:** `test_agent_records_handoff_when_model_unavailable` proves that an outage is recorded as a hand-off.
  - **Model quality** still needs real evaluations with pinned models and held-out data (group D).
- **Full suite:** **423 passed, exit 0, 218.9 s** (`test-logs/remediation_b_full.log`). The tracked `evidence/step-10/...json` that the suite rewrites was restored afterwards.
- **Live checks:** `python -m src.backend.worker --once` as `sales_app_user` processed 75 tenants with 0 errors (`test-logs/worker_live_once_appuser.log`).

## Still open after group B
- **Workflow engine limits:** no Temporal. There are no durable timers, no automatic resume of crashed RUNNING sagas and no background-agent job queue (see ADR-012).
- **No delivery providers:** no outbound channel provider and no OTP provider are integrated.
- **No reranker:** no reranker model is installed.
- **Groups C–F remain:**
  - F-12: privileges and audit-log immutability;
  - F-13 remainder;
  - F-21 refresh rotation;
  - F-29: in-memory stores;
  - F-30: plaintext channel secrets;
  - F-17 and F-18: agents and RAG;
  - F-15: real STT/TTS;
  - F-20: frontend;
  - F-22: committed dump;
  - F-25 and F-26: dependency manifest, CI, TLS.
