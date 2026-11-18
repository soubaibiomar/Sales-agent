# STEP 01 IMPLEMENTATION PROMPT — ARCHITECTURE, REQUIREMENTS AND THREAT MODEL

**Sprint:** 1 — Define  
**Objective:** Freeze one unified-product scope and establish owners, trust boundaries and testable acceptance rules before coding.  
**Entry criteria:** The unified architecture PDF, original 70-security workbook, and existing repository (if any). No infrastructure credentials required.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Produce an exhaustive requirements catalog (actors, user journeys, tenancy, web/app, email/Gmail, WhatsApp, customer and manager voice, CRM, commerce, warehouse, procurement, logistics, support, scheduling, AI, analytics, SaaS administration), each linked to service owner, API and test ID.
2. Draw high-level C4 context/container/component views plus DFD/STRIDE threat models for customer/manager identity, voice media, provider webhooks, AI tools, RAG documents, payment events, stock ledger and approval state.
3. Create ADRs for modular deterministic backend, provider gateways, PostgreSQL truth + RLS, Redis ephemerality, AI three-path routing, authorization, Temporal ownership, n8n peripheral-only, S3 objects, and security/evidence structure.
4. Create `AGENTS.md`, engineering conventions, repo directory plan, initial task/backlog mapping, threat/risk register, design tokens for neutral white/deep-green UI and traceability of all 70 controls + 12 proposed SAI extensions.
5. Declare threat priority, owners, test taxonomy, launch blockers, measured vs target SLO terminology, and roles/data-retention governance.

## Invariants and architectural constraints
- One full product, no commercial version slicing.
- One authority per business aggregate; AI proposals are never authoritative state changes.
- Every P0 risk has component owner, mitigation path and executable validation strategy.

## Required executable validation
1. Verify every major business domain and both voice modes have end-to-end flow and named owner.
2. Trace IDs 01–70 exactly once; conditional status reviewed and original workbook untouched.
3. Run architecture consistency review (DFD vs ADR vs entities vs API owners) and static source lint/repo smoke tests.
4. Verify no real secrets, unsupported legal claims or invented capacity evidence.

## Required deliverables and artifacts
- `docs/architecture/{context,containers,components,trust-boundaries}.mmd`
- `docs/adr/ADR-*.md`
- `docs/requirements/requirements-traceability.md`
- `security/risk-register.md`
- `security/control-mapping.md`
- `AGENTS.md`
- `reports/step-01-report.md`

## Security control traceability
**Controls specifically relevant to this step:** Baseline 01–70; proposed SAI-01–SAI-12.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only when all major domains, two voice modes, P0 trust boundaries and authority owners have documented, testable contracts.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-01-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
