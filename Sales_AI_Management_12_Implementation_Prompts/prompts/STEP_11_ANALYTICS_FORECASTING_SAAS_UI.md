# STEP 11 IMPLEMENTATION PROMPT — GOVERNED ANALYTICS, FORECASTING, SAAS ADMINISTRATION AND COMPLETE UI

**Sprint:** 6 — Complete  
**Objective:** Finish all user workspaces, govern metrics and forecasts, and enforce SaaS subscription/metering/quotas.  
**Entry criteria:** STEP 10 PASS; complete domain events, customer/operator/manager experiences and voice metrics.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Implement governed reporting read models and data contracts for revenue, margin, pipeline, conversion, cohort/channel attribution, sales rep performance, stock, delivery, support and provider spend.
2. Document KPI definitions with source aggregates, timezone/currency/FX policy, completeness/freshness watermarks, late-event corrections and reconciliation queries. Forecast using documented baselines and backtests; label uncertainty.
3. Implement tenant plans, subscription management, usage metering, token/voice/API quotas, billing separation, limits and no noisy-neighbor policy bypass.
4. Complete and polish customer, sales, manager, operations and admin workspaces using white/neutral + deep-green design; ensure responsive navigation, accessible tables, error states, empty states and consistent approvals.
5. Add cost and operational security dashboards for token spend, voice duration, workflow queue, provider quotas, audit coverage and incidents.

## Invariants and architectural constraints
- Read-model KPIs reconcile to authoritative events and cannot imply freshness they do not have.
- Forecasts are advisory; not authoritative pricing/stock state.
- Tenants cannot access one another’s exports, dashboards, subscriptions or quota ledgers.

## Required executable validation
1. Reconcile KPI totals against independent SQL fixtures across cancellation/refund and time-zone edges.
2. Forecast backtest vs declared baseline and metrics; avoid any invented accuracy improvement.
3. Hot-tenant activity, cross-tenant exports, role-based dashboard access, quota exhaustion and billing separation.
4. E2E all workspace journeys, accessibility, responsive visual review and real UI screenshots.

## Required deliverables and artifacts
- `services/analytics-worker`
- `backend/domains/saas-admin,analytics`
- `apps/web-customer,web-sales,web-manager,web-admin and operations`
- `docs/analytics/kpi-definitions.md`
- `evidence/step-11/`
- `reports/step-11-report.md`

## Security control traceability
**Controls specifically relevant to this step:** 05–07, 33–35, 42–43, 49, 55, 57–58, 64.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only when all dashboards, permissions, SaaS quota/metering, governed KPIs and measured backtests function and reconcile.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-11-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
