# STEP 06 IMPLEMENTATION PROMPT — SUPPLIERS, MULTI-WAREHOUSE PROCUREMENT, LOGISTICS, SUPPORT AND SCHEDULING

**Sprint:** 3 — Operate  
**Objective:** Implement the entire operational lifecycle after sale, including purchasing, shipment, returns and customer care.  
**Entry criteria:** STEP 05 PASS with order, payment and reservation invariants.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Implement multiple warehouses, inter-warehouse transfers, SKU/lot tracking where needed, supplier registry/catalog, RFQ, purchase order approval and partial goods receipt.
2. Implement pick/pack/ship, carrier adapters, tracking event normalization, delivery proof, ETA provenance and monotonic shipment state transitions.
3. Build support tickets, warranties, return authorization, inspection outcomes (restock/quarantine/reject), refund handoff, booking/calendar availability, cancellation and conflict protection.
4. Implement controlled document corrections/credit artifacts via linked versions and audit references.
5. Complete warehouse, operations and support workspaces, with tenant/site/user permissions and usable responsive forms.

## Invariants and architectural constraints
- Warehouse balance remains ledger-backed, even on transfer and return.
- Carrier status and ETA claims are current/verifiable and cannot regress from late callbacks.
- Refund/stock mutations require valid inspected return and policy transitions.

## Required executable validation
1. Partial supplier receipts, reordered/duplicated shipment events, transfer contention and over-receipt rejection.
2. Return of damaged goods, warranty exception, booking races, duplicate appointment confirmation and unauthorized multi-site access.
3. Carrier/calendar outage and retry with no invented delivery/booking completion.
4. Manual UI E2E plus automated checks for warehouse, support and manager pages; save screenshots and test evidence.

## Required deliverables and artifacts
- `backend/domains/procurement,fulfilment,support,bookings`
- `integrations/carriers,calendars`
- `apps/web-operations and support screens`
- `tests/contract/provider*`
- `evidence/step-06/`
- `reports/step-06-report.md`

## Security control traceability
**Controls specifically relevant to this step:** 05–07, 16, 21–23, 33–34, 48, 57–59.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only when inventory/shipment/return state changes are legitimate, traceable, non-regressing and permission-scoped.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-06-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
