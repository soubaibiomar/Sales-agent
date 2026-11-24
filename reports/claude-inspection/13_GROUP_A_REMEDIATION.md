# 13 — Group A (P0) Remediation Record

- **Branch:** `fix/group-a-p0-remediation`, created from `master` at `1a74c49`. Nothing is committed yet.
- **Scope:** remediation group A of report 11. The findings are in `findings_register.csv`.

## What changed, per finding
| Finding | Fix | Main files |
|---|---|---|
| **F-10** default secrets | Startup now fails outside development when any secret still equals its committed default, or when the DB is SQLite. New settings `payment_webhook_secret`, `voice_session_secret` and `n8n_webhook_secret` replace the constants that were hardcoded. `.env.example` now uses the RLS role and lists the new secrets as placeholders. | `src/backend/core/config.py`, `.env.example` |
| **F-01** `X-Tenant-ID` fallback | All 14 workflow, notification and integration routes now require authentication **and** a permission: `workflows:read/manage`, `notifications:manage`, `integrations:manage`. The `tenant_admin` default role gets these permissions. The n8n endpoints require auth, and their signing secret comes from config, never from the caller. Voice: see F-13. | `src/backend/api/{workflows,notifications,integrations}.py`, `core/policy_service.py` |
| **F-09** RLS unusable at runtime | New migration `011_rls_compatible_preauth_lookups.sql` adds `auth_resolve_login_tenants(email, tenant_id)`. It is SECURITY DEFINER with a pinned `search_path`, executable only by `sales_app_user`, and returns tenant ids only. Login and MFA verify bind the verified tenant and re-bind it after every commit, since the GUC is transaction-local. Startup refuses superuser/BYPASSRLS connections outside development. A latent pool bug was also fixed: the checkin `RESET` left psycopg connections INTRANS, which broke the second request under the app role. | `migrations/011_*.sql` (also appended to `infra/init-db.sql` and applied to the local dev DB), `core/database.py`, `api/auth.py`, `main.py` |
| **F-04** approval MFA | A code now counts only if it verifies against the approver's enrolled TOTP seed. Shared helper: `core/step_up.py`. | `api/approvals.py`, `core/step_up.py` |
| **F-03** refunds | `X-MFA-Verified` and `?mfa_verified` are removed; MFA is proven server-side. Changes: <ul><li>the order is locked with `FOR UPDATE`;</li><li>cumulative cap: open + completed refunds ≤ order total;</li><li>idempotency key replay returns the original request, and reusing a key for different terms is rejected;</li><li>four-eyes rule: the requester cannot approve;</li><li>the cap is re-checked at approval;</li><li>a partial refund sets `PARTIALLY_REFUNDED` instead of refunding the whole order.</li></ul> | `api/payments.py`, `domains/payments/service.py` |
| **F-02** payment webhook | The secret is per tenant (`tenant_channel_integrations`, channel `PAYMENT_<PROVIDER>`); the shared value is a development-only fallback. The signed message is `"<timestamp>.<body>"` with a mandatory, fresh timestamp (`X-Signature-Timestamp`, or Stripe-style `t=…,v1=…`). Amount and currency must match the payment intent. The tenant is bound only after verification with that tenant's own secret. | `api/payments.py`, `domains/payments/service.py` |
| **F-05** OTP backdoor | The `123456` fallback is removed. New `request-otp` endpoint and WebSocket `REQUEST_OTP` frame deliver a single-use code through a pluggable `OtpDeliveryAdapter`. The default adapter **fails closed** (HTTP 503) because no SMS/WhatsApp provider exists yet. The code is never returned to the caller. | `voice/service.py`, `voice/otp_delivery.py`, `api/voice.py` |
| **F-06** manager step-up | A fresh TOTP is always verified against the manager's seed; session-level MFA is not enough for the voice channel. Action tokens are bound to tenant + user. The response no longer claims execution: it returns `executed: false`, `AUTHORIZED_PENDING_EXECUTION`. | `voice/security.py`, `api/voice.py` |
| **F-13** (part, needed for F-01) voice/telephony | Session creation requires an authenticated caller and returns a signed, expiring **voice session token** binding tenant + session. Per-session endpoints accept either a bearer JWT or that token, never a header tenant. WebSocket needs `?token=`, and no longer auto-creates sessions or defaults recording consent to true. Telephony inbound/status require a signature with the called number's own integration secret; the tenant comes from that binding; recording is off by default. Callbacks require auth. | `api/voice.py`, `voice/session_tokens.py`, `schemas/voice.py` |
| **F-21** refresh-as-access | Tokens with `type=refresh` are rejected by the auth middleware and by MFA verify. | `core/auth_middleware.py`, `api/auth.py` |
| **F-07** fabricated tool data | `catalog.search`, `inventory.check_atp`, `pricing.calculate_quote` and `orders.get_status` are answered from tenant-scoped domain data (catalog, inventory ledger, PricingService, orders/shipments). They raise instead of falling back. Other tools are still placeholders and are labelled `simulated: true`; BaseAgent never turns them into evidence. Every `ToolGateway` instance registers the real handlers. | `src/ai/domain_tool_handlers.py`, `src/ai/tool_gateway.py`, `src/ai/agents/base.py` |
| **F-08** guard fail-open | Verification always runs; no evidence means "nothing verified". Price parsing handles currency before or after the amount, "dirham(s)", euros, and `1 250,00` / `1.250,00` / `1,250.00`. Unparseable amounts are violations. Stock claims without ATP evidence are violations. BaseAgent always builds an envelope from real tool results, in major units. | `src/ai/output_guard.py`, `src/ai/agents/base.py` |

## Tests
- **New:** `tests/security/test_group_a_p0_regressions.py`, 25 tests. Each reproduces an original exploit and asserts it is rejected, plus the legitimate path. It includes a real-PostgreSQL test for the SECURITY DEFINER login lookup and the superuser startup guard.
- **Updated** (these asserted the insecure behaviour; each now asserts the secure flow plus the old exploit failing):

| Test | Change |
|---|---|
| `tests/voice/test_voice_api_contract.py` | Static OTP refused; delivered OTP accepted; wrong TOTP 403; real TOTP authorizes but does not execute. |
| `tests/voice/test_telephony_adapter_and_security.py` | Unsigned call 401; signed call accepted; callbacks need auth. |
| `tests/voice/test_voice_websocket_streaming.py` | Socket without token refused; static OTP refused. |
| `tests/voice/test_manager_copilot_and_mfa.py` | Foreign user cannot consume a token. |
| `tests/e2e/test_step12_full_lifecycle_e2e.py` (scenario D) | Foreign user cannot consume a token. |
| `tests/workflows/test_workflow_api_contract.py` | Header-only request 401; authenticated operator works. |
| `tests/ai/test_tool_gateway.py` | Prices and searches a seeded product through PricingService; fails closed without data or for an unknown SKU. |

No assertion was relaxed to make a test pass. The WebSocket test teardown no longer runs `drop_all` across event loops; it only disposes its in-memory engine.

## Evidence
- `evidence/claude-inspection/security/runtime_security_probes_post_fix.json`: the original 12 exploit probes, re-run → **all DEFENDED**. Probe 04 was stopped earlier in its chain, because the forged webhook no longer marks the order paid; the refund controls themselves are covered by `test_f03_*`.
- `evidence/claude-inspection/security/live_login_under_rls_post_fix.json`: the real server connected as `sales_app_user`.

| Request | Result |
|---|---|
| Wrong password | 401 |
| Correct login | 200, token issued |
| Authenticated call | 200, correct tenant |
| `X-Tenant-ID`-only call | 401 |

- Full suite after the fixes: **406 passed, exit 0, 285.8 s** (`test-logs/remediation_a_full_final.log`). That is 381 pre-existing tests plus 25 new ones. It ran with PostgreSQL and Ollama up.
- The pool-checkin fix landed after that run started. A re-run of `tests/integration`, `tests/security`, `tests/e2e`, `tests/voice` and `tests/workflows` on the final code gave **175 passed, exit 0** (`test-logs/remediation_a_postfix_subset.log`).
- The suite still rewrites the tracked `evidence/step-10/multilingual_voice_evaluation.json`; it was restored with `git checkout` after the runs.

## Still open after group A
These are not done and are deliberately left for later groups:
- **No real external providers.** There is no payment provider refund call; the provider refund ID is still simulated. There is no provider reconciliation before PAID. There is no OTP delivery provider, so caller verification returns 503 until one is registered.
- **Voice actions are authorized but not executed.** There is no domain executor for voice-authorized actions.
- **Group B, C and later items** remain:
  - F-11 composite tenant FKs;
  - F-12 role privileges and audit immutability;
  - F-14 public quote accept, which is also non-functional under RLS;
  - F-16 fake model fallback;
  - F-17 keyword agents;
  - F-18 RAG ACL roles from the request body;
  - F-19 worker/Temporal;
  - F-20 frontend: it still sends `X-Tenant-ID` / `mock-manager-token`, so its API calls now correctly get 401 until a login UI exists;
  - F-28 DB constraints;
  - F-29 in-memory OTP/action stores, which are single-process;
  - TOTP codes can be reused within their 30-second window;
  - group F infrastructure.
- **Dev fallback:** in development, a tenant without its own payment integration still accepts the shared dev secret. Startup rejects that value in any other environment.
