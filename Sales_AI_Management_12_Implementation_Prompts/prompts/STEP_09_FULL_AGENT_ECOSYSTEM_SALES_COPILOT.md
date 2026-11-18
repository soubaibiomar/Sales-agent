# STEP 09 IMPLEMENTATION PROMPT — COMPLETE 18-ROLE AGENT ECOSYSTEM AND SALES REPRESENTATIVE COPILOT

**Sprint:** 5 — Agents  
**Objective:** Implement every catalog role with bounded responsibilities, reproducible evaluations and no autonomous commercial authority.  
**Entry criteria:** STEP 08 PASS; stable policy-aware Tool Gateway, RAG, supervisor and model routing.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Register all catalog roles: Router/classifier, Conversation Supervisor, nine interactive specialists (Qualification/CRM; Product/Knowledge; Quote/Pricing; Order/Payment; Scheduling; Negotiation/Objections; Support/Returns; Account Management; Documents), six background roles (Outreach; Research; Pipeline Coach; Analyst; Knowledge Curator; Incident Responder), and Sales Rep Copilot.
2. For each role define purpose, owner, allowed tools, input/output schema, tenancy, evidence, prompt/model version, context/token/delegation/time budget, default failure/handoff, evaluation dataset and rollback behavior.
3. Implement specialist dispatch through one turn owner and deterministic job triggers for all background agents. Agent-to-agent effects cannot bypass tools, approvals or workflow engine.
4. Implement sales rep copilot workspace, manager agent-operations panel, guarded response synthesis and human-reviewed knowledge/prompts.
5. Implement offline Quality Reviewer with pinned traces and no production write credentials; maintain test cases for role boundaries and error handling.

## Invariants and architectural constraints
- The 18 entries form a capability catalog; router is a classifier, not an independent authority.
- Every active role is policy-limited, observable, fail-closed and cost-bounded.
- Outreach and operational agents propose actions; Notification Orchestrator and domain services make consequential sends/writes.

## Required executable validation
1. Agent-by-agent capability/authorization regression, B2B negotiation pressure, quote modifications, account merge attempts and support escalation.
2. Multi-agent delegation exhaustion, stale conversation versions, tool errors, cross-tenant access and human takeover.
3. Background run scheduling, unapproved outreach with STOP, knowledge self-publication prevention and incident responder runbook ceilings.
4. Measure token/cost/latency by agent and run offline evaluation with pinned outputs; supply complete role matrix.

## Required deliverables and artifacts
- `ai/agent-registry and all role implementations`
- `apps/web-sales rep copilot`
- `apps/web-manager agent operations panel`
- `tests/agents and offline evaluation corpus`
- `evidence/step-09/`
- `reports/step-09-report.md`

## Security control traceability
**Controls specifically relevant to this step:** 39–40, 42, 49, 63, 65–67; SAI-06–SAI-08, SAI-10, SAI-12.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only if catalog coverage and individual role evaluations are evidenced and no delegation bypasses authorization or approvals.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-09-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
