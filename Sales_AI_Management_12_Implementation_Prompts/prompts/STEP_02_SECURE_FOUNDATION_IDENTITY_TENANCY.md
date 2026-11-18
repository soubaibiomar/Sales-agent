# STEP 02 IMPLEMENTATION PROMPT — SECURE FOUNDATION, IDENTITY AND MULTI-TENANCY

**Sprint:** 1 — Secure  
**Objective:** Create working secure local infrastructure, tenant membership, authorization and recovery substrate used by every later domain.  
**Entry criteria:** STEP 01 PASS; approved ADRs, security mapping and repo structure.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Initialize Docker Compose with health and readiness probes for backend API, PostgreSQL, Redis, S3-compatible object storage, identity, OpenTelemetry/metrics; keep all app/service containers on least-privilege networks.
2. Implement database migrations for tenants, organizations/sites, users/memberships, roles, permissions, audit events and feature flags. Enforce RLS with least-privileged application DB role and transaction-bound trusted tenant context.
3. Wire OIDC token verification/JWKS, MFA for managers/admins, secure sessions, refresh/revocation, disabled accounts, role-scoped policy service and no trust in client/LLM tenant or role arguments.
4. Build minimal authenticated web shells (sales, manager, customer/admin) with protected routes, secure cookies/CSRF/CORS policy, logged-in tenant switching and accessible UI.
5. Add secrets management and scan gates, SAST/SCA baseline, pinned CI images/actions, encrypted backups, restore scripts, audit correlation IDs, role and tenant test fixtures.

## Invariants and architectural constraints
- Every DB and API access is tenant-scoped; object storage and logs have equivalent policies.
- Privileged users require MFA; denied authorization is fail closed.
- No default secrets, no public DB/admin interfaces.

## Required executable validation
1. Integration tests: wrong tenant on row, object and attachment; role mutation in JWT, expired or wrong-audience token, revoked session, disabled user, unknown organization.
2. Service roles and RLS negative tests, direct SQL denial under low-privilege account, tenant-switch racing.
3. Restore isolated backup and confirm data integrity + encryption / secret omission in logs.
4. Run CI secret scan, dependency scan, secure headers/cookie/CORS checks, API smoke tests and screenshot verification of role-specific layouts.

## Required deliverables and artifacts
- `infra/docker-compose.yml or repository equivalent`
- `backend/migrations/ and tenancy/security services`
- `tests/security/test_tenant_isolation*`
- `tests/security/test_auth*`
- `docs/security/identity-tenancy.md`
- `evidence/step-02/`
- `reports/step-02-report.md`

## Security control traceability
**Controls specifically relevant to this step:** 01–15, 24–26, 41, 44, 48–49, 54–56, 60–63.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only if authentication, privileged MFA, server-side policies, RLS and backup restoration are executable and proven; no cross-tenant escape.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-02-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
