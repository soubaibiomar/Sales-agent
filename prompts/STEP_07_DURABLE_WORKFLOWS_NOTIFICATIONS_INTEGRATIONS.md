# STEP 07 IMPLEMENTATION PROMPT — OUTBOX/INBOX, DURABLE WORKFLOWS, NOTIFICATIONS AND INTEGRATIONS

**Sprint:** 4 — Orchestrate  
**Objective:** Ensure every long-running business process survives crashes, retries, rate limits and provider outages with correct effects.  
**Entry criteria:** STEPS 02–06 PASS for their required invariants; existing order/payment/approval lifecycle available.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Implement transactional outbox + inbox with versioned schemas and durable event publishing, deduplicating consumers, ordering rules and dead-letter quarantine.
2. Create Temporal (or ADR-approved equivalent) workflows for approvals, payment expiry/reconciliation, stock-hold expiration, procurement, fulfilment, returns, reporting jobs and provider retries.
3. Build Notification Orchestrator with consent, STOP, ownership, channel suitability, message templates, quiet hours/time zones, frequency caps, send-time recheck and delivery receipts.
4. Integrate n8n as a restricted peripheral consumer of immutable events via scoped service identity; it cannot call privileged commit operations outside normal policies.
5. Implement queue dashboards, health alerts, limits, retries/backoff, workflow resumes and safe operator recovery.

## Invariants and architectural constraints
- PostgreSQL commerce state is committed independently of message transmission; outbox matches transaction.
- Retry or lease loss cannot duplicate money, stock, approvals or customer sends.
- Notifications never bypass opt-out, consent, human ownership or frequency budgets at delivery time.

## Required executable validation
1. Kill workers just after commit / just before send / during ack and replay all events; assert business truth consistent.
2. Provider 429/outage, network partitions, DLQ recovery, unknown schema version, duplicate/late events and retry storms.
3. Quiet hours across Moroccan time/date boundaries; multi-script STOP; human takeover during pending message.
4. Verify n8n service accounts cannot directly change paid state, prices, inventory or approvals.

## Required deliverables and artifacts
- `backend/outbox,inbox and workflow runtime`
- `services/notification-service`
- `integrations/n8n restricted flows`
- `tests/failure_injection/workers*`
- `evidence/step-07/`
- `reports/step-07-report.md`

## Security control traceability
**Controls specifically relevant to this step:** 28, 31, 42–44, 57–59, 63–64; SAI-11.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only if durable state recovers without duplicate effects and notification rules remain enforced through failure/retry.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-07-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
