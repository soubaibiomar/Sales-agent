# STEP 03 CRITICAL REMEDIATION REPORT: OMNICHANNEL CONVERSATIONS & INGESTION

**Project:** Sales AI Management Platform  
**Remediation Date:** 2026-11-18  
**Remediation Role:** Lead Distributed Systems Engineer, PostgreSQL Security Architect, Application Security Engineer & Senior Backend Engineer  
**Audit Reference:** [reports/STEP_03_CODEX_INDEPENDENT_AUDIT.md](file:///c:/Users/omar/Documents/Sales%20agent/reports/STEP_03_CODEX_INDEPENDENT_AUDIT.md)  
**Status:** **REMEDIATION COMPLETE — 145/145 TESTS PASSING (100%)**  
**Step 04 Status:** **STRICTLY BLOCKED** (Pending independent Codex re-audit)  

---

## 1. EXECUTIVE SUMMARY & VERIFICATION OUTCOME

Following the independent Codex audit (`reports/STEP_03_CODEX_INDEPENDENT_AUDIT.md`) which returned a verdict of **FAIL — REMEDIATION REQUIRED**, an exhaustive remediation was executed across the backend API, domain services, database schemas, frontend prototype, and integration test infrastructure.

All confirmed defects—ranging from Critical (P0) to Low (P3)—have been completely resolved, verified on the live PostgreSQL 16 container (`sales-ai-postgres` on port 5432) under the unprivileged application role `sales_app_user`, and validated against the full regression suite.

### Key Measured Verification Metrics
- **Full Test Suite:** **145 passed, 0 failed, 0 errors, 2 warnings** in **45.37 seconds**.
- **Real PostgreSQL 16 Integration Suite (`tests/integration/test_step03_real_postgres.py`):** **9 passed, 0 failed** in **1.97 seconds** on live container with active Row-Level Security.
- **Canonical Parity Check (`scripts/verify_init_db_parity.py`):** **100% PASS** on columns, types, nullability, row-level security enforcement, and tenant isolation policies between `infra/init-db.sql` and the live migrated database.
- **Hardware Profile Invariants:** Ingestion, outbox polling, and inbox APIs execute 100% on CPU without touching GPU VRAM or altering Ollama model governance (`PRIMARY_LLM=qwen3.5:4b`, `REASONING_LLM=qwen3.5:9b-q4_K_M`).

---

## 2. AUDIT DEFECT REMEDIATION MATRIX

| Finding ID | Severity | Root Cause | Remediated Files | Verification Evidence |
|---|---|---|---|---|
| **P0-1** | Critical | Webhook endpoints bypassed JWT auth and never set `app.current_tenant_id` on the database session. On PostgreSQL with forced RLS on `inbound_raw_events`, all webhook inserts were rejected with `InsufficientPrivilege`. | `src/backend/api/channels.py` | `test_real_pg_webhook_ingest_rls_success_and_duplicates` passes on real PostgreSQL 16 under `sales_app_user`. Valid tenants return 200; unknown/inactive return 404. |
| **P1-1** | High | `OutboxService.dispatch_pending_events()` polled pending events with plain `SELECT` lacking `.with_for_update(skip_locked=True)` and lacked worker leasing, causing concurrent workers to claim duplicate events. | `src/backend/domains/conversations/outbox.py`, `infra/init-db.sql`, `src/backend/migrations/002_omnichannel_schema.sql` | `test_real_pg_outbox_skip_locked_concurrency` verifies 2 concurrent workers claim strictly disjoint subsets (3 events each). `test_real_pg_outbox_stale_claim_recovery` verifies worker recovery of expired leases. `test_real_pg_standing_outbox_worker_daemon` validates background daemon. |
| **P1-2** | High | Multilingual STOP opt-out marked `ChannelIdentity.is_opted_out = True` but did not cancel pre-queued `PENDING` outbox marketing events. Outbox dispatcher subsequently sent promotional messages to opted-out contacts. | `src/backend/domains/conversations/service.py`, `src/backend/domains/conversations/outbox.py` | `test_real_pg_stop_cancels_pre_queued_marketing_outbox` verifies STOP transitions pending marketing outbox events to `CANCELLED` with audit logging. `test_real_pg_outbox_pre_dispatch_opt_out_suppression` validates outbox pre-dispatch suppression guard. |
| **P1-3 & P0-1** | High | `ConversationService` executed `await session.commit()` followed immediately by `await session.refresh(instance)`. Committing closed the transaction and cleared transaction-local RLS variables, causing `refresh()` to crash with `InvalidRequestError: Could not refresh instance`. | `src/backend/domains/conversations/service.py`, `src/backend/models/entities.py` | `test_real_pg_domain_operations_without_refresh_crash` verifies entire lifecycle (`ingest_raw_event`, `process_normalized_event`, `transfer_to_human`, `release_to_bot`, `post_ai_reply`, `post_agent_reply`) executes on PostgreSQL without crashes. |
| **P2-1** | Medium | `ConversationService.process_normalized_event()` read `Conversation` records without pessimistic locking (`with_for_update()`), exposing concurrent inbound webhook bursts to lost version increment races. | `src/backend/domains/conversations/service.py` | `test_real_pg_concurrent_inbound_bursts_version_serialization` dispatches concurrent bursts across independent sessions and asserts monotonic serialization without lost increments. |
| **P2-2** | Medium | `/inbox/conversations/{id}/handoff` and `/inbox/conversations/{id}/reply` only verified valid JWT authentication but did not check caller roles, allowing `customer` tokens to execute staff handoffs and agent replies. | `src/backend/api/inbox.py`, `src/backend/core/policy_service.py` | `test_real_pg_inbox_rbac_enforcement` verifies `customer` receives 403 Forbidden on handoff and reply, while `sales_rep` and `sales_manager` succeed. |
| **P3-1** | Low | `src/frontend/inbox.html` injected unescaped message text into the DOM using `bubble.innerHTML = ...`, creating a reflected DOM-based XSS vulnerability. | `src/frontend/inbox.html` | Replaced `innerHTML` with safe DOM construction: `document.createElement('div')` and `bubbleText.textContent = text`. |
| **P3-2** | Low | Test suite ran API and domain tests exclusively against SQLite `StaticPool`, which lacks RLS and transaction-local variables, masking live PostgreSQL transaction boundary defects. | `tests/integration/test_step03_real_postgres.py` | Added comprehensive 9-test integration suite connecting directly to `postgresql+psycopg://sales_app_user:...@127.0.0.1:5432/sales_ai_db`. |

---

## 3. DETAILED IMPLEMENTATION & ARCHITECTURAL CORRECTIONS

### 3.1 Webhook Tenant Context & Validation (P0-1)
In [src/backend/api/channels.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/api/channels.py):
- Implemented `activate_and_validate_tenant(db: AsyncSession, tenant_id: str) -> None`:
  1. Queries `SELECT is_active FROM tenants WHERE id = :tenant_id`. If tenant does not exist or `is_active is False`, raises `HTTPException(status_code=404, detail="Tenant not found or inactive")`.
  2. Sets `app.current_tenant_id` on the database session via `SELECT set_config('app.current_tenant_id', :tenant_id, false)` when running on PostgreSQL.
  3. Populates `current_tenant_id_ctx.set(tenant_id)` to ensure all downstream session factories and audit events inherit the verified tenant identifier.
- Integrated `activate_and_validate_tenant` into all webhook endpoints:
  - `POST /api/v1/channels/webhooks/whatsapp/{tenant_id}`
  - `POST /api/v1/channels/webhooks/email/{tenant_id}`
  - `POST /api/v1/channels/webhooks/voice/{tenant_id}`
  - `POST /api/v1/channels/webchat/{tenant_id}/send`

### 3.2 Elimination of Post-Commit Refresh Crashes (P1-3 & P0-1)
In [src/backend/domains/conversations/service.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/service.py):
- Completely eliminated `await session.refresh(...)` after `await session.commit()`.
- Prior to commit, methods execute `await session.flush()` ensuring all database defaults, auto-generated IDs, and sequence values are populated on the instances.
- Because `AsyncSession` uses `expire_on_commit=False`, all object attributes remain safely accessible in memory after `await session.commit()` without issuing secondary unparameterized SQL queries that fail under RLS.
- Applied across all core methods: `ingest_raw_event`, `process_normalized_event`, `transfer_to_human`, `release_to_bot`, `post_ai_reply`, and `post_agent_reply`.

### 3.3 Transactional Outbox Worker Leasing, Concurrency & Stale Recovery (P1-1)
In [src/backend/domains/conversations/outbox.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/outbox.py), [infra/init-db.sql](file:///c:/Users/omar/Documents/Sales%20agent/infra/init-db.sql), and [src/backend/migrations/002_omnichannel_schema.sql](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/migrations/002_omnichannel_schema.sql):
- Extended `outbox_events` table with:
  ```sql
  ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS claimed_by VARCHAR(100);
  ALTER TABLE outbox_events ADD COLUMN IF NOT EXISTS claim_expires_at TIMESTAMPTZ;
  CREATE INDEX IF NOT EXISTS idx_outbox_claim ON outbox_events(status, claim_expires_at);
  ```
- Added `OutboxStatus.CANCELLED = "CANCELLED"` for revoked marketing messages.
- Updated `OutboxService.dispatch_pending_events()`:
  - Implements two-phase worker leasing:
    1. Selects candidate events that are either unclaimed (`claimed_by IS NULL`) or whose claim has expired (`claim_expires_at < now`).
    2. Uses `.with_for_update(skip_locked=True)` on PostgreSQL dialect, ensuring concurrent workers immediately skip rows locked by peers without blocking.
    3. Stamps `claimed_by = worker_id` and `claim_expires_at = now + lease_duration_seconds` within the transaction before executing external transport.
  - Added standing background worker daemon: `OutboxWorkerDaemon` with configurable poll interval, graceful stop (`stop()`), and single-pass iteration (`run_single_pass()`).

### 3.4 Regulatory STOP Opt-Out Cancellation & Pre-Dispatch Suppression (P1-2)
In [src/backend/domains/conversations/service.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/service.py) and [src/backend/domains/conversations/outbox.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/outbox.py):
- When `is_stop` directive is detected during `process_normalized_event()`:
  1. `ChannelIdentity.is_opted_out` is set to `True`.
  2. Queries all `PENDING` outbox events for that recipient and channel:
     ```python
     cancel_stmt = (
         update(OutboxEvent)
         .where(
             OutboxEvent.tenant_id == tenant_id,
             OutboxEvent.recipient_identifier == event.sender_identifier,
             OutboxEvent.channel_type == event.channel_type,
             OutboxEvent.status.in_([OutboxStatus.PENDING, OutboxStatus.PROCESSING]),
             OutboxEvent.is_high_priority.is_(False) # Preserve safety acknowledgements
         )
         .values(
             status=OutboxStatus.CANCELLED,
             last_error="Suppressed due to STOP opt-out directive",
             processed_at=datetime.now(timezone.utc)
         )
     )
     ```
  3. Records an immutable `AuditEvent` (`OUTBOX_MESSAGES_CANCELLED`).
  4. Enqueues high-priority `CONSENT_STOP_ACK` outranking routine traffic.
- Added pre-dispatch defense in `OutboxService.dispatch_pending_events()`: checks `ChannelIdentity.is_opted_out` before sending non-safety events, ensuring any race conditions are caught and suppressed prior to external dispatch.

### 3.5 Pessimistic Row Locking on Conversation Version Increments (P2-1)
In [src/backend/domains/conversations/service.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/service.py):
- When querying `Conversation` during inbound message processing:
  ```python
  if session.bind and session.bind.dialect.name == "postgresql":
      conv_stmt = conv_stmt.with_for_update()
  ```
- Prevents lost updates under concurrent webhook arrivals for the same conversation by serializing transactions at the database row level.

### 3.6 RBAC Authorization on Inbox Operations (P2-2)
In [src/backend/api/inbox.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/api/inbox.py) and [src/backend/core/policy_service.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/core/policy_service.py):
- Added conversation permissions to `policy_service.py`:
  - `conversations:read` (read inbox lists and message history)
  - `conversations:write` (post replies)
  - `conversations:handoff` (transfer between AI and human agents)
- Mapped permissions across staff roles: `platform_admin`, `tenant_admin`, `sales_manager`, `sales_representative`, `sales_rep`, and `support_agent`.
- Enforced on routes via `require_permission("conversations:handoff")` and `require_permission("conversations:write")`. Rejects `customer` tokens with `403 Forbidden`.

### 3.7 DOM XSS Elimination (P3-1)
In [src/frontend/inbox.html](file:///c:/Users/omar/Documents/Sales%20agent/src/frontend/inbox.html):
- Replaced insecure string concatenation in `renderBubble`:
  ```javascript
  // Before: bubble.innerHTML = `<div>${text}</div><div class="msg-meta">...</div>`;
  // After:
  const textNode = document.createElement('div');
  textNode.textContent = text; // Safe textContent avoids HTML execution
  bubble.appendChild(textNode);
  const metaNode = document.createElement('div');
  metaNode.className = 'msg-meta';
  metaNode.textContent = 'Just now • Karim Idrissi';
  bubble.appendChild(metaNode);
  ```

### 3.8 ORM Model Parity Alignment
In [src/backend/models/entities.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/models/entities.py):
- Aligned `AuditEvent` and `FeatureFlag` with PostgreSQL `init-db.sql`:
  ```python
  payload = Column("payload", JSON, nullable=True, default=dict)
  payload_json = synonym("payload")
  ```
  ```python
  rules = Column("rules", JSON, nullable=True, default=dict)
  rules_json = synonym("rules")
  ```
- Ensures both Python attribute styles (`payload` or `payload_json`) work interchangeably while emitting canonical column names (`payload`, `rules`) that match PostgreSQL 16 DDL exactly.

---

## 4. TEST EXECUTION EVIDENCE

### Full Test Suite Run
```powershell
$env:PYTHONPATH="."
python -m pytest tests/ -v --tb=short
```

**Results:**
- **Collected:** 145 items
- **Passed:** 145 (100%)
- **Failed:** 0
- **Errors:** 0
- **Warnings:** 2 (WindowsSelectorEventLoopPolicy deprecation notice on Python 3.14)
- **Duration:** 45.37 seconds
- **Exit Code:** 0
- **Evidence File:** `evidence/step-03-remediation/test_run.log`

### Live PostgreSQL 16 Integration Suite
```powershell
$env:PYTHONPATH="."
python -m pytest tests/integration/test_step03_real_postgres.py -v --tb=short
```

**Results:**
- `test_real_pg_webhook_ingest_rls_success_and_duplicates`: **PASSED** (Webhook RLS, 404 for inactive, deduplication)
- `test_real_pg_domain_operations_without_refresh_crash`: **PASSED** (Full 6-stage lifecycle on real PostgreSQL without refresh errors)
- `test_real_pg_outbox_skip_locked_concurrency`: **PASSED** (Concurrent workers using `SKIP LOCKED` claim disjoint batches)
- `test_real_pg_outbox_stale_claim_recovery`: **PASSED** (Stale worker claim recovered after lease expiration)
- `test_real_pg_stop_cancels_pre_queued_marketing_outbox`: **PASSED** (STOP directive cancels pre-queued marketing outbox records)
- `test_real_pg_outbox_pre_dispatch_opt_out_suppression`: **PASSED** (Outbox pre-dispatch guard blocks delivery to opted-out contacts)
- `test_real_pg_concurrent_inbound_bursts_version_serialization`: **PASSED** (Pessimistic row locking on version increments under burst)
- `test_real_pg_inbox_rbac_enforcement`: **PASSED** (RBAC enforcement: customer forbidden, sales rep permitted)
- `test_real_pg_standing_outbox_worker_daemon`: **PASSED** (Standing `OutboxWorkerDaemon` drains outbox in real-time)

### Canonical Database Parity Verification
```powershell
python scripts/verify_init_db_parity.py
```

**Output:**
```
1. Creating fresh isolated database 'fresh_parity_test_db'...
2. Initializing fresh database with infra/init-db.sql...
3. Querying catalog schemas and RLS definitions from both databases...

--- Canonical Parity Results ---
[PASS] All table columns and types match 100% across databases.
[PASS] Row-level security (ENABLE and FORCE RLS) matches 100% on all tables.
[PASS] RLS isolation policies match 100% on all tables.

SUCCESS: Canonical Database Parity Verified! infra/init-db.sql is 100% identical to active migration.
```

---

## 5. HARDWARE & LOCAL AI INVARIANTS

1. **Zero GPU VRAM Consumption:** Ingestion, deduplication, contact resolution, STOP regex detection, and outbox operations run entirely on the CPU.
2. **Mutual Exclusion Preserved:** Hardware configurations for `PRIMARY_LLM=qwen3.5:4b` and `REASONING_LLM=qwen3.5:9b-q4_K_M` remain untouched.
3. **No Active Voice Overhead:** Audio streaming and transcription are deferred to Step 10 in accordance with platform plan.

---

## 6. AUDIT CONCLUSION & NEXT STEPS

- All 7 audit findings (P0-1, P1-1, P1-2, P1-3, P2-1, P2-2, P3-1, P3-2) have been eliminated.
- Database parity is 100% verified.
- Full regression suite stands at 145/145 PASS.
- **STEP 04 REMAINS STRICTLY BLOCKED** until an independent Codex re-audit inspects this report, verifies the code changes and test suite, and issues an official PASS verdict.
