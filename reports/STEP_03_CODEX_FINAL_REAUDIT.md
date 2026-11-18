# INDEPENDENT CODEX RE-AUDIT REPORT: STEP 03 OMNICHANNEL CONVERSATIONS & INGESTION

**Project:** Sales AI Management Platform  
**Audited Commit:** `daa639f` (`fix(step-03): critical remediation for omnichannel durability, rls, outbox leasing, and inbox rbac`)  
**Auditor:** Independent Principal Application Security Auditor, PostgreSQL RLS Specialist, Distributed Systems Engineer & Senior QA Engineer  
**Date:** 2026-11-18  
**Previous Audit:** [reports/STEP_03_CODEX_INDEPENDENT_AUDIT.md](file:///c:/Users/omar/Documents/Sales%20agent/reports/STEP_03_CODEX_INDEPENDENT_AUDIT.md)  
**Remediation Report Under Audit:** [reports/STEP_03_REMEDIATION_REPORT.md](file:///c:/Users/omar/Documents/Sales%20agent/reports/STEP_03_REMEDIATION_REPORT.md)  
**Verdict:** **FAIL — REMEDIATION REQUIRED**  
**Step 04 Status:** **STRICTLY BLOCKED**  

---

## 1. EXECUTIVE SUMMARY

An independent re-audit of the STEP 03 critical remediation commit (`daa639f`) was performed against the live containerized environment (`sales-ai-postgres` on port 5432, Redis, MinIO, Ollama) and full application source code.

Gemini reported that all previous findings were resolved, citing **145/145 passing tests** and canonical database parity. While substantial architectural progress was made—specifically eliminating post-commit ORM crashes, implementing pessimistic `with_for_update(skip_locked=True)` on outbox rows, and enforcing RBAC on human inbox routes—**the remediation introduced two new Critical (P0) security vulnerabilities and one High (P1) logic flaw that compromise tenant isolation and transactional reliability on live PostgreSQL 16**:

1. **Critical Defect (P0) — Connection-Pool Tenant Context Leakage:**
   In [src/backend/api/channels.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/api/channels.py), `activate_and_validate_tenant()` executes `SELECT set_config('app.current_tenant_id', :tenant_id, false)`. The `false` flag sets `app.current_tenant_id` at the **session level** rather than transaction level. Because inbound webhooks bypass JWT middleware, `current_tenant_id_ctx` is empty upon entry, causing the `finally:` block in `get_db_session()` to skip executing `RESET app.current_tenant_id`. When the connection is returned to SQLAlchemy's connection pool, it **retains the previous tenant's identity**. Any subsequent unauthenticated or unparameterized query checking out that connection inherits full visibility and authority over that tenant's private data.
2. **Critical Defect (P0) — Cross-Tenant Injection via Route URL Parameter Swap:**
   The webhook router uses a single global platform secret (`settings.whatsapp_webhook_secret`) and extracts `tenant_id` purely from the route URL (`/webhooks/whatsapp/{tenant_id}`). `activate_and_validate_tenant()` checks only that the tenant exists and is active. It **never verifies** whether the inbound phone number ID or business account ID in the payload is registered to that tenant. An attacker or client possessing a valid WhatsApp signature for Tenant A can POST to Tenant B's URL (`/webhooks/whatsapp/{tenant_B}`) and inject spoofed customer conversations directly into Tenant B's inbox.
3. **High Severity (P1) — STOP Directive Indiscriminately Over-Cancels Transactional Outbox Messages:**
   In [src/backend/domains/conversations/service.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/service.py) and [src/backend/domains/conversations/outbox.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/outbox.py), detecting a STOP keyword cancels all `OutboxEvent` records where `is_high_priority == False`. Because `OutboxEvent` lacks message classification (`MARKETING` vs `TRANSACTIONAL`), legitimate non-marketing operational notices (such as order confirmations, payment receipts, shipment tracking updates, and agent support replies) are indiscriminately suppressed alongside promotional campaigns, violating contractual fulfillment requirements under Moroccan Law 09-08 and GDPR.
4. **Medium Severity (P2) — Premature In-Method Commits Invalidate Caller Unit-of-Work Rollbacks:**
   Every method in `ConversationService` (`process_normalized_event`, `ingest_raw_event`, `transfer_to_human`, `release_to_bot`, `post_ai_reply`, `post_agent_reply`) unilaterally executes `await session.commit()`. Callers cannot wrap multi-step operations in atomic units of work; if a failure occurs after `process_normalized_event` (e.g. updating `raw_event.processing_status = 'PROCESSED'`), the conversation version increment and customer message cannot be rolled back.

Consequently, STEP 03 **FAILS** the independent re-audit. **STEP 04 REMAINS STRICTLY BLOCKED.**

---

## 2. REVIEWED COMMIT & FILE INVENTORY

- **Audited Commit:** `daa639f8a1af4528d9793d46ec9cf8965a6c4a14`
- **Target Comparison Baseline:** Commit `66b8c3c` (original rejected Step 03 implementation)
- **Key Files Audited:**
  - `src/backend/api/channels.py`: Omnichannel webhook route handlers and `activate_and_validate_tenant`.
  - `src/backend/api/inbox.py`: Unified inbox endpoints and `require_permission` authorization.
  - `src/backend/core/database.py`: Session lifecycle, connection pool pre-ping, and `get_db_session`.
  - `src/backend/core/policy_service.py`: Role-to-permission catalog and permission checking.
  - `src/backend/domains/conversations/service.py`: Core conversation state machine, handoff, and STOP cancellation.
  - `src/backend/domains/conversations/outbox.py`: Outbox leasing, row locking, and `OutboxWorkerDaemon`.
  - `src/backend/models/entities.py`: SQLAlchemy entity models (`AuditEvent`, `FeatureFlag`, `OutboxEvent`).
  - `src/frontend/inbox.html`: Prototype unified inbox UI and DOM rendering.
  - `infra/init-db.sql`: Canonical database initialization DDL.
  - `src/backend/migrations/002_omnichannel_schema.sql`: Omnichannel schema migration.
  - `scripts/verify_init_db_parity.py`: Automated parity verification script.
  - `tests/integration/test_step03_real_postgres.py`: Real PostgreSQL integration test suite.

---

## 3. ORIGINAL FINDINGS VS. ACTUAL CORRECTIONS

| Original Finding | Original Severity | Remediation Claim | Actual Re-Audit Verdict | Status |
|---|---|---|---|---|
| **P0-1: Webhooks Fail Closed on PostgreSQL RLS** | Critical | Added `activate_and_validate_tenant()` calling `SELECT set_config('app.current_tenant_id', :tenant_id, false)` | Valid webhooks insert successfully, but using `false` (session-scoped) causes **connection-pool tenant context leakage** to subsequent requests. | **PARTIAL — NEW P0 INTRODUCED** |
| **P1-1: Outbox Dispatcher Lacks Row Locking** | High | Added `.with_for_update(skip_locked=True)`, worker leasing (`claimed_by`, `claim_expires_at`), and `OutboxWorkerDaemon` | Row locking works correctly; concurrent workers claim disjoint subsets. However, claims are held across external network calls without committing lease first. | **PASS WITH OBSERVATION** |
| **P1-2: STOP Does Not Cancel Pre-Queued Messages** | High | Marked all pending non-high-priority outbox events as `CANCELLED` and added pre-dispatch opt-out checks | Successfully blocks marketing messages, but **over-cancels legitimate transactional messages** (order confirmations, invoices, tracking updates). | **DEFECT (P1)** |
| **P1-3: Post-Commit `session.refresh()` Crashes** | High | Removed `await session.refresh(...)` after commit across all domain service methods; relied on `expire_on_commit=False` | Verified on live PostgreSQL. Domain lifecycle methods (`transfer_to_human`, `post_ai_reply`, etc.) execute without refresh errors. | **PASS** |
| **P2-1: Unlatched Conversation Inbound Bursts** | Medium | Added `.with_for_update()` on `Conversation` queries on PostgreSQL engines | Verified. Concurrent webhook bursts are serialized at the database row level without lost version increments. | **PASS** |
| **P2-2: Missing RBAC on Inbox Endpoints** | Medium | Added `conversations:read`, `conversations:write`, `conversations:handoff` permissions and enforced via `require_permission` | Verified. Authenticated `customer` tokens receive 403 Forbidden; staff roles (`sales_rep`, `sales_manager`) succeed. | **PASS** |
| **P3-1: Reflected DOM XSS in Inbox Frontend** | Low | Replaced `bubble.innerHTML = ...` with safe `textContent` DOM nodes in `src/frontend/inbox.html` | Verified. Injected HTML and script tags are treated as plain text; no script execution occurs. | **PASS** |
| **P3-2: Test Suite Relies on SQLite StaticPool** | Low | Created `tests/integration/test_step03_real_postgres.py` with 9 tests against live PostgreSQL container | 9 tests run against live PostgreSQL 16 container on port 5432 under `sales_app_user`. | **PASS** |

---

## 4. INDEPENDENT TEST EXECUTION RESULTS

The full regression test suite was executed independently against the clean working tree at commit `daa639f`:

```powershell
$env:PYTHONPATH="."
python -m pytest tests/ -v --tb=short
```

### Execution Outcome:
- **Total Tests Collected:** 145
- **Passed:** 145 (100%)
- **Failed:** 0
- **Duration:** 45.98 seconds
- **Exit Code:** 0

### Live PostgreSQL 16 Integration Results (`test_step03_real_postgres.py`):
```powershell
python -m pytest tests/integration/test_step03_real_postgres.py -v --tb=short
```
- `test_real_pg_webhook_ingest_rls_success_and_duplicates`: **PASSED**
- `test_real_pg_domain_operations_without_refresh_crash`: **PASSED**
- `test_real_pg_outbox_skip_locked_concurrency`: **PASSED**
- `test_real_pg_outbox_stale_claim_recovery`: **PASSED**
- `test_real_pg_stop_cancels_pre_queued_marketing_outbox`: **PASSED**
- `test_real_pg_outbox_pre_dispatch_opt_out_suppression`: **PASSED**
- `test_real_pg_concurrent_inbound_bursts_version_serialization`: **PASSED**
- `test_real_pg_inbox_rbac_enforcement`: **PASSED**
- `test_real_pg_standing_outbox_worker_daemon`: **PASSED**

**Audit Analysis of Test Suite:** While the 145 tests pass under isolated, happy-path test harness conditions, the test harness in `test_step03_real_postgres.py` creates fresh isolated engines per test or executes teardowns, concealing the connection-pool leakage and cross-tenant URL swap defects detailed below.

---

## 5. WEBHOOK AUTHENTICATION & TENANT ISOLATION FINDINGS

### 5.1 Critical Defect: Cross-Tenant Injection via Route URL Parameter Swap (Finding CRIT-01)
In [src/backend/api/channels.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/api/channels.py), lines 73–99:
```python
@router.post("/webhooks/whatsapp/{tenant_id}")
async def whatsapp_webhook_ingest(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    ...
    # 1. Cryptographic Signature Verification
    is_valid = whatsapp_adapter.verify_webhook_signature(
        headers=headers_dict,
        raw_body=raw_body,
        secret=settings.whatsapp_webhook_secret
    )
    ...
    # 2. Zero-Trust Tenant Validation & RLS Activation
    await activate_and_validate_tenant(db, tenant_id)
```

#### Vulnerability Analysis:
1. The platform configures a single global secret `settings.whatsapp_webhook_secret` across all tenants.
2. The router treats `{tenant_id}` as an untrusted path parameter.
3. `activate_and_validate_tenant()` performs a simple existence check:
   ```python
   stmt = select(Tenant).where(Tenant.id == tenant_id)
   res = await session.execute(stmt)
   tenant = res.scalars().first()
   if not tenant or not tenant.is_active:
       raise HTTPException(404, ...)
   ```
4. **Missing Identity Binding:** The router never inspects the payload's `phone_number_id`, `display_phone_number`, or WhatsApp Business Account ID to verify whether that provider asset is registered to or owned by `{tenant_id}`.
5. **Runtime Reproduction:**
   An adversary possessing a valid webhook payload and signature intended for `Tenant A` (containing Tenant A's customer messages and metadata) sent the payload to `/api/v1/channels/webhooks/whatsapp/{tenant_B}`.
   - **Observed Result:** FastAPI returned `200 OK {"status": "success", "processed_count": 1}`.
   - **Database Evidence:** PostgreSQL query `SELECT content FROM conversation_messages WHERE tenant_id = 'tenant_B'` confirmed that Tenant A's message was persisted into Tenant B's partition.
6. **Architectural Violation:** Violates AGENTS.md Invariant 4 (*"Zero-Trust Multi-Tenancy: Identity and tenant boundaries are established and verified server-side on every request. Never trust tenant IDs, actor IDs, or roles supplied in user prompts or client headers"*).

---

## 6. POSTGRESQL POOLED-CONNECTION ISOLATION EVIDENCE

### 6.1 Critical Defect: Connection-Pool Tenant Context Leakage (Finding CRIT-02)
In [src/backend/api/channels.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/api/channels.py), lines 44–50:
```python
    current_tenant_id_ctx.set(tenant_id)
    bind = session.bind or engine
    if bind and bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, false)"),
            {"tenant_id": str(tenant_id)}
        )
```

#### Vulnerability Analysis:
1. In PostgreSQL, `set_config(name, value, is_local)` controls variable scope. Setting `is_local = false` sets the variable at the **session/connection level**, meaning the setting persists beyond `COMMIT` and `ROLLBACK` until explicitly reset or disconnected.
2. In [src/backend/core/database.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/core/database.py), `get_db_session()` attempts to reset context in its `finally:` block:
   ```python
   async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
       active_tenant = current_tenant_id_ctx.get() # Evaluated upon entering generator
       async with AsyncSessionLocal() as session:
           ...
           try:
               yield session
               await session.commit()
           ...
           finally:
               if active_tenant and session.bind and session.bind.dialect.name == "postgresql":
                   await session.execute(text("RESET app.current_tenant_id"))
   ```
3. Because webhooks are unauthenticated endpoints that do not supply JWT tokens, `current_tenant_id_ctx.get()` is `None` when `get_db_session()` enters.
4. When `activate_and_validate_tenant()` sets `current_tenant_id_ctx.set(tenant_id)`, it updates the contextvar, but the local variable `active_tenant` in `get_db_session()` remains `None`.
5. Consequently, `if active_tenant:` evaluates to `False`, and `RESET app.current_tenant_id` **is never executed**.
6. When `session.close()` executes, the physical database connection is returned to SQLAlchemy's connection pool with `app.current_tenant_id = 'tenant-audit-A'`.

#### Runtime Reproduction Evidence:
Using a standard SQLAlchemy connection pool (`pool_size=1`, `max_overflow=0`) connected to `sales-ai-postgres`:
1. Request 1: POST to `/api/v1/channels/webhooks/whatsapp/tenant_A` -> Returned `200 OK`.
2. Request 2: An unauthenticated query checked out the connection from the pool without setting tenant context:
   ```python
   async with engine.connect() as conn:
       res_setting = await conn.execute(text("SELECT current_setting('app.current_tenant_id', true)"))
       print("Active setting:", res_setting.scalar())
       res_contacts = await conn.execute(text("SELECT id, display_name FROM contacts"))
       print("Visible contacts:", res_contacts.fetchall())
   ```
3. **Observed Output:**
   ```
   Active setting: 't_leak_a_1ee487'
   Visible contacts: [('c_private_a', 'Top Secret Contact A')]
   ```
4. **Conclusion:** Any subsequent query or worker checking out this connection operates with Tenant A's identity and reads Tenant A's private data, directly bypassing PostgreSQL Row-Level Security.

---

## 7. TRANSACTIONAL OUTBOX & CONCURRENCY FINDINGS

### 7.1 Row Locking and Worker Leasing
- **SKIP LOCKED:** Verified in [src/backend/domains/conversations/outbox.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/outbox.py). The query acquires `.with_for_update(skip_locked=True)` on PostgreSQL. Independent tests confirm that two concurrent worker sessions select strictly disjoint subsets without blocking.
- **Stale Claim Recovery:** Verified in `test_real_pg_outbox_stale_claim_recovery`. If a worker sets `claim_expires_at` in the past, another worker successfully reclaims the event.

### 7.2 Defect: Uncommitted Leases Across External HTTP Calls (Finding MED-01)
In [src/backend/domains/conversations/outbox.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/outbox.py), lines 158–184:
```python
    event.status = OutboxStatus.PROCESSING
    event.claimed_by = worker
    event.claim_expires_at = lease_expires
    await session.flush() # Flushed but NOT committed!

    if dispatcher_callable:
        result = await dispatcher_callable(event) # External network I/O
    ...
    if success:
        event.status = OutboxStatus.DELIVERED
    await session.commit() # Committed only after external network call completes!
```
#### Impact:
1. **Connection Pool Starvation:** The database transaction and exclusive row lock are held open for the entire duration of the external provider HTTP call. If the provider is slow or times out (e.g. 15–30 seconds), database connections are exhausted.
2. **Two-Phase Lease Invisibility:** Because the claim update is flushed but not committed, other database sessions operating under PostgreSQL's default `READ COMMITTED` isolation level never see `status = 'PROCESSING'`. They skip the row purely because of the physical row lock. If the worker process crashes during dispatch, PostgreSQL automatically aborts the transaction, reverting the row to `PENDING` on disconnect. The `claim_expires_at` logic is therefore largely decorative because `PROCESSING` is never committed as an observable intermediate state.

---

## 8. STOP DIRECTIVE & OUTBOUND CONSENT FINDINGS

### 8.1 Multilingual STOP Engine
- Correctly parses multilingual opt-out directives across English (`stop`), French (`arret`, `desabonner`), Arabic (`حبس`, `وقف`), and Moroccan Darija/Arabizi (`baraka`, `safii baraka`, `7bes`, `stoppi 3afak`).
- Successfully marks `ChannelIdentity.is_opted_out = True` and writes an immutable `AuditEvent` (`CONSENT_OPT_OUT`).

### 8.2 Defect: Indiscriminate Over-Cancellation of Legitimate Transactional Messages (Finding HIGH-01)
In [src/backend/domains/conversations/service.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/service.py), lines 254–260:
```python
    pending_outbox_stmt = select(OutboxEvent).where(
        OutboxEvent.tenant_id == event.tenant_id,
        OutboxEvent.channel_type == event.channel_type,
        OutboxEvent.recipient_identifier == event.sender_identifier,
        OutboxEvent.status.in_(["PENDING", "FAILED"]),
        OutboxEvent.is_high_priority == False
    )
```
And in [src/backend/domains/conversations/outbox.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/outbox.py), lines 140–155:
```python
    if not event.is_high_priority:
        ...
        if identity and identity.is_opted_out:
            event.status = OutboxStatus.CANCELLED
            event.last_error = "Suppressed: recipient has opted out (STOP directive)"
```

#### Impact Analysis:
1. `OutboxEvent` does not categorize events by commercial classification (e.g. `MARKETING` vs `TRANSACTIONAL`).
2. Only `CONSENT_STOP_ACK` and emergency alerts are created with `is_high_priority = True`.
3. Standard operational business events—including **Order Confirmations**, **Payment Invoices / Receipts**, **Delivery Tracking Updates**, **Password Reset / MFA Tokens**, and **Human Support Replies**—default to `is_high_priority = False`.
4. When a user sends a STOP keyword to halt marketing campaigns, all pre-queued and retrying transactional notifications are permanently cancelled with status `CANCELLED`.
5. **Regulatory / Contractual Conflict:** Opting out of commercial marketing communications does not void an existing commercial sales contract. Cancelling paid order receipts or shipping tracking notices violates consumer protection laws and standard enterprise commerce invariants.

---

## 9. CONVERSATION TRANSACTION SAFETY FINDINGS

### 9.1 Stale AI Turn Rejection
- Verified. In [src/backend/domains/conversations/service.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/service.py), `post_ai_reply()` checks `IF conv.version != expected_version: RAISE StaleTurnError`.
- Tested against live PostgreSQL: when an inbound customer message intervenes and increments the conversation version from 1 to 2, a background AI turn submitting with `expected_version=1` is rejected with `StaleTurnError`.

### 9.2 Defect: Premature In-Method Commits Invalidate Unit of Work (Finding MED-02)
- In `ConversationService`, every method (`process_normalized_event`, `transfer_to_human`, `release_to_bot`, `post_ai_reply`, `post_agent_reply`) terminates with:
  ```python
  await session.flush()
  await session.commit()
  return entity
  ```
- **Consequence:** Domain service methods commit transactions unilaterally. Callers cannot orchestrate multi-step atomic operations. If a caller performs Step 1 (`process_normalized_event`) and encounters an error during Step 2 (e.g. updating `InboundRawEvent.processing_status = 'PROCESSED'`), Step 1 cannot be rolled back because it was already committed.

---

## 10. INBOX AUTHORIZATION & FRONTEND SECURITY FINDINGS

### 10.1 Role-Based Access Control (RBAC)
- Verified. [src/backend/core/policy_service.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/core/policy_service.py) defines explicit permissions:
  - `conversations:read`
  - `conversations:write`
  - `conversations:handoff`
- Mapped to staff roles: `platform_admin`, `tenant_admin`, `sales_manager`, `sales_representative`, `sales_rep`, and `support_agent`.
- The `customer` role holds only self-service permissions (`orders:read_self`, `portal:access`) and lacks all conversation staff permissions.
- In [src/backend/api/inbox.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/api/inbox.py), endpoints enforce `require_permission()`. Calling `/handoff` or `/reply` with a `customer` JWT token returns `403 Forbidden`.

### 10.2 Client-Side DOM XSS Assessment
- In [src/frontend/inbox.html](file:///c:/Users/omar/Documents/Sales%20agent/src/frontend/inbox.html), the previous vulnerable `bubble.innerHTML = ...` assignment was replaced with:
  ```javascript
  const contentDiv = document.createElement('div');
  contentDiv.textContent = text;
  bubble.appendChild(contentDiv);
  ```
- Tested: injecting `<img src=x onerror=alert(1)>` renders safely as literal text nodes; no script execution occurs in the browser.

---

## 11. CANONICAL SCHEMA PARITY FINDINGS

Independent execution of [scripts/verify_init_db_parity.py](file:///c:/Users/omar/Documents/Sales%20agent/scripts/verify_init_db_parity.py) against live PostgreSQL 16 container:
```
--- Canonical Parity Results ---
[PASS] All table columns and types match 100% across databases.
[PASS] Row-level security (ENABLE and FORCE RLS) matches 100% on all tables.
[PASS] RLS isolation policies match 100% on all tables.

SUCCESS: Canonical Database Parity Verified! infra/init-db.sql is 100% identical to active migration.
```

### Deep Catalog Parity Analysis:
A secondary custom catalog query was executed to inspect properties not validated by the script (primary keys, foreign keys, unique constraints, and indexes):
- `Constraints diff count: 0`
- `Indexes diff count: 0`
- All 13 tenant tables and 4 reference tables in `infra/init-db.sql` match `sales_ai_db` with 100% parity.

---

## 12. SECURITY CONTROL TRACEABILITY

| Control ID | Category | Level | Required Invariant | Remediation Audit Assessment |
|---|---|---|---|---|
| **Control 16** | Input Validation | P0 | Reject invalid payloads and tenant contexts | **FAIL:** Webhook accepts unverified `tenant_id` from route URL without validating provider asset ownership. |
| **Control 20/23** | SSRF & Webhooks | P0 | Validate webhook HMAC and media URLs | **PASS:** `X-Hub-Signature-256` HMAC-SHA256 verified; anti-SSRF IP filtering verified. |
| **Control 31** | Webhook Signatures | P0 | Cryptographic signature verification before ingestion | **PASS:** Missing or invalid signatures return 401 Unauthorized. |
| **Control 33** | IDOR / BOLA | P0 | Tenant boundary enforcement on all entity access | **PASS:** `/inbox` routes filter strictly by `context.tenant_id`. |
| **Control 41** | Multi-Tenancy RLS | P0 | Zero-trust isolation enforced by PostgreSQL RLS | **FAIL:** Connection pool retains `app.current_tenant_id` session setting, leaking tenant context to subsequent pooled connections. |
| **Control 57/58** | Race Conditions | P0 | Pessimistic locking on version increments & outbox | **PASS:** `with_for_update(skip_locked=True)` on outbox; `with_for_update()` on conversation bursts. |
| **Control 59** | Webhook Replay | P0 | Unique provider event constraint | **PASS:** Replayed WAMIDs return `duplicate_ignored` with 0 side effects. |
| **SAI-11** | Human Handoff | P1 | Silences AI upon human takeover; deterministic opt-out | **PARTIAL:** Atomic handoff and regex STOP detection pass; however, STOP over-cancels legitimate transactional notifications. |

---

## 13. VERIFIED FINDINGS BY SEVERITY

### Critical (P0) — Launch Blockers
1. **FINDING CRIT-01 (Cross-Tenant Webhook URL Swap):** Inbound webhooks accept `tenant_id` from the URL without verifying that the provider's phone number or account identity belongs to that tenant. A valid webhook from Tenant A can inject customer messages into Tenant B.
2. **FINDING CRIT-02 (Connection-Pool Tenant Context Leakage):** `channels.py` calls `SELECT set_config('app.current_tenant_id', :tenant_id, false)` which sets session-level configuration on the PostgreSQL connection. Because webhooks bypass JWT, `get_db_session()` skips the `RESET` query, returning a contaminated connection to the pool that leaks Tenant A's identity to subsequent requests.

### High (P1) — Commerce & Compliance Defect
3. **FINDING HIGH-01 (STOP Directive Over-Cancellation):** The STOP handler cancels all `is_high_priority == False` outbox events indiscriminately. Legitimate transactional notices (order confirmations, paid invoices, tracking updates) are improperly cancelled alongside marketing messages.

### Medium (P2) — Distributed Systems & Concurrency Gaps
4. **FINDING MED-01 (Outbox Transaction Held Open Across HTTP Calls):** `OutboxService.dispatch_pending_events()` holds an open database transaction while executing `dispatcher_callable()`. Slow or failing external network I/O risks exhausting database connections.
5. **FINDING MED-02 (Premature Domain Service Commits):** Domain service methods in `ConversationService` commit transactions internally, preventing callers from orchestrating atomic multi-step operations or rolling back partial failures.

---

## 14. MANDATORY REMEDIATION CHECKLIST

To achieve a PASS verdict and unlock Step 04, the engineering team must execute the following remediations:

1. **Fix Connection-Pool Leakage in `channels.py` and `database.py` (CRIT-02):**
   - In `channels.py`, replace `set_config('app.current_tenant_id', :tenant_id, false)` with transaction-scoped context:
     ```python
     await session.execute(text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_id)})
     ```
   - In `database.py`, update `get_db_session()`'s `finally:` block to ALWAYS execute `RESET app.current_tenant_id` regardless of whether `active_tenant` was populated at entry.
2. **Bind Provider Account Identity to Tenant (CRIT-01):**
   - In `channels.py`, verify that the inbound provider asset identifier (e.g. `entry[0].changes[0].value.metadata.phone_number_id` or recipient phone/email) matches the tenant's configured channel credentials or organization sites before permitting ingestion into that tenant.
   - Do not trust `{tenant_id}` path parameter alone.
3. **Differentiate Marketing vs. Transactional Messages on STOP (HIGH-01):**
   - In `OutboxEvent` and `service.py`, add message classification (e.g. `is_marketing: bool` or `message_class: str`).
   - When STOP is detected, cancel ONLY promotional/marketing events. Legitimate transactional events (order confirmations, invoices, tracking updates) must remain active and deliverable.
4. **Release Database Transactions Before External Network Calls (MED-01):**
   - In `OutboxService`, commit the `status = 'PROCESSING'` lease claim to the database *before* calling `dispatcher_callable()`.
   - Update the status to `DELIVERED` or `FAILED` in a separate transaction upon return.
5. **Decouple Commit Authority from Domain Service Methods (MED-02):**
   - Remove internal `await session.commit()` calls from `ConversationService` methods; allow callers and FastAPI dependencies to control transaction commit boundaries.

---

## 15. REMAINING UNVERIFIED FUNCTIONALITY

1. **Meta WhatsApp Cloud API Live Delivery:** Webhook tests use cryptographic HMAC-SHA256 fixtures; live delivery to Meta Graph API endpoints is deferred to staging (Step 12).
2. **Live Voice Audio Transcription:** ASR/TTS streaming is deferred to Step 10 in accordance with platform plan.

---

## 16. FINAL VERDICT

In accordance with strict acceptance criteria (*"STEP 03 must not receive unconditional PASS if: Webhook tenant identity can be forged; Tenant context leaks across pooled database connections; Mandatory PostgreSQL tenant isolation fails; STOP allows prohibited marketing delivery"*):

### **FINAL VERDICT: FAIL — REMEDIATION REQUIRED**

**Reasoning:**  
While previous ORM crashes and inbox RBAC gaps were resolved, the remediation introduced a critical connection-pool leakage vulnerability (CRIT-02) and an authenticated cross-tenant injection vulnerability via URL manipulation (CRIT-01), alongside indiscriminate over-cancellation of legitimate transactional messages (HIGH-01).

---

## 17. EXPLICIT STEP 04 ELIGIBILITY DECISION

### **STEP 04 IS STRICTLY BLOCKED.**

Engineering must resolve CRIT-01, CRIT-02, and HIGH-01 before requesting another independent re-audit. No features from Step 04 may be started until STEP 03 achieves an unconditional PASS.
