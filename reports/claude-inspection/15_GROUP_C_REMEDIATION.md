# 15 — Group C (security hardening) Remediation Record

- **Branch:** `fix/group-a-p0-remediation`, continuing after commit `c999e87`.
- **Scope:** remediation group C of report 11.

## What changed, per finding
| Finding | Fix | Main files |
|---|---|---|
| **F-12** excess DB privileges, mutable audit | Migration `014` revokes UPDATE/DELETE on `tenants` (INSERT stays, for tenant provisioning), INSERT/UPDATE/DELETE on `roles`, `permissions` and `role_permissions`, and UPDATE/DELETE on `audit_logs` from `sales_app_user`. This also closes a worse gap found while testing: a `DELETE FROM tenants` by the app role cascaded through every child table, and foreign-key cascades bypass RLS, so **the app role could erase another tenant entirely**. Audit log changes: <ul><li>a per-tenant SHA-256 hash chain (`chain_seq`, `prev_hash`, `entry_hash`) filled by a trigger, with an advisory lock per tenant so concurrent inserts cannot fork the chain;</li><li>the 34 existing rows were back-filled into the chain;</li><li>a trigger blocks every UPDATE, and blocks DELETE for anyone but a superuser (tenant erasure);</li><li>`audit_verify_chain()` recomputes the caller's own tenant chain.</li></ul> | `migrations/014_least_privilege_and_audit_chain.sql`, `models/entities.py` |
| **F-21** refresh tokens | New `POST /api/v1/auth/refresh` endpoint: <ul><li>refresh tokens are single-use and rotated;</li><li>every login creates a session family (`fam` claim on access and refresh tokens);</li><li>reusing an already-rotated refresh token revokes the whole family, including access tokens already issued, and writes an audit event;</li><li>roles and permissions are re-read from the DB on each refresh;</li><li>privileged or MFA users must log in again with MFA instead of silently extending.</li></ul> Logout revokes the family. The auth middleware checks family revocation. | `api/auth.py`, `core/security.py`, `core/auth_middleware.py` |
| **F-29** in-memory voice security state | OTP challenges, manager action previews and telephony replay nonces now live in PostgreSQL tables with RLS (migration `015`). <ul><li>OTPs are stored as HMAC-SHA256, single-use, with 3 attempts and a 5-minute expiry.</li><li>Previews are bound to tenant + user and single-use.</li><li>Nonces are unique per tenant.</li></ul> Any API worker can now verify what another worker issued, and the state survives restarts. | `voice/security.py`, `voice/service.py`, `voice/manager_copilot.py`, `api/voice.py`, `migrations/015_*.sql` |
| **F-30** plaintext integration secrets | `tenant_channel_integrations.webhook_secret` uses a new `EncryptedSecret` column type: AES-256-GCM with associated data, key `INTEGRATION_SECRET_KEY` (covered by the startup default-secret guard). Legacy plaintext rows are still readable; `python -m src.backend.migrations.encrypt_channel_secrets` re-encrypts them. Migration `016` widens the column to TEXT. **Also fixed:** the carrier webhook verified against the hardcoded constant `amana/simulated_webhook_secret_default` with the tenant taken from a client header. It now uses the tenant's own `CARRIER_<CODE>` secret; the shared value is a development-only fallback. | `core/crypto_types.py`, `api/logistics.py`, `core/config.py`, `migrations/016_*.sql`, `migrations/encrypt_channel_secrets.py` |
| **F-13** retention | The worker now purges, per tenant under RLS: recordings past `expires_at` or older than 90 days, transcripts older than 365 days, and expired OTP challenges, action previews and nonces. | `src/backend/worker.py` |
| **F-22** committed DB dump | `evidence/step-12/dr/sales_ai_db_backup.dump` is **untracked** (`git rm --cached`; your local file is kept). `*.dump`, `*.backup` and `*.sql.gz` are git-ignored. The DR drill now writes its dump to the OS temp folder, records only the hash and metrics, and deletes the dump afterwards. | `.gitignore`, `scripts/dr_backup_restore_drill.py` |
| Supply chain (F-25, F-26 partial) | Pinned `requirements.txt` / `requirements-dev.txt` covering the packages the code imports, at the versions the suite was verified with. New `.github/workflows/ci.yml` runs tests on PostgreSQL 16, `pip-audit` (SCA), `bandit` (SAST) and gitleaks over the full history. | `requirements*.txt`, `.github/workflows/ci.yml` |

## Tests
- **New `tests/security/test_group_c_regressions.py`** (7 tests):
  - refresh rotation, theft (reuse) detection and family revocation;
  - OTPs are hashed, single-use, and work across "workers";
  - telephony replay is rejected from the durable nonce table;
  - secrets are encrypted at rest, and the per-tenant carrier secret beats the dev fallback;
  - retention purge;
  - no tracked dumps;
  - **real PostgreSQL:** the app role is denied DELETE/UPDATE on `tenants` and INSERT on `roles`, the audit chain links and verifies, UPDATE is refused, and a forced tamper is detected (rolled back afterwards).
- **Updated tests:**

| Test | Change |
|---|---|
| `test_postgres_rls.py` | The setup/teardown that deleted tenants through the app role now uses an admin connection. The tautological policy-count assertion (any of 11 historical numbers) is **replaced** by a real coverage check: every table with `tenant_id` must have RLS enabled, forced and a tenant policy. The one documented exception is `tenant_channel_integrations`, which is read before the tenant is known and whose secrets are now encrypted. |
| `test_step03_real_postgres.py` | Admin connection for tenant cleanup. |
| Manager-guard tests | Updated for the async, DB-backed guard (`test_manager_copilot_and_mfa`, scenario D, `test_f06_guard_unit_binding`, which now also checks single use). |
| `test_logistics_and_support_apis.py` | Uses the configured dev carrier secret instead of the removed literal. |
| `test_agent_apis.py` | Explicit deterministic model stub. It had failed on a live-model timeout under full-suite load: an API contract test, not a model-quality test. |

- **Full suite:** **430 passed, exit 0, 370 s** (`test-logs/remediation_c_full.log`).
- **Live check:** `python -m src.backend.worker --once` as `sales_app_user`: 81 tenants, 0 errors.
- **9B timeout:** the 9B cold-start timeout was raised to 180 s. Under full-suite memory pressure (~0.4 GB free) the 9B load exceeded 90 s; interactive 4B stays at 60 s.
- **Migrations 014–016** were applied to the local dev DB (a backup was taken first in the session scratchpad) and appended to `infra/init-db.sql`.

## Still open after group C
- **Git history:** the dump is still in Git history. Purging it needs a history rewrite (e.g. `git filter-repo`), which requires your explicit approval because it changes every commit hash.
- **CI not run:** the CI workflow has not run here (no runner), so `pip-audit`, `bandit` and gitleaks results are **not verified**. There is no hashed lock file yet.
- **Identity:** OIDC/JWKS (RS256) is not done; it still uses local HS256 JWTs.
- **Rate limiting:** the call-flood limiter is still in memory (single-process). There is no global API rate limit.
- **Tenant switch bug:** `POST /tenants/switch` queries the target tenant's users under the *current* tenant's RLS context, so it cannot work as the app role. This was found during this pass and is not fixed.
- **Object storage:** recording objects in object storage need a lifecycle rule; only the metadata rows are purged.
- **Groups D–F remain:** agents/RAG (F-17, F-18), real STT/TTS (F-15), frontend (F-20), TLS/reverse proxy/observability (F-26).
