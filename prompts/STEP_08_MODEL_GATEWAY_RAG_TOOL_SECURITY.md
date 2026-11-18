# STEP 08 IMPLEMENTATION PROMPT — MODEL GATEWAY, RAG, ROUTER, PROTECTED TOOLS AND OUTPUT VERIFICATION

**Sprint:** 4 — Intelligence  
**Objective:** Introduce replaceable AI reasoning with strong evidence, tenant isolation and enforceable agent tool authority.  
**Entry criteria:** STEPS 02, 04, 07 PASS for authentication, deterministic commerce core and durable tasks.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Implement Model Gateway for configurable local/cloud models, provider health, latency/cost budgets, fallback, concurrency limits, token accounting, PII processing and version tracing.
2. Implement approved document ingestion, provenance, permission-filtered chunking/indexing and retrieval with tenant/document ACLs, poisoning controls and removal/reindex support.
3. Implement language/intent/risk Router, confidence gates, direct/read vs reasoning vs workflow classification, single conversation supervisor, stale-turn fencing and budgets.
4. Implement strict typed Tool Gateway with allowlists, policy re-evaluation, server-issued actor context, idempotency, deadline, error codes and validated schema.
5. Implement claim-level verifier for prices/currencies/stock/payment/version/freshness and output semantic/policy guard; create replayable test corpus and offline model evaluation.

## Invariants and architectural constraints
- Agents see only scoped evidence; cannot invoke arbitrary SQL, URLs or providers.
- Tool authorization cannot be widened by prompts, retriever text or supervisor delegation.
- Customer-facing claims involving money/stock/payment/status must be backed by current domain postconditions.

## Required executable validation
1. Direct and indirect prompt injection from incoming messages, OCR/documents, RAG and tool responses; cross-tenant memory and retrieval.
2. Unauthorized tool/action/tenant overrides; stale-turn writes; malformed JSON, schema extra fields and timeouts.
3. Pinned model/provider results replay without live mutations; cost/latency/budget observability and fallback simulation.
4. Curated Darija Arabic/Latin, Arabic, French, English and code-switching cases; distinguish observed quality from targets.

## Required deliverables and artifacts
- `services/model-gateway,agent-runtime,tool-gateway`
- `ai/rag,guards,evaluations`
- `typed tool schemas + agent evidence envelopes`
- `tests/adversarial-ai/*`
- `evidence/step-08/`
- `reports/step-08-report.md`

## Security control traceability
**Controls specifically relevant to this step:** 39–40, 49, 63, 65–67; SAI-06–SAI-10, SAI-12.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only if unauthorized tools and tenant retrieval fail closed and financial/customer state claims are grounded; no invented evaluation scores.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-08-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
