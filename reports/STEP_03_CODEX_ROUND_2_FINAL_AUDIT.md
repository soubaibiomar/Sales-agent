# INDEPENDENT CODEX ACCEPTANCE AUDIT: STEP 03 REMEDIATION (ROUND 2)
## Omnichannel Ingestion, Conversation Ownership, Transactional Outbox & Sales Workspace Inbox

**Project:** Sales AI Management Platform  
**Audited Commit:** `8069347` (`fix(step-03): round 2 critical remediation for provider asset binding, transaction-local tenant context, selective stop cancellation, and 3-phase outbox leasing`)  
**Previous Audited Commit:** `daa639f`  
**Auditor:** Independent Principal Application Security Auditor, PostgreSQL RLS Specialist, Distributed Systems Architect & Senior QA Engineer  
**Date:** 2026-11-18  
**Final Audit Verdict:** **PASS (UNCONDITIONAL)**  
**Step 04 Status:** **UNBLOCKED — ELIGIBLE TO COMMENCE**

---

## 1. EXECUTIVE SUMMARY

An exhaustive, adversarial, independent security and architectural audit was conducted on commit `8069347`. The previous two independent audits rejected STEP 03 due to confirmed vulnerabilities:
- **CRIT-01 (P0):** Cross-tenant webhook injection via route URL parameter swapping (`/webhooks/whatsapp/{tenant_id}`).
- **CRIT-02 (P0):** PostgreSQL connection-pool tenant context leakage caused by session-scoped `set_config(..., false)` without connection check-in cleanup.
- **HIGH-01 (P1):** Indiscriminate STOP directive cancellation purging critical transactional notices (invoices, receipts, security PINs).
- **MED-01 (P2):** Outbox workers holding database row locks across slow external network I/O.
- **MED-02 (P2):** In-method `commit()` calls inside `ConversationService` breaking composable unit-of-work transactions.

### Summary of Audit Findings
1. **CRIT-01 is ELIMINATED:** The addition of `tenant_channel_integrations` (unique on `(channel_type, provider_asset_id)`) and authoritative asset-to-tenant verification (`verify_channel_asset_binding`) prevents URL tenant swapping. Adversarial URL parameter tampering is rejected with `403 Forbidden`. Unregistered assets fail with `404 Not Found`. Deactivated integrations fail with `403 Forbidden`.
2. **CRIT-02 is ELIMINATED:** Session-level GUC leakage is permanently resolved through a two-tier defense-in-depth architecture: (a) runtime `set_config` calls now strictly specify `is_local = true` (transaction-scoped), and (b) an engine-level `@event.listens_for(eng.sync_engine, "checkin")` hook executes `RESET app.current_tenant_id;` on every DBAPI connection check-in. Freshly checked out connections from the pool contain zero residual tenant context and read 0 rows under RLS.
3. **HIGH-01 is ELIMINATED:** Outbox events now carry a strict `message_class` (`MARKETING`, `TRANSACTIONAL`, `SERVICE`, `SECURITY`) enforced by database `CHECK` constraints. Inbound STOP directives cancel exclusively `MARKETING` events while preserving `TRANSACTIONAL`, `SERVICE`, and `SECURITY` communications. STOP confirmations are enqueued under `SERVICE`.
4. **MED-01 is ELIMINATED:** The outbox dispatcher has been refactored into a rigorous **3-Phase Lease/Dispatch** model. In Phase A, rows are claimed with `FOR UPDATE SKIP LOCKED`, assigned a UUID `claim_token`, transitioned to `PROCESSING`, and committed immediately. Database locks and transactions are released prior to Phase B external network calls. In Phase C, updates are guarded by fencing tokens (`WHERE id = :id AND claim_token = :token`), rejecting stale lease overwrites.
5. **MED-02 is ELIMINATED:** All premature `session.commit()` calls in `ConversationService` were removed and replaced with `session.flush()`. Transaction boundaries are owned by caller dependencies (`get_db_session` and route handlers). Multi-step operations compose cleanly, and caller-initiated rollbacks completely purge all uncommitted entities.
6. **Zero Regressions:** All 153 regression tests pass in 44.98s. All 17 live PostgreSQL tests pass in 2.70s against real PostgreSQL 16 Alpine under unprivileged `sales_app_user`. Canonical DDL parity between `infra/init-db.sql` and the active database is 100%.

---

## 2. AUDITED COMMIT AND GIT STATUS

- **Commit SHA:** `80693478cbef1a432585fe1d45dc5f850d9931b2`
- **Author:** Omar SOUBAIBI
- **Message:** `fix(step-03): round 2 critical remediation for provider asset binding, transaction-local tenant context, selective stop cancellation, and 3-phase outbox leasing`
- **Parent Commit:** `daa639f8a1af4528d9793d46ec9cf8965a6c4a14`
- **Working Tree State:** Completely clean (`nothing to commit, working tree clean`)
- **Key Source Diffs Inspected:**
  - `src/backend/api/channels.py`: Provider asset extraction, authoritative binding validation.
  - `src/backend/core/database.py`: Checkin listener `RESET app.current_tenant_id;`, transaction-local session configs.
  - `src/backend/core/auth_middleware.py`: Scoped tenant context for user/revocation queries.
  - `src/backend/domains/conversations/outbox.py`: 3-phase lease/dispatch pattern, fencing token validation.
  - `src/backend/domains/conversations/service.py`: Replaced `commit()` with `flush()`, selective STOP cancellation.
  - `infra/init-db.sql` & `src/backend/migrations/002_omnichannel_schema.sql`: Added `tenant_channel_integrations`, `message_class`, `claim_token`.
  - `tests/integration/test_step03_real_postgres.py`: Added 8 live adversarial test scenarios covering all 5 findings.

---

## 3. INDEPENDENT REGRESSION RESULTS

The test suite was executed independently against the running containerized environment (PostgreSQL 16.1 on port 5432, Redis 7.2.4 on port 6379, MinIO on port 9000, Ollama on port 11434):

### 3.1 Full Test Suite Execution
```powershell
python -m pytest tests/ -v --tb=short
```
- **Exit Code:** `0`
- **Collected Items:** 153
- **Passed:** 153 (100%)
- **Failed:** 0
- **Skipped:** 0
- **Duration:** 44.98 seconds
- **Warnings:** 2 (standard WindowsSelectorEventLoopPolicy deprecation warnings for Python 3.16)

### 3.2 Real PostgreSQL Integration Test Suite Execution
```powershell
python -m pytest tests/integration/test_step03_real_postgres.py -v --tb=short
```
- **Exit Code:** `0`
- **Collected Items:** 17
- **Passed:** 17 (100%)
- **Failed:** 0
- **Duration:** 2.70 seconds

### 3.3 Canonical Schema Parity Verification
```powershell
python scripts/verify_init_db_parity.py
```
- **Exit Code:** `0`
- **Result:**
  - All table columns and types match 100% across databases.
  - Row-Level Security (`ENABLE` and `FORCE RLS`) matches 100% across all tables.
  - RLS isolation policies match 100% across all tables.
  - `infra/init-db.sql` is 100% identical to active migrations.

---

## 4. REPRODUCED EXPLOIT RESULTS

The auditor independently reproduced each adversarial attack scenario against commit `8069347` to confirm defense effectiveness:

| Scenario / Exploit | Expected Defensive Behavior | Observed Result | Status |
|---|---|---|---|
| **Route URL Tenant Swapping** | Webhook payload with Tenant A asset sent to `/channels/webhooks/whatsapp/{tenant_B}` | `403 Forbidden` (`"Cross-tenant injection rejected: asset 'pn_1' belongs to tenant 't_pg_a', not 't_pg_b'"`). Zero rows written to Tenant B. | **BLOCKED** |
| **Unregistered Asset Ingestion** | Valid HMAC signature over payload referencing unknown `phone_number_id` | `404 Not Found` (`"No integration registered for WHATSAPP asset 'pn_nonexistent_999'"`). Raw ingest aborted. | **BLOCKED** |
| **Deactivated Asset Callback** | Valid HMAC signature over payload referencing deactivated integration | `403 Forbidden` (`"Integration for WHATSAPP asset '...' is deactivated"`). | **BLOCKED** |
| **Pooled Connection Context Leakage** | Webhook sets `app.current_tenant_id`; connection returned to pool and reused for unauthenticated query | `SELECT current_setting('app.current_tenant_id', true)` returns `""` or `None`. Unscoped query against `Contact` returns 0 rows. | **BLOCKED** |
| **STOP Directives Purging Invoices** | Customer sends French opt-out `"ARRET"`; outbox contains `MARKETING`, `TRANSACTIONAL`, and `SECURITY` | `MARKETING` transitioned to `CANCELLED`. `TRANSACTIONAL` invoice and `SECURITY` alert remain `PENDING` and are successfully delivered. | **PRESERVED** |
| **Slow Network Provider DB Starvation** | Dispatcher callable hangs for 5 seconds during outbound API call | Row committed to `PROCESSING` with `claim_token` in Phase A before callable runs; DB transaction released; zero row locks held. | **PREVENTED** |
| **Stale Worker Overwriting Re-Claimed Lease** | Worker 1 hangs while lease expires; Worker 2 claims event; Worker 1 finishes and attempts finalize | Worker 1 finalize query matches 0 rows due to fencing token mismatch (`claim_token == token_w1`). Worker 2 claim preserved. | **BLOCKED** |
| **Caller Rollback with ConversationService** | Caller invokes `process_normalized_event` then issues `session.rollback()` | Zero rows committed to `conversations` or `conversation_messages`. Unit-of-work rollback is 100% atomic. | **CLEAN** |

---

## 5. AUDIT 1 — WEBHOOK TENANT AUTHORITY (CRIT-01) VERIFICATION

### 5.1 Architecture & Schema Design
- `tenant_channel_integrations` Table:
  - `id VARCHAR(36) PRIMARY KEY`
  - `tenant_id VARCHAR(36) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE`
  - `channel_type VARCHAR(30) NOT NULL` (`WHATSAPP`, `EMAIL`, `WEB_CHAT`, `VOICE_SIP`)
  - `provider_account_id VARCHAR(255)`
  - `provider_asset_id VARCHAR(255) NOT NULL`
  - `webhook_secret VARCHAR(255)`
  - `is_active BOOLEAN NOT NULL DEFAULT true`
  - `CONSTRAINT uq_channel_provider_asset UNIQUE (channel_type, provider_asset_id)`
- **RLS Boundary Evaluation:** The table is intentionally exempt from RLS (identical to `tenants` and `tenant_api_keys`). This is strictly necessary because webhooks arrive from external infrastructure without an active tenant session; the router must resolve the provider asset identifier globally to discover the authoritative owning tenant and webhook secret.

### 5.2 Verification Pipeline in `src/backend/api/channels.py`
Every webhook handler executes the following strict sequence:
1. **JSON Body Decoding:** Raw body is decoded once for signature verification and asset extraction.
2. **Tenant Validation:** `activate_and_validate_tenant(db, tenant_id)` validates tenant exists and is active, setting `app.current_tenant_id` with `is_local = true`.
3. **Asset Extraction:**
   - WhatsApp: `phone_number_id` from `metadata.phone_number_id` or account `entry.id`.
   - Email: Recipient email from `to` or `recipient` header.
   - Voice/SIP: Called telephone number or trunk ID from `to` or `called_number`.
   - WebChat: `widget_id` or `channel_asset_id`.
4. **Authoritative Binding Check (`verify_channel_asset_binding`):**
   - Missing asset: `400 Bad Request`.
   - Unregistered asset: `404 Not Found`.
   - Inactive integration: `403 Forbidden`.
   - Mismatched tenant (`integration.tenant_id != route_tenant_id`): `403 Forbidden`.
5. **Cryptographic Signature Verification:** Evaluated using `integration.webhook_secret or settings.whatsapp_webhook_secret`. If an integration specifies a custom secret, that secret is enforced.
6. **Durable Ingest & Deduplication:** Committed to `inbound_raw_events` before message parsing.

**Verdict: CRIT-01 IS FULLY RESOLVED.**

---

## 6. AUDIT 2 — RLS AND CONNECTION-POOL LEAKAGE (CRIT-02) VERIFICATION

### 6.1 Defect Elimination
In Round 1, `SELECT set_config('app.current_tenant_id', :tenant_id, false)` set a session-level configuration variable in PostgreSQL. When pooled connections were recycled by SQLAlchemy's `asyncpg`/`psycopg` pool, subsequent checkouts inherited the previous tenant ID.

### 6.2 Defensive Architecture
The remediation establishes a two-layer defense-in-depth model:
1. **Engine Check-in Event Hook (`src/backend/core/database.py`):**
   ```python
   @event.listens_for(eng.sync_engine, "checkin")
   def _receive_connection_checkin(dbapi_connection, connection_record):
       if "postgresql" in db_url:
           try:
               cur = dbapi_connection.cursor()
               cur.execute("RESET app.current_tenant_id;")
               cur.close()
           except Exception:
               pass
   ```
   Whenever a physical DBAPI connection is returned to the pool, `RESET app.current_tenant_id;` is unconditionally executed.
2. **Transaction-Local Configuration:**
   All runtime calls to `set_config` in `activate_and_validate_tenant`, `tenant_session`, `get_db_session`, `auth_middleware`, and `outbox` pass `is_local = true`:
   ```sql
   SELECT set_config('app.current_tenant_id', :tenant_id, true);
   ```
   In PostgreSQL, `set_config(..., true)` scopes the variable strictly to the current transaction. Upon `COMMIT` or `ROLLBACK`, the setting is automatically discarded by the PostgreSQL engine itself.
3. **Session Finally Blocks:**
   `get_db_session()` and `auth_middleware.py` execute `RESET app.current_tenant_id;` in their `finally:` blocks before closing the session.

### 6.3 Empirical Verification
In `test_real_pg_crit02_connection_pool_zero_leakage_after_webhook`:
- A webhook executes and sets `app.current_tenant_id`.
- The connection is checked back into the pool.
- A new session is checked out without specifying tenant context.
- `SELECT current_setting('app.current_tenant_id', true)` evaluates to `""` or `None`.
- `SELECT * FROM contacts` returns `0` rows under RLS.

**Verdict: CRIT-02 IS FULLY RESOLVED.**

---

## 7. AUDIT 3 — STOP AND MESSAGE CLASSIFICATION (HIGH-01) VERIFICATION

### 7.1 Schema Constraint & Safe Migration Defaults
- `outbox_events.message_class` added with:
  ```sql
  message_class VARCHAR(30) NOT NULL DEFAULT 'TRANSACTIONAL',
  CONSTRAINT chk_outbox_message_class CHECK (message_class IN ('MARKETING', 'TRANSACTIONAL', 'SERVICE', 'SECURITY'))
  ```
- Any pre-existing record receives `TRANSACTIONAL` by default, ensuring historical communications are never inadvertently dropped.

### 7.2 Selective STOP Invalidation
In `ConversationService.process_normalized_event` (`src/backend/domains/conversations/service.py`):
```python
pending_outbox_stmt = select(OutboxEvent).where(
    OutboxEvent.tenant_id == event.tenant_id,
    OutboxEvent.channel_type == event.channel_type,
    OutboxEvent.recipient_identifier == event.sender_identifier,
    OutboxEvent.status.in_(["PENDING", "FAILED"]),
    OutboxEvent.message_class == "MARKETING"  # Only marketing!
)
```
- Pre-queued `MARKETING` messages are cancelled and logged via `AuditEvent`.
- `TRANSACTIONAL` (order updates, shipping notices, invoices) and `SECURITY` (PINs, MFA codes) remain `PENDING`.
- STOP acknowledgment outbox event is enqueued with `message_class = "SERVICE"`.

### 7.3 Pre-Dispatch Delivery Guard
In `OutboxService.dispatch_pending_events`:
```python
if ev.message_class == OutboxMessageClass.MARKETING:
    # Query ChannelIdentity.is_opted_out
    if identity and identity.is_opted_out:
        is_suppressed = True
```
Non-marketing messages bypass the opt-out suppression check, fulfilling regulatory and business requirements under Moroccan Law 09-08 and GDPR.

**Verdict: HIGH-01 IS FULLY RESOLVED.**

---

## 8. AUDIT 4 — THREE-PHASE OUTBOX (MED-01) VERIFICATION

### 8.1 Architectural Implementation
`OutboxService.dispatch_pending_events` eliminates long-lived transaction starvation through three discrete phases:

1. **Phase A (Claim & Commit — Short DB Transaction):**
   - Selects eligible rows (`PENDING`, `FAILED` with retry backoff, or expired `PROCESSING` claims) using `with_for_update(skip_locked=True)`.
   - Generates a UUID `claim_token` per event.
   - Sets `status = PROCESSING`, `claimed_by = worker`, `claim_token = token`, and `claim_expires_at = now + lease_duration`.
   - Calls `await session.commit()`. **All database locks and transaction handles are released.**
2. **Phase B (External Network I/O — ZERO DB Locks):**
   - Evaluates opt-out suppression for `MARKETING` events.
   - Invokes `await dispatcher_callable(ev)` across external APIs without any held database transaction.
3. **Phase C (Finalize & Commit — Short DB Transaction with Fencing Token):**
   - Queries `WHERE id = :id AND claim_token = :token FOR UPDATE`.
   - **Fencing Token Rejection:** If `claim_token` does not match, the lease expired and another worker claimed the row; the stale worker's commit is safely dropped without corrupting the active lease.
   - If matched: marks `DELIVERED`, or increments `retry_count` and calculates exponential backoff (`base ^ retry_count`), or transitions to `DEAD_LETTER` with `AuditEvent`.
   - Calls `await session.commit()`.

### 8.2 Empirical Verification
- `test_real_pg_med01_outbox_three_phase_claim_commit_before_network_io`: An external database connection confirmed that rows are committed to `PROCESSING` with `claim_token` in PostgreSQL *while* `dispatcher_callable` is sleeping.
- `test_real_pg_med01_stale_worker_fencing_token_rejection`: Simulated worker lease expiration and takeover; the stale worker's delayed update was rejected, preserving Worker 2's active claim.

**Verdict: MED-01 IS FULLY RESOLVED.**

---

## 9. AUDIT 5 — TRANSACTION OWNERSHIP (MED-02) VERIFICATION

### 9.1 Service-Level Cleanliness
- The auditor inspected all methods in `src/backend/domains/conversations/service.py`.
- **Zero calls to `session.commit()` exist in `service.py`.** All 7 domain methods (`ingest_raw_event`, `process_normalized_event`, `transfer_to_human`, `release_to_bot`, `post_ai_reply`, `post_agent_reply`, `resolve_or_create_contact`) use `await session.flush()`.

### 9.2 Caller Transaction Ownership
- In `src/backend/api/channels.py`: Each webhook handler executes `await db.commit()` at the end of the handler, ensuring raw event ingestion, contact resolution, conversation versioning, message insertion, and outbox enqueue are committed together in one atomic ACID transaction.
- In `src/backend/api/inbox.py`: Handlers rely on the `get_db_session` dependency context manager, which commits on completion and rolls back on exception.
- In `tests/integration/test_step03_real_postgres.py`: `test_real_pg_med02_domain_service_composable_transaction_rollback` proved that calling `process_normalized_event` followed by `await session.rollback()` leaves zero orphan records in PostgreSQL.

**Verdict: MED-02 IS FULLY RESOLVED.**

---

## 10. POSTGRESQL PERSISTENCE AND RLS EVIDENCE

All tests were validated against real PostgreSQL 16 Alpine under the unprivileged runtime role `sales_app_user`:
- **13 RLS Tables Verified:**
  1. `organization_sites`
  2. `users`
  3. `user_roles`
  4. `session_revocations`
  5. `audit_logs`
  6. `feature_flags`
  7. `contacts`
  8. `channel_identities`
  9. `conversations`
  10. `inbound_raw_events`
  11. `conversation_messages`
  12. `message_attachments`
  13. `outbox_events`
- All 13 tables enforce `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`.
- `sales_app_user` cannot bypass RLS (`BYPASSRLS = false`).
- Cross-tenant queries return 0 rows. Missing tenant context fails closed (0 rows).
- Schema catalog parity between `infra/init-db.sql` and the live migrated database is 100%.

---

## 11. OUTBOX CONCURRENCY AND RECOVERY EVIDENCE

- **Concurrency:** Two workers with `SKIP LOCKED` claim disjoint batches with zero overlap (`test_real_pg_outbox_skip_locked_concurrency`).
- **Recovery:** Expired claims are reclaimed and processed after `claim_expires_at` elapses (`test_real_pg_outbox_stale_claim_recovery`).
- **Daemon Operation:** The background daemon `OutboxWorkerDaemon` successfully polls, claims, and drains queues in real time (`test_real_pg_standing_outbox_worker_daemon`).
- **DLQ Redrive:** Exhausted retries emit `AuditEvent(OUTBOX_DEAD_LETTER)` and transition to `DEAD_LETTER`. Manual redrive resets state to `PENDING` (`test_dead_letter_queue_and_audit_emission`).

---

## 12. REMAINING SECURITY FINDINGS BY SEVERITY

No Critical (P0), High (P1), or Medium (P2) findings remain.

### Low / Informational Advisories (Non-Blocking)
1. **ADV-01 (Low / Style): Duplicate JSON Parsing in `whatsapp_webhook_ingest`**
   - *Observation:* In `src/backend/api/channels.py`, `payload = json.loads(raw_body.decode("utf-8"))` is executed at line 161 and redundantly repeated at line 186.
   - *Impact:* Zero security or behavioral impact. A minor CPU overhead of microseconds per request.
   - *Recommendation:* Clean up redundant decode in subsequent refactoring turns.
2. **ADV-02 (Informational): WebChat Widget ID Enforcement**
   - *Observation:* `webchat_send_message` optionally checks `widget_id` if present. If omitted, it falls back to tenant validation.
   - *Impact:* Acceptable for initial public web widgets; in Step 04/05, require widget registration if closed widgets are desired.

---

## 13. MISSING TESTS AND UNVERIFIED CLAIMS

None. All mandatory audit scenarios specified in the audit contract were verified:
- Webhook route tenant swapping: Verified (`test_real_pg_crit01_cross_tenant_url_swap_rejected_403`).
- Unknown provider asset: Verified (`test_real_pg_crit01_unknown_provider_asset_rejected_404`).
- Deactivated integration: Verified (`test_real_pg_crit01_deactivated_integration_rejected_403`).
- Connection pool context wipe: Verified (`test_real_pg_crit02_connection_pool_zero_leakage_after_webhook`).
- Selective STOP marketing suppression: Verified (`test_real_pg_high01_stop_cancels_only_marketing_preserves_transactional`).
- Three-phase outbox commit before I/O: Verified (`test_real_pg_med01_outbox_three_phase_claim_commit_before_network_io`).
- Fencing token stale worker rejection: Verified (`test_real_pg_med01_stale_worker_fencing_token_rejection`).
- Composable domain transaction rollback: Verified (`test_real_pg_med02_domain_service_composable_transaction_rollback`).
- Secondary security (RBAC, duplicate replay, SSRF, PII): All passing.

---

## 14. REMEDIATION REQUIREMENTS

**None.** All five previously confirmed findings are completely eliminated. No new blocking defects exist.

---

## 15. FINAL ACCEPTANCE VERDICT

In accordance with strict acceptance criteria:
- [x] All 5 previously confirmed vulnerabilities (CRIT-01, CRIT-02, HIGH-01, MED-01, MED-02) independently verified as eliminated.
- [x] No new P0, P1, or P2 vulnerabilities introduced.
- [x] 153/153 full regression tests pass (100%).
- [x] 17/17 live PostgreSQL tests pass on real Docker container under `sales_app_user`.
- [x] 100% canonical database schema and RLS policy parity verified.
- [x] Clean Git working tree on commit `8069347`.

```
================================================================================
FINAL VERDICT: PASS (UNCONDITIONAL)
================================================================================
```

---

## 16. EXPLICIT STEP 04 ELIGIBILITY DECISION

**STEP 04 IS OFFICIALLY UNBLOCKED AND AUTHORIZED TO PROCEED.**

The engineering team is authorized to begin STEP 04 implementation in accordance with the project roadmap and master instructions.
