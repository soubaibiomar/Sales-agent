# 18 — Group F (Production Infrastructure) Remediation Record

- **Branch:** `fix/group-a-p0-remediation`, continuing after commit `88d5bf3`.
- **Scope:** remediation group F of report 11, finding **F-26**: "deployment is local-only: `/ready` hardcoded, no API container, no TLS / reverse proxy, no CI pipeline". It also covers related honesty issues found along the way (F-23 style: invented telemetry).

## What changed

| Area | Fix | Main files |
|---|---|---|
| **Readiness and liveness** | <ul><li>`/ready` used to answer `{"database": "UP", "redis": "UP", "storage": "UP"}` without checking anything. It now runs real checks with a 3 s timeout:<ul><li>PostgreSQL: `SELECT 1`, plus a check that the connection does **not** bypass RLS (outside development).</li><li>Ollama: reported, but optional.</li></ul></li><li>It returns **503** when the database fails.</li><li>Errors are reduced to the exception class name; connection strings and hostnames are never echoed.</li><li>`/health` is now pure liveness.</li><li>`/api/v1/observability/health` is now authenticated (it was public) and uses the same checks. It used to report hardcoded latencies (1.2 ms / 0.8 ms) and a Redis check that always failed because the library was not installed.</li></ul> | `src/backend/core/operations.py`, `src/backend/main.py`, `src/backend/api/observability.py` |
| **Metrics** | <ul><li>Prometheus `/metrics` exposes request counter, latency histogram, dependency-up and dependency-latency gauges.</li><li>Labels use the **route template**, never the raw path, so cardinality stays bounded.</li><li>It requires `METRICS_TOKEN`, which is mandatory outside development (the startup validator refuses to start without it).</li><li>The metrics middleware is pure ASGI, so it is safe for WebSockets and streaming.</li></ul> | `src/backend/core/operations.py`, `src/backend/core/config.py` |
| **Log redaction** | <ul><li>The JSON formatter that claimed to redact PII redacted nothing, and nothing installed it.</li><li>`RedactingFilter` is now installed on every root and uvicorn handler, in the API and in the worker. It redacts:<ul><li>credentials in connection URLs;</li><li>Bearer tokens and JWTs;</li><li>`password` / `secret` / `token` / `otp` fields;</li><li>e-mail addresses, card numbers and international phone numbers.</li></ul></li><li>Exception tracebacks are redacted too. Logs are JSON lines outside development.</li></ul> | `src/backend/core/operations.py`, `src/backend/worker.py` |
| **Migrations as a release step** | <ul><li>The old runner ran ORM `create_all`, then `init-db.sql` split on `;`, **ignoring every failing statement**.</li><li>The new runner: an ordered `NNN_*.sql` ledger (`schema_migrations` with SHA-256 checksums), one transaction per file, stop on first error, reject edited migrations, advisory lock against concurrent releases, `--baseline` / `--status`. It creates or rotates `sales_app_user` from `APP_DB_PASSWORD` (always NOSUPERUSER / NOBYPASSRLS).</li><li>**Divergence found and fixed.** Building a database from the numbered migrations alone was impossible: `014` needs `pgcrypto`, which only `init-db.sql` created. Once that was fixed, the result was still **insecure**:<ul><li>13 tables (`users`, `user_roles`, `audit_logs`, `conversations`, `contacts`, `outbox_events`, …) had **no tenant RLS**;</li><li>42 timestamp columns differed;</li><li>roles and permissions were never seeded.</li></ul></li><li>`000_extensions.sql` and a generated, idempotent `018_init_db_parity.sql` close the gap.</li></ul> | `src/backend/migrations/runner.py`, `000_extensions.sql`, `018_init_db_parity.sql` |
| **Container image** | <ul><li>Multi-stage `Dockerfile`, one image for three roles: api, worker and migrate.</li><li>Runs as non-root (uid 10001) and has a `HEALTHCHECK`.</li><li>Only `src/` is copied.</li><li>`.dockerignore` excludes `.env`, `.git`, tests, evidence and backups.</li></ul> | `Dockerfile`, `.dockerignore` |
| **Full stack** | `infra/docker-compose.stack.yml` layers onto the existing compose file:<ul><li>a **migrate** one-shot that gates api and worker (`service_completed_successfully`);</li><li>**api** and **worker**, both read-only filesystem, all capabilities dropped, `no-new-privileges`;</li><li>a **Caddy TLS proxy**, the only published ports (80→443 redirect). It sets HSTS and returns 404 for `/metrics` and the API docs from outside, and proxies WebSockets;</li><li>**Prometheus** with 5 alert rules: API down, database not ready, model runtime down, 5xx > 2 %, non-AI p95 > 200 ms target.</li></ul>Every secret is `${VAR:?}`, so deployment **fails** instead of falling back to a committed default. Template: `infra/stack.env.example`. | `infra/docker-compose.stack.yml`, `infra/proxy/Caddyfile`, `infra/observability/*` |
| **CI/CD** | <ul><li>Tests now run on a database built by the **migration runner** (it used to use `init-db.sql`).</li><li>Security job, existing: pip-audit, bandit, gitleaks.</li><li>Security job, new: the compose stack must validate, **and must fail** when a secret is missing.</li><li>New `image` job:<ul><li>build;</li><li>Trivy scan, which fails on fixable HIGH/CRITICAL findings;</li><li>SPDX SBOM;</li><li>on `main` only: push to GHCR by commit SHA, then **keyless cosign signature** plus SBOM attestation.</li></ul></li><li>Rollback means redeploying a previous signed digest.</li></ul> | `.github/workflows/ci.yml` |
| **Backups** | <ul><li>`scripts/backup_database.py` exported only **10 of 88 tables**, with a key derived from the JWT secret. It is now labelled as a legacy partial export.</li><li>New `scripts/pg_backup.py`:<ul><li>full `pg_dump`, streamed, so the plaintext never touches disk;</li><li>AES-256-GCM in 1 MiB chunks, with an authenticated index and final flag that detect reordering, truncation and appended data;</li><li>a dedicated `BACKUP_ENCRYPTION_KEY`;</li><li>a manifest with SHA-256 and per-table row counts;</li><li>`--copy-to` for a verified off-site copy;</li><li>restore into a **new** database only;</li><li>`drill`, which compares every table and the security catalogue.</li></ul></li></ul> | `scripts/pg_backup.py` |
| **Honest telemetry** | <ul><li>The voice benchmark API filled ASR = 110 ms and LLM = 380 ms with constants while flagging them "not simulated". Those stages are now excluded and labelled `not_measured`.</li><li>The voice observability page showed "Measured … 518.3 ms — MEETS_TARGET". It now shows the **measured** group D result: median 6 859 ms, target **not met**.</li><li>The "6,307 MB" VRAM fallback and the static "PASS" table are replaced by live or "Non mesuré" values.</li><li>The endpoint is authenticated and uses 2 iterations off the event loop (it used to run 40 real syntheses per public GET).</li></ul> | `src/ai/voice/voice_observability.py`, `src/frontend/voice_observability.html`, `js/pages/voice_observability.js`, `js/pages/workflow_reliability_dashboard.js` |

## Verification (executed 2026-11-25)

**Migration parity**
- Built one database from `000`–`018` with the runner and another from `infra/init-db.sql`, then compared them.
- Result: **0 differences** across 1 061 columns, 87 RLS flags, 82 policies, 526 constraints, 239 functions, 335 grants, 287 indexes, 40 permissions and 6 roles.
- Behaviour checks:
  - re-running the runner applies 0 files;
  - an edited migration is rejected (checksum mismatch);
  - a failing migration stops the release, is rolled back and is not recorded;
  - the app role is NOSUPERUSER / NOBYPASSRLS.
- Evidence: `evidence/claude-inspection/group_f/migration_parity_check.json`. The script is `evidence/claude-inspection/scripts/migration_parity_check.py`.
- The dev database is now tracked: `--baseline 017`, then `018` applied.

**Backup and restore drill** (`backup_restore_drill.json`)

| Measure | Result |
|---|---|
| Tables / rows compared | 88 tables, 1 013 rows |
| Row-count mismatches | 0 |
| RLS-forced tables, policies, functions | identical in source and restore (82 / 82 / 239) |
| Encrypted size | 0.5 MB |
| Backup time | 0.70 s |
| Restore time | 2.19 s |
| Off-site copy | checksum re-verified |
| Wrong key / tampered byte / truncated file | all **rejected** |

These timings are for this small development dataset on the laptop. They are **not** a production RTO.

**Live readiness** (`readiness_live_check.json`; API running as `sales_app_user`)
- `/ready` returned 200 READY with `rls_enforced: true`.
- `/metrics` returned 401 without the token, and the metrics with it.
- With the Postgres container stopped, `/ready` returned **503 NOT_READY** (`TimeoutError`, 3.0 s).
- Stopping the container coincided with Docker Desktop exiting on this machine. It was relaunched, and the database came back with its data and migration ledger intact.

**Compose**
- `docker compose … config` validates the 8-service stack.
- Removing `METRICS_TOKEN` makes it fail with "required variable … is missing a value".

**Tests**
- `tests/security/test_group_f_regressions.py`: 28 passed (including the readiness-deadline test added after the stack run).
- Full suite: **793 passed** (`python -m pytest -q`, 404 s, Python 3.14, Windows), after the stack-run fixes.

## Stack run (2026-11-25, downloads approved by the user)
Evidence: `evidence/claude-inspection/group_f/stack_run_verification.json`. The overlay is `infra/docker-compose.verify.yml`, run as project `salesai-verify`. It used:
- isolated containers and fresh volumes;
- no `init-db.sql` bootstrap;
- random secrets, deleted afterwards;
- ports 8443 and 8080.

| Check | Result |
|---|---|
| **Image build** | 210 s, 950 MB. Runs as uid 10001, with no compiler. The image contains no `.env`, `.git`, tests, evidence, backups or `infra/`. With `ENVIRONMENT=production` and the committed defaults, it **refuses to start**. |
| **Release gate** | Migrate built the empty database: 19 migrations, exit 0. A re-run applied 0. The API and worker started only after migrate succeeded. |
| **TLS proxy** | `/ready` over HTTPS: 200 READY (`rls_enforced: true`). `/metrics` and `/api/docs` from outside: **404**. HTTP returns 301 to HTTPS. The HSTS, strict CSP and `X-Frame-Options` headers are present. The API is not published on the host. |
| **End to end over HTTPS** | Wrong password: 401. Login issued a token. CRM returned only the user's own-tenant account (RLS). An `X-Tenant-ID`-only request: **401**. |
| **Logs** | The worker writes JSON lines. The API log contains 0 occurrences of the password, token or e-mail. |
| **Hardening** | API and worker run as uid 10001 with a **read-only root** (a write attempt was refused), all capabilities dropped and `no-new-privileges`. |
| **Prometheus** | Scrapes the API with the token from a secret (target `up`). All 5 rules loaded. |
| **Database outage** (`docker pause`) | `/ready` returns **503 in 3.2 s**, measured 3 times. `DatabaseNotReady` was pending at 38 s and **firing at 97 s**. Back to 200 after unpausing. |

**Two bugs found only by running the stack, both fixed:**
1. Compose cannot mount an environment-sourced secret into a read-only container, so Prometheus failed to start. Prometheus now runs with `read_only: false`; its other hardening options are kept.
2. The first `/ready` request after the freeze got **no answer within 10 s**. `asyncio.wait_for` waits for cancellation to finish, and cancelling a query on a pooled connection to a frozen server hangs. Readiness now gives up at the deadline and lets the task cancel in the background. A regression test simulates a cancellation that hangs for 10 s and requires an answer in under 2 s.

## Not done / not verified (not claimed)
- **No image vulnerability scan run locally.** Trivy or pip-audit would need further downloads beyond the approved build-and-run scope. The CI `image` job is where that gate runs.
- **CI:** it runs on every push. Runs #1–#5 failed: the test job had no Postgres password (now uses the public dev defaults the tests expect, so no repository secrets are needed). The security job failure is under investigation (its logs require a GitHub sign-in).
- **Off-site storage:** "off-site" was simulated with a separate directory. No cloud bucket or remote site, encryption key escrow or backup schedule exists yet.
- **RPO and RTO:** RPO equals the backup interval, which is not scheduled yet. The RTO for production volumes is unmeasured.
- **Tracing and dashboards:** no OpenTelemetry trace export, no Grafana dashboards and no Alertmanager receiver (the receiver is an operator decision).
- **Redis:** it is in the compose stack but the application does not use it. The reliability dashboard now says so instead of showing "UP".
- **TLS certificates:** `tls internal` (local CA) is the default. A real certificate needs a public DNS name and `TLS_MODE` set to an ACME e-mail.
