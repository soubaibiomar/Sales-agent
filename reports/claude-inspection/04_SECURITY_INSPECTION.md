# 04 — Security Inspection

## Sources
- **Authoritative reference:** `references/70-security.xlsx`, sheet "Contrôles 01-70".
  - It is unchanged: SHA-256 `08dac551…5fda4`, identical to the copy in the prompt pack.
  - All 70 controls are still "NON VERIFIE" in the workbook. The workbook was not edited.
  - Extracted copy: `evidence/claude-inspection/security/workbook_70_controls_extracted.csv`.
- **SAI-01..12:** from `security/SAI_EXTENSION.md` (proposed controls).
- **Per-control assessment:** `security_control_assessment.csv` (82 rows).

## Result summary
| Set | PASS | PARTIAL | FAIL | NOT VERIFIED | N/A |
|---|---|---|---|---|---|
| Baseline 01–70 | 14 | 18 | 28 | 9 | 1 |
| SAI-01–12 | 0 | 3 | 8 | 1 | 0 |

AGENTS.md lists five P0 launch blockers. Their status:

| # | Launch blocker | Status |
|---|---|---|
| 1 | Cross-tenant leakage | **OPEN** (F-01, F-09, F-11) |
| 2 | Hardcoded secrets | **OPEN** (F-02, F-10, F-22) |
| 3 | Money effects without domain authorization | **OPEN** (F-02, F-03) |
| 4 | Unauthenticated manager/customer voice disclosure | **OPEN** (F-05, F-06, F-13) |
| 5 | Webhooks without HMAC + replay dedup | **OPEN** for payments and telephony (F-02, F-13). Channel webhooks are OK. |

## Executed safe tests
All of these ran against throwaway or local resources only.
1. **Route audit.**
   - 199 routes: 154 authenticated, 45 not (`evidence/claude-inspection/static/route_auth_audit.json`).
   - The unauthenticated set includes the workflow, notification, integration and voice APIs, which fall back to the `X-Tenant-ID` header.
2. **Runtime PoC harness.**
   - Real FastAPI app in-process, scratch SQLite, no network (`evidence/claude-inspection/scripts/poc_security_harness.py`).
   - Output: `evidence/claude-inspection/security/runtime_security_probes.json`.

| Probe | Result |
|---|---|
| 01 Unauthenticated read of tenant B via header | VULNERABLE (HTTP 200, data returned) |
| 02 Unauthenticated notification send as tenant B | VULNERABLE (HTTP 201) |
| 03 Forged payment webhook with the repo constant | VULNERABLE (order → PAID) |
| 04 Refund with `X-MFA-Verified: true`, 3× full, same idempotency key, self-approved | VULNERABLE (300,000 refunded vs 100,000 captured) |
| 05 Voice OTP `123456` | VULNERABLE (verified=true) |
| 06 Manager step-up with `abcdef` | VULNERABLE (executed=true) |
| 07 Tenant-B manager consumes tenant-A action token | VULNERABLE |
| 08 RAG role escalation via `user_roles` | NOT VERIFIED at runtime (blocked by a `crm:read` permission). Static finding F-18 stands. |
| 09 Refresh token used as access token | Inconclusive (wrong path, 404). Static finding F-21. |
| 10 Guard without evidence | VULNERABLE (is_safe=True) |
| 11 Guard with "MAD 999" / "dirhams" | VULNERABLE |
| 12 Tool `orders.get_status` on a non-existent order | VULNERABLE (returns PAID) |

3. **PostgreSQL privilege and RLS probe** (rolled back): `evidence/claude-inspection/db/cross_tenant_fk_probe.json`, `no_context_visibility.txt`.
4. **Git-history secret pattern scan.**
   - Found a `whsec_` test constant (the payment webhook secret).
   - Found an unencrypted `PGDMP` dump tracked in Git (`evidence/step-12/dr/sales_ai_db_backup.dump`).
   - gitleaks is not installed, so this was a regex scan and is not exhaustive.

## Identity and access
- **What works:**
  - PBKDF2 password hashes.
  - Constant-time dummy hashing for unknown users.
  - Lockout after 5 failures.
  - JWT with pinned `alg` / `aud` / `iss`.
  - JTI revocation list.
  - AES-GCM-encrypted TOTP seeds.
  - X-Tenant-ID mismatch rejected when a token *is* present.
- **What fails:**
  - Optional-auth fallback (F-01).
  - Client-asserted MFA in refunds and approvals (F-03, F-04).
  - Fake step-up for voice (F-06).
  - Default HS256 secret with no production guard (F-10).
  - Refresh/access token types not distinguished (F-21).
  - No OIDC/JWKS.
  - Roles frozen in the JWT for its 30-minute life (F-34).
- **BOLA/IDOR:**
  - Authenticated routes filter by `ctx.tenant_id` in the sampled code.
  - Public quote accept (F-14) and the voice/session routes are BOLA-prone.

## Application security
| Area | Assessment |
|---|---|
| SQL injection | No f-string SQL found; parameterised. PASS (static). |
| XSS | Not verified end-to-end. |
| CSRF | Bearer tokens, no cookies → low exposure. |
| SSRF | n8n stub does no HTTP; media URL allowlist present. |
| Deserialization / command injection | None found. |
| CORS | Explicit allowlist. |
| Error disclosure | Masked 500s; some auth errors echo PyJWT text (minor). |
| Rate limiting | Login lockout only; voice limiter is in memory; no API-wide limit. |
| WebSocket | Unauthenticated (F-13). |
| Security headers | Present. The CSP is so strict it breaks the shipped UI (F-20). |

## Infrastructure
- **Ports:** compose binds to 127.0.0.1 (good). Containers use `no-new-privileges` and resource limits (good).
- **Missing:** TLS, reverse proxy, secret injection, API container, CI/SCA/SAST.
- **Dependency vulnerabilities:** NOT VERIFIED — no manifest exists, and pip-audit is not available.

## Business security
| Risk | Status |
|---|---|
| Unauthorized discount via approval MFA bypass | F-04 |
| Fraudulent payment confirmation | F-02 |
| Refund manipulation | F-03 |
| Duplicate orders | Mitigated at service level; no DB constraint (F-28) |
| Inventory manipulation | Ledger + `FOR UPDATE`, mitigated |
| Invoice tampering | No DB immutability; app role has UPDATE |
| Cross-tenant commercial access | F-01, F-11 |

## Legal and compliance
- **Technical controls that exist:**
  - Disclosure text in the voice agent.
  - Retention settings: 90 days for audio, 365 days for transcripts (config only, no lifecycle job found).
  - PII redaction in transcripts and LLM output.
- **What is missing:**
  - Recording consent is set to `True` by default on the WebSocket and SIP paths.
  - No DSAR or erasure workflow was found.
- **Verdict:** no evidence supports a claim of Moroccan Law 09-08 or GDPR *compliance*. Only the partial technical controls above exist.
