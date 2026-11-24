# 11 — Prioritised Remediation Plan

Nothing here has been implemented. Effort estimates assume one experienced engineer. Finding details are in `findings_register.csv`.

## A. Immediate critical corrections (P0) — about 2–3 weeks
Work these in this order, because each one unblocks the next:
1. **F-10 Secrets.** Remove all defaults; fail startup in non-dev environments; move secrets to Docker secrets or Vault. Rotate anything that ever lived in Git. *(Prerequisite for F-02 and F-13.)*
2. **F-01 Header fallback.** Make every non-webhook route require `get_security_context`, and delete the `x_tenant_id` fallbacks. Add a CI route-audit test (use `evidence/claude-inspection/scripts/route_audit.py` as the starting point).
3. **F-09 RLS-compatible runtime.**
   - Add `SECURITY DEFINER` lookup functions for login and webhook routing.
   - Run the API as `sales_app_user`; refuse superuser or BYPASSRLS connections at startup.
   - Remove the SQLite default.
   - Re-run the full suite under this role.
4. **F-04, F-03, F-06 MFA bypasses.** Build one `verify_step_up(ctx, code)` helper on top of `SecurityService.verify_totp`. Then:
   - Delete the header, query and length-only checks.
   - Bind action previews to tenant + user, stored in PostgreSQL.
   - Make "execute" call the domain service.
5. **F-03 Refund integrity.** Cumulative cap under `FOR UPDATE`, a unique idempotency key, four-eyes approval, and a provider refund call before COMPLETED.
6. **F-02 Payment webhooks.** Per-tenant secret, provider-native signature with timestamp, amount/currency match, reconciliation before PAID.
7. **F-05 OTP.** Remove `123456`; deliver OTPs through an adapter; store a hash with TTL in Redis or PostgreSQL. Fix the tests that rely on the backdoor.
8. **F-07 + F-08 AI grounding.** Register real tool handlers at startup; make the built-in fixtures raise. Make the guard fail closed when commercial claims appear without evidence, and extend the claim patterns.

**Verification after group A:** re-run `poc_security_harness.py`. Every probe must report DEFENDED. Add each probe as a permanent pytest negative test.

## B. Short-term functional corrections — about 3–5 weeks
1. F-19: a worker service (outbox relay, reservation expiry, saga timers, background-agent jobs). Either adopt Temporal or write an ADR approving the PostgreSQL engine.
2. F-14: signed quote-acceptance links.
3. F-28: DB constraints (unique `quote_id`, CHECKs, refund idempotency, booking exclusion) and composite tenant FKs (F-11).
4. F-16: honest model failure path, async HTTP, warm-up, `think: false`, timeouts sized from the measured cold start.
5. F-34: a coherent permission catalog with a route→role coverage test.
6. F-31: a separate *paid* revenue metric; a rolling-origin backtest.

## C. Security hardening — about 2 weeks, partly parallel with B
1. F-12: revoke DML on `tenants`, `roles`, `permissions` and `audit_logs`; make the audit log append-only with a hash chain.
2. F-13: mandatory telephony signatures; WebSocket session tokens; recording off by default with an explicit consent event; a retention purge job.
3. F-21: enforce the `type` claim; refresh rotation with reuse detection. Then move to OIDC/JWKS (RS256), as Step 02 requires.
4. F-29: Redis-backed rate limits, OTPs and nonces, namespaced by tenant.
5. F-30: encrypt channel secrets or store references only.
6. F-22: remove the committed dump (a history rewrite needs the owner's explicit approval); encrypted DR drills only.
7. Supply chain: lock file with hashes, SBOM, pip-audit, gitleaks and bandit in CI.

## D. AI and voice improvements — about 4–8 weeks
1. F-17: replace keyword triggers with typed function-calling. Pass the *end-user* roles into retrieval. Build per-role held-out evaluation sets scored on real model outputs.
2. F-18: ignore client-supplied roles; store the embedding model ID per chunk; pgvector with an HNSW index and a tenant filter.
3. F-15: real STT (e.g. faster-whisper small/int8 on CPU) and TTS (Piper/Kokoro on CPU) behind the existing interfaces. Browser capture (`getUserMedia` + AudioWorklet) and playback. Measure audio-in to audio-out p50/p95 with recorded fixtures.
4. Consented multilingual audio corpus (fr, en, ar, ary-Arab, ary-Latn, code-switching). Report WER per language with sample counts.
5. F-27: decide VRAM residency from live `/api/ps` inside the file lock; set `OLLAMA_MAX_LOADED_MODELS=1`.

## E. Frontend improvements — about 4–6 weeks
1. Decide the stack: the planned Next.js shell, or keep HTML but move all inline CSS/JS to files and use a nonce-based CSP.
2. One shared layout and navigation (fixes the 6 variants), an OIDC login, and an API client that carries the token. Remove `X-Tenant-ID` and `mock-manager-token`.
3. Wire the dashboard, inbox, quote builder, approvals, orders and inventory to real endpoints, with loading, empty and error states.
4. Responsive fixes at 390 px; right panels clipped at 1440 px; deduplicate the voice script (F-32).
5. Playwright E2E for journeys A–H on the *served* app, with visual regression and axe accessibility checks.

## F. Production infrastructure — about 3–4 weeks
1. API and worker Dockerfiles, reverse proxy with TLS, real readiness probes, migrations as a release step.
2. CI/CD with test, SAST, SCA and secret-scan gates; signed images.
3. OpenTelemetry → Prometheus/Grafana, alerting, centralised log redaction.
4. Encrypted off-site backups; measured RPO/RTO on a representative dataset; rollback via versioned images.
5. A legal review for Law 09-08 / GDPR (consent, retention, DSAR, processor agreements), done independently of the engineering work.

## Dependency order (summary)
A1 → A2/A3 → A4–A7 → A8 → B1 → (C and D in parallel) → E → F hardening → independent re-audit.
