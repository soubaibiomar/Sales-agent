# STEP 03 IMPLEMENTATION PROMPT — OMNICHANNEL INGESTION, CONVERSATION OWNERSHIP AND INBOX

**Sprint:** 2 — Connect  
**Objective:** Normalize web chat, WhatsApp and Gmail/email into one durable tenant-isolated conversation timeline and human handoff workflow.  
**Entry criteria:** STEP 02 PASS with identity/RLS and authenticated client shell.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Create authenticated web-chat adapter and provider interface contracts for WhatsApp Business and Gmail/email, including webhook signatures/OAuth scopes, provider event IDs, attachments and retry semantics; use real sandbox integrations only where credentials exist.
2. Persist raw metadata-minimized inbound envelopes before batching or routing, deduplicate with unique keys, normalize channel/identity, record consent, STOP language variants and ownership state. Do not auto-merge unverified contacts.
3. Implement conversation state machine with monotonic version, inbound burst handling, operator assignment, unread counters, atomic handoff, callback/task fallback and AI silence while a human owns conversation.
4. Build Sales Workspace unified inbox: filters, assignments, customer context, messages, attachment previews, status, handoff controls, accessibility and responsive layout.
5. Create test fixtures for provider payloads, invalid signatures, delayed callbacks, out-of-order message batches and channel-provider outages.

## Invariants and architectural constraints
- Durable ingest BEFORE debounce/routing; replay and duplicates have no extra side effects.
- Consent/STOP and ownership decisions are deterministic and outrank LLM suggestions.
- Attachment media is authenticated/scanned; external URLs cannot trigger unrestricted SSRF.

## Required executable validation
1. Replay identical and reordered WhatsApp/email/web events; assert exact persisted count and stable ordering policy.
2. Race new message vs human handoff, assert older AI turn cannot send; verify stale version cancellation.
3. Negative tests: cross-tenant inbox/attachments, XSS, MIME mismatch, malicious URL/SSRF, forged provider signature, repeated STOP, high-volume bursts.
4. Run UI end-to-end journeys for sales/support and capture genuine screenshots; verify basic keyboard/accessibility checks.

## Required deliverables and artifacts
- `integrations/whatsapp, gmail, web-chat adapters`
- `backend/domains/conversations`
- `apps/web-sales unified inbox`
- `tests/contract/channels*`
- `tests/concurrency/conversation*`
- `evidence/step-03/`
- `reports/step-03-report.md`

## Security control traceability
**Controls specifically relevant to this step:** 16–23, 27–28, 33–35, 42, 57–59; SAI-11.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only if every configured channel ingests safely, persists before routing, deduplicates correctly, and human ownership/consent is unbypassable.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-03-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
