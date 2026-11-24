# 02 — Requirements Traceability (12 official steps)

- **Full matrix:** `requirements_traceability.csv` (59 requirements, built from the "Exact implementation scope" sections of `prompts/STEP_01…12_*.md`).
- **Status counts:** PASS 10 · PARTIAL 27 · FAIL 21 · NOT VERIFIED 1.
- **Prompt copies:** `prompts/` and `Sales_AI_Management_12_Implementation_Prompts/prompts/` are identical (`diff -rq` shows no differences).

## Step verdicts (this inspection) vs. Gemini's claims
| Step | Official title (from prompt file) | Gemini claim | Inspection verdict | Gate-blocking evidence |
|---|---|---|---|---|
| 01 | Architecture, Requirements and Threat Model | PASS | **PASS** (documentation scope) | Deliverables present; step01 tests pass. Diagrams describe the intended system, not the built one. |
| 02 | Secure Foundation, Identity, Tenancy | PASS (after remediation) | **FAIL** | No OIDC/JWKS or IdP container. Unauthenticated `X-Tenant-ID` fallback (F-01). App cannot run under the RLS role (F-09). Default secrets (F-10). |
| 03 | Omnichannel Conversations | PASS (after 2 rounds) | **PARTIAL** | Ingestion, dedup, ownership and outbox leasing are good. Inbox UI is static; no provider sandbox. |
| 04 | CRM, Catalog, Pricing, Quotes, Approvals | PASS | **FAIL** | Money is exact, but approval MFA is bypassable (F-04) and quotes can be accepted publicly (F-14). |
| 05 | Orders, Payments, Invoices, Reservations | PASS | **FAIL** | Forged webhook → PAID (SEC-PROBE-03); refunds of 300% (SEC-PROBE-04). |
| 06 | Procurement, Warehouses, Logistics, Support | PASS | **PARTIAL** | Services and tests are solid at service level. Carriers are simulated; UIs not wired. |
| 07 | Durable Workflows, Notifications, Integrations | PASS | **FAIL** | No Temporal and no approved replacement ADR. No worker. n8n is a stub. |
| 08 | Model Gateway, RAG, Tool Security | PASS | **FAIL** | Tools return fixtures (F-07); guard fails open (F-08); provider fakes success (F-16). |
| 09 | Full Agent Ecosystem, Sales Copilot | PASS | **FAIL** | The 18 roles are registered but run on one generic agent. Evaluations are deterministic stubs, not role evaluations. |
| 10 | Customer & Manager Voice AI | PASS | **FAIL** | OTP backdoor (F-05), fake step-up (F-06), placeholder STT/TTS (F-15). |
| 11 | Analytics, Forecasting, SaaS, UI | PASS | **PARTIAL** | Read models are real. Backtest is in-sample; quotas not enforced at the gateway; UI not wired. |
| 12 | Final Integration, Security, Load, DR | "APPROVED FOR PRODUCTION" | **FAIL** | P0 launch blockers 1, 3, 4 and 5 are open; the control matrix is overstated. |

## Voice sequencing error (Step 07 vs Step 10)
- **What Git shows:**
  - `88a5c83` (*"feat(step-07): dual-mode voice ai…"*) implemented Voice AI under Step 07.
  - `262bd03` then implemented the real Step 07 scope (workflows, notifications, n8n).
  - Voice was relabelled "STEP 10 EARLY" (`STEP_10_EARLY_REPORT.md`) and extended in `c6c7d70`.
- **Step 07 contract:**
  - Outbox/inbox/DLQ: covered (with leasing).
  - Notification orchestrator: covered, including `ZoneInfo("Africa/Casablanca")`.
  - **Not covered:** durable workflow runtime (Temporal or an ADR-approved equivalent with workers), n8n integration, worker-kill recovery tests against a real worker.
  - → PARTIAL scope, **FAIL** on its gate.
- **Step 10 contract:**
  - Telephony signature helpers, G.711, VAD, barge-in and the session model exist.
  - STT/TTS, consented audio evaluation, WebRTC/SIP, verified customer identity and manager step-up are missing or defeated.
  - → **FAIL**.
- **Net:** the final project covers neither contract fully. The early voice work was kept, but the defects introduced then (OTP fallback, length-only TOTP) survived into Step 10.

## Documentation vs. code discrepancies
| Document claim | Code reality |
|---|---|
| "cryptographically signed `action_preview_token`" (STEP_10_REPORT) | `uuid4()` in an in-memory dict (`voice/security.py:187`). |
| "Measured End-to-End Voice Turn Latency 518.31 ms" | Sum of a hardcoded ASR value (110 ms), a fallback TTFT (380 ms) and sine-wave TTS timing (`scripts/benchmark_voice_pipeline.py:435`). |
| "82/82 Verified (0 Unresolved P0s)" | 10 P0 findings; 28 baseline controls FAIL in this inspection. |
| ADR-007 "Temporal as Master Workflow Orchestrator" | No `temporalio` dependency or worker anywhere. |
| AGENTS.md: Next.js/React console | Static HTML. |
| `.env.example` connects as `postgres` with the asyncpg driver | asyncpg is not installed. A superuser bypasses RLS. |
