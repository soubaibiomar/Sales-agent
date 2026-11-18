# STEP 04 IMPLEMENTATION PROMPT — CRM, CATALOG, PRICING, QUOTATIONS AND APPROVALS

**Sprint:** 2 — Sell  
**Objective:** Complete authoritative lead-to-quotation business flow with deterministic pricing and exact-term approvals.  
**Entry criteria:** STEP 03 PASS; verified contact identity and inbox. Original full scope must remain in the requirement map.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Create CRM modules for leads, contacts, accounts, opportunities, activities, owners and pipelines with role-scoped API/UI and import validation.
2. Implement product/service catalog, SKU variants, units of measure, pricing lists, tenant/region/currency/tax context, deterministic discount policy, margin floors and precise money representation (minor units/decimal; no float money).
3. Implement quote state machine (draft/priced/pending approval/approved/issued/sent/accepted/rejected/expired/cancelled), expiry, price-list snapshot, optimistic version checks and exact-term revalidation.
4. Create canonical approval queue with MFA-capable approver authentication, one-use decisions, exact terms hash, reason, authorization and immutable audit. Generate hash-addressed issued pro-forma/quote documents.
5. Build pipeline board, catalog, quote builder, manager approval screens and customer-facing quotation status/acceptance flows.

## Invariants and architectural constraints
- Only Pricing service computes final values, taxes, margins and discounts; no AI/free-text authority.
- Issued quote and pro-forma are versioned; older approvals are invalid when terms change.
- Quotes are tenant-scoped; approval rights cannot be self-granted.

## Required executable validation
1. Table-driven money/tax/rounding/multi-currency test fixtures, invalid quantities/UOM/negative quantities, stale price-list and stock.
2. Simulate two concurrent approvers, duplicate approval callback, expired approval and changed quote terms.
3. Verify unauthorized approval, cross-tenant quote read and quote tampering are denied server-side.
4. E2E create lead→opportunity→quote→manager approval→issue PDF/pro-forma with hash and screenshots.

## Required deliverables and artifacts
- `backend/domains/crm,catalog,pricing,quotations,approvals,documents`
- `apps/web-sales pricing/quotes/pipeline views`
- `apps/web-manager approval center`
- `tests/unit/money*`
- `tests/concurrency/approval*`
- `evidence/step-04/`
- `reports/step-04-report.md`

## Security control traceability
**Controls specifically relevant to this step:** 05–07, 15, 33–34, 51, 57–58, 63; SAI-08.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only if monetary calculations and approval/issuance authority are deterministic, version-safe and independent of prompts.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-04-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
