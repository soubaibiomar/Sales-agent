# STEP 05 IMPLEMENTATION PROMPT — ORDERS, PAYMENTS, INVOICING AND STOCK RESERVATIONS

**Sprint:** 3 — Transact  
**Objective:** Protect money and stock from duplicate commits, forged paid state, overselling and inconsistent cancellation/refunds.  
**Entry criteria:** STEP 04 PASS with exact-term quote lifecycle.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Implement idempotent quote acceptance and sales order state machine; use unique aggregate/event keys and expected_version fencing.
2. Implement stock movement ledger, warehouse-aware available-to-promise, atomic holds/reservation expiry, backorders, release/commit semantics and hot-SKU contention safeguards.
3. Implement payment-intent lifecycle using supported provider sandbox, cryptographically verified inbound signatures, dedupe, independently reconcilable paid state and safe refund request states. Do not persist cardholder data outside provider-designated scope.
4. Implement invoice/receipt numbering, issuance hash and immutable version links; preserve audit and money/tax exactness.
5. Create customer/finance order, checkout, payment status and invoice interfaces with evidence-based status labels.

## Invariants and architectural constraints
- A screenshot, user message or LLM statement never establishes successful payment.
- Stock counts derive from durable movements; concurrent holds cannot over-reserve.
- Duplicate quote acceptance/payment webhook/retry cannot duplicate order/payment/ledger effects.

## Required executable validation
1. Concurrent hot SKU and multiple customers, reservation expiration vs payment settlement, duplicate quote acceptance and cancellation races.
2. Reordered, forged, delayed, duplicate and replayed payment callbacks; independently reconciled paid transitions and refunds.
3. Crash worker between transaction commit and downstream acknowledgment; ensure exactly-once business effects through idempotency.
4. Verify invoice correction chain/immutability, payment authorization and customer scope. Record measured counters for duplicates and oversells (expect zero in specified tests).

## Required deliverables and artifacts
- `backend/domains/orders,payments,inventory,invoicing`
- `provider sandbox adapter/mocks`
- `tests/concurrency/hot_sku*`
- `tests/security/payment_webhook*`
- `evidence/step-05/`
- `reports/step-05-report.md`

## Security control traceability
**Controls specifically relevant to this step:** 31–32, 33–34, 48, 57–59; SAI-07, SAI-08.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only when documented adversarial/concurrency suite exhibits zero duplicate business commits, zero oversells and zero unverified paid transitions.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-05-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
