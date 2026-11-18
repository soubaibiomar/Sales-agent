# INDEPENDENT AUDIT REPORT: STEP 03 OMNICHANNEL CONVERSATIONS & INGESTION

**Project:** Sales AI Management Platform  
**Audited Commit:** `66b8c3c`  
**Auditor:** Independent Principal Distributed Systems Engineer, Application Security Auditor, PostgreSQL Architect & Senior QA Engineer  
**Date:** 2026-11-18  
**Verdict:** **FAIL — REMEDIATION REQUIRED**  
**Step 04 Status:** **STRICTLY BLOCKED**  

---

## 1. EXECUTIVE SUMMARY

Gemini reported completing **STEP 03** at commit `66b8c3c`, citing **136/136 passing tests** in 47.45 seconds.

An exhaustive, adversarial audit of the codebase, live PostgreSQL 16 container, SQLite test harness, and domain services was conducted. While the conceptual architecture and component design represent substantial engineering effort—including normalized channel adapters, multilingual STOP detection, anti-SSRF guards, and a transactional outbox schema—**the implementation exhibits critical architectural defects that fail on live PostgreSQL with Row-Level Security (RLS) enabled**:

1. **Critical Defect (P0): Inbound Webhook Handlers Fail Closed on PostgreSQL Under RLS:**
   In [src/backend/api/channels.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/api/channels.py), webhook routes (`/webhooks/whatsapp/{tenant_id}`, `/webhooks/email/{tenant_id}`, `/webhooks/voice/{tenant_id}`) do not set `app.current_tenant_id` on the database session before persisting raw events. On real PostgreSQL 16 where `inbound_raw_events` enforces RLS, all inbound webhooks crash with `psycopg.errors.InsufficientPrivilege: new row violates row-level security policy for table "inbound_raw_events"`.
2. **High Severity (P1): `ConversationService` Post-Commit `session.refresh()` Fails on PostgreSQL:**
   Throughout [src/backend/domains/conversations/service.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/service.py), methods execute `await session.commit()` followed by `await session.refresh(instance)`. Because `set_config('app.current_tenant_id', ..., true)` is transaction-local, committing ends the transaction and clears the tenant context. The subsequent `session.refresh()` queries in a new unparameterized transaction where RLS blocks row visibility, raising `sqlalchemy.exc.InvalidRequestError: Could not refresh instance`.
3. **High Severity (P1): STOP Opt-Out Does Not Cancel Pre-Queued Outbound Messages:**
   When a customer submits a STOP directive, `ChannelIdentity.is_opted_out` is set to `True` and a `CONSENT_STOP_ACK` is enqueued with high priority. However, already-queued `PENDING` outbox messages (e.g., promotional campaigns or follow-ups) are not cancelled. The outbox dispatcher sends the STOP confirmation and subsequently delivers the promotional message to the opted-out customer.
4. **High Severity (P1): Outbox Dispatcher Lacks Concurrency Row Locking (`SKIP LOCKED`):**
   In [src/backend/domains/conversations/outbox.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/outbox.py), `dispatch_pending_events` queries pending events with a plain `SELECT` without `.with_for_update(skip_locked=True)`. Multiple worker replicas will claim and dispatch the exact same events simultaneously, causing duplicate outbound deliveries.
5. **Masking of Defects via SQLite Test Harness:**
   The API contract test suite (`test_inbox_and_channel_apis.py`) ran exclusively against in-memory SQLite with `StaticPool`, which completely lacks Row-Level Security and transaction-local variables. This masked the webhook insertion failure and the post-commit refresh crashes.

Consequently, STEP 03 **FAILS** independent audit acceptance criteria. STEP 04 is **STRICTLY BLOCKED** until all findings are remediated and verified on live PostgreSQL.

---

## 2. REVIEWED COMMIT & FILE INVENTORY

- **Target Commit:** `66b8c3c` (`feat(step03): finalize transactional outbox, DLQ, out-of-order ingestion, canonical DB parity, and validation suite`)
- **Key Files Audited:**
  - `infra/init-db.sql`: Canonical database initialization DDL.
  - `src/backend/migrations/002_omnichannel_schema.sql`: Omnichannel schema migration.
  - `src/backend/models/entities.py`: SQLAlchemy ORM entity mappings.
  - `src/backend/core/media_security.py`: Anti-SSRF URL validator and MIME filter.
  - `src/backend/integrations/base.py`: Channel adapter interfaces and event dataclasses.
  - `src/backend/integrations/whatsapp.py`: WhatsApp Cloud API webhook adapter.
  - `src/backend/integrations/email.py`: Email/Gmail inbound normalizer.
  - `src/backend/integrations/webchat.py`: WebChat widget adapter.
  - `src/backend/integrations/voice_sip.py`: Voice/SIP signaling adapter.
  - `src/backend/domains/conversations/service.py`: `ConversationService` core domain logic.
  - `src/backend/domains/conversations/outbox.py`: `OutboxService` transactional outbox and DLQ.
  - `src/backend/api/channels.py`: FastAPI channel webhook routers.
  - `src/backend/api/inbox.py`: Unified inbox API routes.
  - `src/frontend/inbox.html`: Sales Workspace HTML/JS interface.
  - `scripts/apply_omnichannel_migration.py`: Live migration runner.
  - `scripts/verify_init_db_parity.py`: Schema and RLS parity verifier.
  - `tests/`: Multi-tier test suite across unit, contract, concurrency, security, and integration tests.

---

## 3. ORIGINAL ACCEPTANCE CONTRACT COVERAGE

| Contract Requirement | Gemini Claim | Audit Finding | Status |
|---|---|---|---|
| **Durable Ingest Before Debounce** | Persists raw envelopes to `inbound_raw_events` before routing | Implemented in code, but fails on live PostgreSQL due to missing tenant context in `channels.py` | **DEFECT (P0)** |
| **Monotonic Conversation Versioning** | Monotonically increments version on every turn | Implemented in memory; lacks row locks for simultaneous concurrent bursts | **DEFECT (P2)** |
| **Atomic Human Takeover** | Silences AI (`is_ai_silenced=True`) and rejects stale turns with `StaleTurnError` | Verified. `post_ai_reply` enforces version match and non-silenced state | **PASS** |
| **Deterministic Multilingual STOP** | 4-language regex matrix outranks LLM and records audit event | Regex engine verified. Pre-queued outbound messages are not purged upon STOP | **DEFECT (P1)** |
| **Transactional Outbox & DLQ** | Enqueues outbound events atomically with backoff and DLQ | Service implemented; lacks `SKIP LOCKED` concurrency protection and standing worker | **DEFECT (P1)** |
| **Zero-Trust Multi-Tenancy RLS** | All tables protected with forced RLS in PostgreSQL | Forced RLS verified on 13 tables; webhook routes fail closed due to missing context | **DEFECT (P0)** |
| **Anti-SSRF Media Protection** | Blocks loopback, private, link-local, and non-HTTP IPs | Verified in `media_security.py` and security tests | **PASS** |
| **Unified Sales Workspace Inbox** | Responsive HTML interface with design tokens | UI layout verified; contains reflected DOM XSS in message bubble injection | **DEFECT (P3)** |

---

## 4. ACTUAL INDEPENDENT TEST RESULTS

The reported test suite was executed independently using:
```powershell
$env:PYTHONPATH="."
python -m pytest tests/ -v --tb=short
```

### Execution Summary
- **Total Test Cases Executed:** 136
- **Passed:** 136 (100%)
- **Failed / Errors:** 0
- **Duration:** 44.70 seconds
- **Exit Code:** 0

### Breakdown by Test Category
| Category | Test Modules | Tests | Execution Substrate | Evaluation |
|---|---|---|---|---|
| **Unit Tests** | `test_deterministic_stop.py`, `test_multilingual_matrix.py`, `test_local_ai_constraints.py`, `test_ai_concurrency_and_failures.py` | 43 | Pure Python / In-Memory | Solid coverage of regex and model rules. |
| **Contract Tests** | `test_channel_adapters.py`, `test_outbox_and_dlq.py`, `test_out_of_order_messages.py` | 16 | SQLite in-memory | **Masks PostgreSQL RLS behavior.** |
| **API Contract Tests** | `test_inbox_and_channel_apis.py` | 4 | SQLite with `StaticPool` | **Masks RLS failure on webhook endpoints.** |
| **Concurrency Tests** | `test_conversation_races.py` | 4 | SQLite in-memory | **Sequential for-loop; no true concurrency.** |
| **Security Tests** | `test_channel_security.py`, `test_ai_model_governance.py`, `test_auth_and_rbac.py` | 32 | SQLite / Mocked Sessions | Good parameter bounds; mocked DB layer. |
| **PostgreSQL Integration** | `test_omnichannel_rls.py`, `test_postgres_rls.py` | 12 | Live PostgreSQL 16 container | Real RLS tested with raw SQL; bypassed domain ORM services. |
| **Step 01 Regression** | `tests/step01/` | 25 | File / Spec Assertions | All architectural traceability tests pass. |

**Audit Conclusion on Tests:** The 136 passing tests represent a misleading safety signal because the domain services (`ConversationService`, `channels.py`) were never executed against the live PostgreSQL 16 container with RLS active; only raw SQL scripts were tested against PostgreSQL.

---

## 5. POSTGRESQL SCHEMA AND RLS FINDINGS

### 5.1 Catalog Verification
Catalog inspection of `sales-ai-postgres` on `127.0.0.1:5432` confirmed 17 total tables in the `public` schema:
- **13 Tenant-Partitioned Tables (RLS Enabled and Forced):**
  `audit_logs`, `channel_identities`, `contacts`, `conversation_messages`, `conversations`, `feature_flags`, `inbound_raw_events`, `message_attachments`, `organization_sites`, `outbox_events`, `session_revocations`, `user_roles`, `users`.
- **4 Global Reference Tables (No RLS):**
  `tenants`, `roles`, `permissions`, `role_permissions`.

### 5.2 Policy Definitions & Parity
All 13 tenant tables utilize consistent permissive policies:
```sql
CREATE POLICY tenant_isolation_<table_name> ON <table_name>
    AS PERMISSIVE FOR ALL TO PUBLIC
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
```
Execution of [scripts/verify_init_db_parity.py](file:///c:/Users/omar/Documents/Sales%20agent/scripts/verify_init_db_parity.py) confirmed 100% equivalence in columns, nullability, data types, and RLS policies between `infra/init-db.sql` and the active database.

### 5.3 Live PostgreSQL Execution Failure (Finding P0-1)
Direct execution of `ConversationService.process_normalized_event()` against live PostgreSQL 16 under `sales_app_user` revealed a fatal flaw:
```python
# service.py, line 342-344
await session.commit()
await session.refresh(msg)
```
In PostgreSQL, setting `set_config('app.current_tenant_id', :tenant_id, true)` applies strictly to the current transaction. When `session.commit()` executes, the transaction ends and `app.current_tenant_id` resets. When `session.refresh(msg)` immediately follows, it opens a new transaction where `app.current_tenant_id` is empty. RLS forces row visibility to 0, causing SQLAlchemy to raise:
`sqlalchemy.exc.InvalidRequestError: Could not refresh instance '<ConversationMessage>'`

---

## 6. TRANSACTIONAL OUTBOX AND DLQ FINDINGS

### 6.1 Atomicity & Guarantees
- **Atomic Enqueue:** `OutboxService.enqueue_outbound_event()` is called within the same `session` as `ConversationMessage` creation before `await session.commit()`. If the transaction rolls back, both message and outbox event are discarded.
- **Delivery Guarantee:** The service provides **at-least-once delivery** (re-attempts external calls if errors occur). It does **not** provide exactly-once external delivery.

### 6.2 Missing Concurrency Row Locking (Finding P1-1)
In [src/backend/domains/conversations/outbox.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/domains/conversations/outbox.py), lines 82–93:
```python
stmt = (
    select(OutboxEvent)
    .where(
        OutboxEvent.status.in_([OutboxStatus.PENDING, OutboxStatus.FAILED]),
        OutboxEvent.next_retry_at <= current_time
    )
    .order_by(
        OutboxEvent.is_high_priority.desc(),
        OutboxEvent.created_at.asc()
    )
    .limit(limit)
)
```
Without `.with_for_update(skip_locked=True)`, multiple worker processes polling the outbox will select the exact same events, resulting in duplicate external dispatches.

### 6.3 Missing Outbox Worker Daemon
While `OutboxService.dispatch_pending_events()` exists and is tested via contract tests, there is no standing background process (e.g., daemon or cron) actively polling or draining the outbox in the running application.

---

## 7. CONVERSATION RACE AND VERSIONING FINDINGS

### 7.1 Monotonic Versioning
- Conversations maintain an integer `version` incremented on every inbound message and human handoff.
- In `ConversationService.post_ai_reply()`, line 466 enforces `IF conv.version != expected_version: RAISE StaleTurnError`.
- If an out-of-order message or human handoff occurs during AI generation, `conv.version` advances, causing subsequent AI reply attempts to be rejected.

### 7.2 Concurrency Gap on Concurrent Inbound Bursts (Finding P2-1)
In `ConversationService.process_normalized_event()`, line 229:
```python
conv_stmt = select(Conversation).where(...)
```
The conversation row is read without pessimistic locking (`with_for_update()`). In a true concurrent arrival of two webhooks for the same conversation across separate database connections, both will read `conv.version = 1`, and both will increment to `2`, overwriting each other's version increments. In `tests/concurrency/test_conversation_races.py`, `test_inbound_burst_handling` tested events sequentially in a `for` loop on a single session, masking this concurrency race.

---

## 8. STOP, CONSENT & SAFETY FINDINGS

### 8.1 Multilingual STOP Engine
- Evaluates inbound messages against compiled regexes covering English (`stop`, `unsubscribe`), French (`arret`, `desabonner`), Standard Arabic (`حبس`, `وقف`, `إلغاء`), and Moroccan Darija/Arabizi (`baraka`, `safii baraka`, `stoppi`, `7bes`).
- Verified across 18 test cases in `test_deterministic_stop.py`.
- Correctly sets `ChannelIdentity.is_opted_out = True`, `opt_out_at = now`, writes an `AuditEvent` (`CONSENT_OPT_OUT`), and sets `Conversation.is_ai_silenced = True`.

### 8.2 Pre-Queued Marketing Message Leakage (Finding P1-2)
When a customer sends STOP:
- A high-priority `CONSENT_STOP_ACK` is enqueued to `outbox_events`.
- However, existing `PENDING` outbox records for that recipient are **not cancelled or suppressed**.
- In `OutboxService.dispatch_pending_events()`, the dispatcher sends the STOP confirmation first, but then dispatches the remaining pending promotional events to the opted-out customer.

---

## 9. CHANNEL ADAPTER SECURITY FINDINGS

| Adapter | Status Classification | Webhook Auth / Signature | Anti-SSRF Defense | XSS Sanitization | Provider Evt Deduplication |
|---|---|---|---|---|---|
| **WhatsApp** | Locally Simulated & Tested | `X-Hub-Signature-256` HMAC-SHA256 | Validated via `validate_media_url()` | Plaintext extraction | Unique `(tenant_id, channel, provider_event_id)` |
| **Email** | Locally Simulated & Tested | Bearer Token in Auth Header | URL structure parsing | Stored XSS stripped (`sanitize_content()`) | Message-ID extraction |
| **WebChat** | Locally Simulated & Tested | Shared token (`X-WebChat-Token`) | Relative/URL storage paths | None (Relies on client rendering) | UUID generation |
| **Voice/SIP** | Locally Simulated & Tested | Substring secret check | N/A (Signaling only) | Plain text signaling | Call-ID + Event mapping |

**Assessment:** None of the adapters are verified against live external commercial APIs (Meta WhatsApp Cloud API or live Gmail SMTP/IMAP). They are classified as **Locally Simulated and Tested**.

---

## 10. API AND FRONTEND SECURITY FINDINGS

### 10.1 Webhook Missing Tenant Context (Finding P0-1)
In [src/backend/api/channels.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/api/channels.py), lines 47–97:
```python
@router.post("/webhooks/whatsapp/{tenant_id}")
async def whatsapp_webhook_ingest(
    tenant_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
...
    raw_event = await ConversationService.ingest_raw_event(
        session=db,
        tenant_id=tenant_id,
        channel_type="WHATSAPP",
        provider_event_id=provider_event_id,
        payload_dict=payload,
        signature_verified=True
    )
```
`get_db_session()` only sets `app.current_tenant_id` if `current_tenant_id_ctx.get()` is populated. Because webhook endpoints bypass JWT authentication, `current_tenant_id_ctx` is empty. The handler never invokes `SELECT set_config('app.current_tenant_id', :tenant_id, true)`. Under PostgreSQL RLS, the database rejects the insert with `InsufficientPrivilege`.

### 10.2 Missing RBAC on Human Inbox Operations (Finding P2-2)
In [src/backend/api/inbox.py](file:///c:/Users/omar/Documents/Sales%20agent/src/backend/api/inbox.py), `/conversations/{id}/handoff` and `/conversations/{id}/reply` check that the user is authenticated via JWT, but do not check whether `context.roles` contains a sales/agent role. An authenticated user with role `customer` in that tenant can post replies as an `AGENT`.

### 10.3 DOM XSS Vulnerability in Prototype Frontend (Finding P3-1)
In [src/frontend/inbox.html](file:///c:/Users/omar/Documents/Sales%20agent/src/frontend/inbox.html), line 649:
```javascript
bubble.innerHTML = `<div>${text}</div><div class="msg-meta">Just now • Karim Idrissi</div>`;
```
`text` is taken directly from the textarea input without escaping, allowing arbitrary HTML/JavaScript execution in the browser.

---

## 11. INFRASTRUCTURE & FAILURE RECOVERY

- **Active Containers Verified:** PostgreSQL 16.1 (`sales-ai-postgres`), Redis 7.2.4 (`sales-ai-redis`), MinIO (`sales-ai-minio`), and Ollama (`ollama`) are healthy on ports 5432, 6379, 9000, and 11434.
- **Transaction Rollback:** Tested and confirmed. Database rollbacks cleanly revert uncommitted contacts and conversation records.
- **Container Hygiene:** No volumes, containers, or host data were destroyed or altered during the audit.

---

## 12. HARDWARE & MODEL GOVERNANCE

- **Zero LLM Overhead for Ingestion:** Inbound webhook normalization, deduplication, contact resolution, STOP regex detection, and outbox operations execute deterministically on the CPU without invoking Ollama or consuming GPU VRAM.
- **Hardware Profile Invariants:** Step 01 and Step 02 model governance configurations (`PRIMARY_LLM=qwen3.5:4b`, `REASONING_LLM=qwen3.5:9b-q4_K_M`, 4096-token 9B limit, CPU auxiliaries) remain preserved.

---

## 13. SECURITY CONTROL TRACEABILITY

Cross-referencing `references/70-security.xlsx` and `security/control-mapping.md`:
- **Control 16 (Missing input validation):** Partially met. MIME and schema validation active, but `channels.py` lacks tenant existence validation.
- **Control 20/23 (SSRF & Webhook Security):** Met. `validate_media_url()` rejects private and metadata subnets.
- **Control 33 (IDOR / BOLA):** Met in `/inbox` endpoints via `where(Conversation.tenant_id == context.tenant_id)`.
- **Control 35 (Sensitive Data in Logs):** Met via `redact_pii()`.
- **Control 57/58 (Business Logic Abuse & Race Conditions):** Partially met. Monotonic versioning guards AI turns, but unhandled outbox marketing races on STOP and unlatched concurrent inbound bursts exist.
- **Control 59 (Webhook Replay):** Met. Unique database constraint rejects duplicates.
- **SAI-11 (Multilingual STOP & Human Takeover):** Partially met. Regex detection verified; outbox purge on STOP missing.

---

## 14. CRITICAL / HIGH / MEDIUM / LOW FINDINGS

### Critical (P0) — Launch Blockers
- **FINDING P0-1:** Inbound webhook endpoints in `src/backend/api/channels.py` fail with `InsufficientPrivilege` on real PostgreSQL because they do not establish `app.current_tenant_id` before querying/inserting.

### High (P1) — Security & Durability Defects
- **FINDING P1-1:** `OutboxService.dispatch_pending_events()` lacks `with_for_update(skip_locked=True)`, creating duplicate dispatch races when scaled to multiple workers.
- **FINDING P1-2:** STOP directives do not cancel or suppress pre-queued `PENDING` outbox messages, leading to regulatory violations where marketing messages are delivered after opt-out.
- **FINDING P1-3:** `ConversationService` post-commit `session.refresh()` calls fail under PostgreSQL RLS because the transaction commit resets transaction-local session variables.

### Medium (P2) — Logic & Authorization Gaps
- **FINDING P2-1:** `ConversationService.process_normalized_event()` does not acquire row locks on `Conversation` during bursts, risking lost version increments under concurrent webhook delivery.
- **FINDING P2-2:** `/inbox/conversations/{id}/handoff` and `/inbox/conversations/{id}/reply` lack RBAC checks to verify the caller holds a staff role rather than a `customer` role.

### Low (P3) — Code Quality & Frontend Hygiene
- **FINDING P3-1:** `src/frontend/inbox.html` injects message content into the DOM using `innerHTML` instead of `textContent`, exposing a reflected client-side XSS vulnerability.
- **FINDING P3-2:** Test suite relies on SQLite `StaticPool` for API and domain tests, preventing detection of PostgreSQL RLS transaction-boundary issues.

---

## 15. EXACT REMEDIATION CHECKLIST

To achieve a PASS verdict, the engineering team must execute the following remediations:

1. **Fix Webhook Tenant Context & Verification (P0-1):**
   In `src/backend/api/channels.py`, verify that `tenant_id` exists in `tenants` table, and explicitly set transaction-local tenant context on the session before invoking domain methods:
   ```python
   await db.execute(text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})
   ```
2. **Eliminate Post-Commit `session.refresh()` in `ConversationService` (P1-3):**
   In `src/backend/domains/conversations/service.py`:
   - Either remove `await session.refresh(...)` after `await session.commit()` (since `expire_on_commit=False` preserves all fields in memory), OR perform `await session.flush()` and `await session.refresh(...)` *before* `await session.commit()`.
3. **Cancel Pending Outbox Messages on STOP (P1-2):**
   In `ConversationService.process_normalized_event()`, when `is_stop` is detected:
   - Execute an update query marking all existing `PENDING` outbox events for that recipient on that channel as `CANCELLED` (`status = 'CANCELLED'`, `last_error = 'Suppressed due to STOP opt-out directive'`).
   - In `OutboxService.dispatch_pending_events()`, add a pre-send check ensuring the recipient has not opted out before dispatching non-safety events.
4. **Implement Pessimistic Row Locking in Outbox Dispatcher (P1-1):**
   In `OutboxService.dispatch_pending_events()`, add `.with_for_update(skip_locked=True)` on PostgreSQL engines to serialize worker claims.
5. **Add Row Locking on Conversation Version Increments (P2-1):**
   In `ConversationService.process_normalized_event()`, add `.with_for_update()` when querying active `Conversation` records to serialize concurrent message updates.
6. **Enforce Role Authorization in Inbox Endpoints (P2-2):**
   In `src/backend/api/inbox.py`, require caller roles to intersect with `{"platform_admin", "tenant_admin", "sales_manager", "sales_rep", "support_agent"}` before permitting handoff or agent replies.
7. **Fix Frontend DOM XSS (P3-1):**
   In `src/frontend/inbox.html`, replace `bubble.innerHTML = ...` with safe DOM construction using `textContent` for user input.
8. **Add Live PostgreSQL Integration Tests for Webhooks and Domain Services (P3-2):**
   Create integration tests running against `sales_app_user` on port 5432 that invoke `ConversationService.process_normalized_event()` and webhook endpoints to ensure no RLS boundary regressions.

---

## 16. UNVERIFIED FUNCTIONALITY AND LIMITATIONS

1. **Meta WhatsApp Cloud API Live Traffic:** External connectivity to Graph API is simulated with HMAC-SHA256 fixtures; live provider tokens are not configured.
2. **Email Delivery via SMTP/SendGrid:** Outbound email dispatch is modeled via transactional outbox payloads; real SMTP transport is deferred to external connector step.
3. **Voice Audio Processing:** In accordance with prompt boundaries, STT and TTS voice streaming are deferred to Step 10.

---

## 17. FINAL VERDICT

In accordance with strict acceptance criteria (*"PASS requires all mandatory STEP 03 invariants to be implemented and independently verified. A missing mandatory durability or tenant-isolation control blocks acceptance"*):

### **FINAL VERDICT: FAIL — REMEDIATION REQUIRED**

**Reasoning:**  
While unit tests pass on in-memory SQLite, the implementation fails on real PostgreSQL under Row-Level Security. Inbound webhooks cannot insert records due to unparameterized tenant context (P0), domain service methods crash on post-commit refresh (P1), STOP opt-out does not cancel pending marketing outbox messages (P1), and outbox dispatch lacks worker row locking (P1).

---

## 18. EXPLICIT STEP 04 ELIGIBILITY DECISION

### **STEP 04 IS STRICTLY BLOCKED.**

Engineering must not proceed to Step 04 (CRM, Catalog, Pricing, Quotations & Manager Approvals) until all P0, P1, and P2 findings in this audit are fully remediated, verified on live PostgreSQL 16, and confirmed by a clean re-audit.
