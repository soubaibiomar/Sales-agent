# STEP 12 IMPLEMENTATION PROMPT — WHOLE-PRODUCT INTEGRATION, SECURITY AUDIT, LOAD, DR AND FINAL RELEASE

**Sprint:** 6 — Accept  
**Objective:** Prove the entire single Sales AI Management product can be safely released and operated with independently inspectable evidence.  
**Entry criteria:** STEPS 01–11 PASS; if not, record blockers and remediate before declaring final PASS.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Run full E2E across web/email/WhatsApp/phone from lead and verified customer identity through product, quote, approval, order, real/sandbox payment, stock, procurement, fulfilment, return/refund/support, reporting and handoff.
2. Audit every original Excel control 01–70 and proposed SAI-01–12 for Sales AI applicability, owner, test, environment, code/config path, executed evidence, status, reviewer, last validation and remediation. Preserve original values in source workbook; record Sales AI reclassification separately.
3. Perform API/DB/voice/model throughput and concurrency benchmarks with predeclared hardware, datasets and thresholds; distinguish HTTP RPS from active AI generations/tokens/s and voice concurrent calls.
4. Conduct cross-tenant negative and agent/voice red-team tests, payment forgery/replay, dependency/SBOM/supply-chain audit, chaos/provider outage, queue recovery, disaster restoration and incident response exercise.
5. Produce deployment/runbook/rollback/SLO/cost dossier; independently review release artifact hashes/signatures, documentation, secrets scan, support readiness and go/no-go gate.

## Invariants and architectural constraints
- No unverified P0 required control may silently pass; no serious exploitable critical vulnerability at release.
- No false payment/stock/quote/approval/voice identity behavior in defined adversarial tests.
- All traffic tiers and latency numbers explicitly identified as measured or future design goals.

## Required executable validation
1. Run complete CI plus integrated E2E, load/soak, failure injection, tenant/role matrix and legal/privacy checklists; attach logs.
2. Restore encrypted backup in isolated environment and measure RPO/RTO versus approved target.
3. Security control register: all 70 plus SAI extension, positive/negative evidence, justified N/A, remediation for FAIL/UNKNOWN.
4. Independent reviewer verifies security result, all role permissions, demo and release candidate provenance; rollback drill.

## Required deliverables and artifacts
- `reports/step-12-report.md`
- `reports/final-release-acceptance.md`
- `security/evidence/final-control-matrix.*`
- `evidence/step-12/{e2e,security,load,dr,voice}/`
- `docs/runbooks/*`
- `signed/hashed release manifest`

## Security control traceability
**Controls specifically relevant to this step:** All original 01–70 plus proposed SAI-01–SAI-12.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only if all applicable blocking P0 controls and all required cross-domain journeys pass with reviewable evidence; otherwise PARTIAL/FAIL/BLOCKED and no release.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-12-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
