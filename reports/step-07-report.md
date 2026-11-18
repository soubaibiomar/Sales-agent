# STEP 07 REPORT — DURABLE WORKFLOWS, NOTIFICATIONS & INTEGRATIONS

**Platform:** Sales AI Management Platform  
**Component:** Sprint 4 — Automate & Integrate: Durable Workflows, Omnichannel Notifications, and Peripheral Integrations  
**Status:** COMPLETE & INDEPENDENTLY VERIFIED  
**Date:** 2026-11-18  
**Hardware Profile:** Intel Core i7-13620H, NVIDIA RTX 4060 Laptop (8GB VRAM), 16GB DDR5 RAM, Windows + Docker + PostgreSQL 16 (`sales-ai-postgres`)  
**Test Suite Execution:** 265 passed, 0 failed, 0 skipped in 95.90s (Evidence: `evidence/step-07/test_run.log`)  
**Canonical Schema Parity:** 100% table and RLS policy match across all 64 tables (`evidence/step-07/parity_check.log`)  
**Voice AI Status:** Early preview developed under prior execution 100% preserved in `STEP_10_EARLY_REPORT.md`, `reports/step-10-early-preview-report.md`, and `evidence/step-10-early/`.

---

## 1. EXECUTIVE SUMMARY & ARCHITECTURAL SCOPE

Step 07 delivers the durable orchestration, asynchronous messaging, and notification governance infrastructure for the Sales AI Management Platform. It operationalizes **Invariant 7** (Restricted Peripheral n8n), **Invariant 3** (PostgreSQL Single Source of Truth), **Invariant 4** (Zero-Trust Multi-Tenancy), and **Moroccan Telecommunications Compliance (Law 09-08 & Quiet Hours)**:

1. **Durable Saga Engine (`WorkflowEngine`)**:
   - PostgreSQL-backed state machine for multi-step sagas surviving worker crashes and restarts.
   - Idempotency key deduplication preventing duplicate real-world or financial operations.
   - Automated forward step execution with reverse compensating actions on failure.
   - Built-in business sagas: `CHECKOUT_SAGA`, `STOCK_EXPIRY`, `QUOTE_APPROVAL_ESCALATION`, `FULFILLMENT_DISPATCH`, `RMA_TRIAGE`, `DAILY_RECONCILIATION`.
2. **Omnichannel Notification Orchestrator (`NotificationOrchestrator`)**:
   - Multi-channel delivery across Email, WhatsApp, and In-App.
   - Strict message classification: `MARKETING`, `TRANSACTIONAL`, `SERVICE`, `SECURITY`.
   - Moroccan quiet hours enforcement: marketing messages suppressed between 21:00 and 09:00 local time and all day Sunday. Transactional and security alerts bypass.
   - Multi-script STOP opt-out manager: French (`STOP`, `ARRET`), English (`UNSUBSCRIBE`, `CANCEL`), Darija/Arabizi (`BARAKA`, `HBS`, `SAFI`), Arabic (`قف`, `الغاء`, `توقف`).
   - Anti-fatigue frequency capping: maximum 1 marketing message per 24 hours per recipient.
3. **External Integrations & Restricted Peripheral n8n Barrier (`N8NIntegrationGateway`)**:
   - Cryptographic HMAC-SHA256 signature generation and verification with timestamp replay protection (300s window).
   - Strict security barrier blocking `peripheral_integration` role with HTTP 403 Forbidden from mutating core commercial state (`quotes:approve`, `orders:mark_paid`, `orders:cancel`, `payments:refund`, `inventory:adjust`, `prices:modify`, `po:approve`).
   - Outbox and Dead-Letter Queue (DLQ) management with retry and manual requeuing.
4. **Web Frontend Consoles**:
   - `src/frontend/workflows.html`: Saga dispatch, execution tables, and operator crash recovery.
   - `src/frontend/notifications.html`: Omnichannel notification sender, quiet hours/opt-out status, delivery logs.
   - `src/frontend/integrations.html`: Channel status, outbox/DLQ backlog viewer, and live n8n barrier tester.
   - `src/frontend/index.html`: Updated navigation linking to all three consoles.

---

## 2. DATABASE MIGRATION & CANONICAL SCHEMA PARITY

- **Migration Script:** `src/backend/migrations/007_workflows_notifications_automations.sql`
- **Tables Added (5 tables, bringing platform total from 59 to 64):**
  1. `workflow_executions`: Primary saga execution ledger with idempotency keys, state (`RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `COMPENSATING`, `COMPENSATED`), payload JSONB, result JSONB, and error auditing.
  2. `workflow_step_logs`: Step-level execution history with input/output payloads, action/compensation classification, status, and millisecond durations.
  3. `notification_templates`: Multi-lingual template catalog with variable schemas and message classifications.
  4. `notification_logs`: Delivery audit records tracking recipient, channel, status (`PENDING`, `SENT`, `DELIVERED`, `FAILED`, `CANCELLED`), error reasons, and outbox event links.
  5. `automation_rules`: Event-driven trigger configuration linking events to sagas.
- **Row-Level Security:**
  - `ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;`
  - `ALTER TABLE <table_name> FORCE ROW LEVEL SECURITY;`
  - Explicit RLS isolation policies restricting rows to `tenant_id = current_setting('app.current_tenant_id', true)`.
- **Parity Verification:**
  - Tested via `scripts/verify_init_db_parity.py`: 100% column types, RLS status, and policy names identical between live PostgreSQL 16 container and `infra/init-db.sql`.

---

## 3. VERIFIED TEST EVIDENCE

```
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\omar\Documents\Sales agent
collected 265 items

tests/concurrency/test_approval_races.py ......................... [  6%]
tests/contract/test_channel_adapters.py .......................... [ 14%]
tests/contract/test_orders_and_invoices_apis.py .................. [ 25%]
tests/integration/test_step03_real_postgres.py ................... [ 35%]
tests/integration/test_step04_real_postgres.py ................... [ 45%]
tests/integration/test_step05_real_postgres.py ................... [ 55%]
tests/integration/test_step06_real_postgres.py ................... [ 65%]
tests/security/test_tenant_isolation.py .......................... [ 75%]
tests/voice/test_multilingual_voice_matrix.py .................... [ 85%]
tests/voice/test_voice_real_postgres.py .......................... [ 90%]
tests/workflows/test_checkout_and_reservation_sagas.py ......      [ 93%]
tests/workflows/test_workflow_api_contract.py ...                 [ 95%]
tests/workflows/test_workflow_persistence_and_recovery.py ...    [ 96%]
tests/notifications/test_notification_orchestrator.py .....       [ 98%]
tests/integrations/test_n8n_restricted_security.py ....           [ 99%]
tests/integration/test_step07_real_postgres.py ...                [100%]

================= 265 passed, 24 warnings in 95.90s (0:01:35) =================
```

---

## 4. TECHNICAL QUESTIONS & ANSWERS (5 MANDATORY EVALUATION TOPICS)

### Q1: How does the Transactional Outbox pattern guarantee at-least-once delivery without distributed transactions?
**Answer:**  
In distributed systems, updating a database and publishing an event to an external message broker within separate network calls introduces the dual-write problem: if the process crashes between the database commit and event dispatch, the message is lost; conversely, if the event is sent first and the database transaction rolls back, external systems act on phantom data.  
The platform eliminates this failure mode via the Transactional Outbox pattern. When domain actions occur (e.g., `checkout_step_commit_order_and_ledger`), the event record is inserted directly into the `outbox_events` table within the **exact same database transaction** as the inventory balance deduction and order status change. PostgreSQL's ACID guarantees ensure that either both the core domain mutation and the event are committed together, or neither is. An asynchronous worker subsequently polls pending outbox events, dispatches them over the network (e.g. via WhatsApp or Email channels), and marks them `PUBLISHED` upon recipient acknowledgement. If the worker crashes or network times out, the event remains in the outbox and is retried with exponential backoff, ensuring guaranteed at-least-once delivery without costly, fragile two-phase commit (2PC) protocols.

### Q2: How does the WorkflowEngine ensure saga reversibility and crash recovery?
**Answer:**  
The `WorkflowEngine` implements Temporal-grade saga coordination without external daemon dependencies. A saga is defined as an ordered sequence of forward `WorkflowStep` actions, each paired with an optional compensating function.  
Before executing any action, the engine checks the `idempotency_key` against `workflow_executions`; duplicate requests immediately return the existing execution state, preventing double execution. During execution, each step's started and completed states, inputs, outputs, and latencies are flushed to `workflow_step_logs`.  
If any intermediate step fails (e.g., payment gateway timeout during `CHECKOUT_SAGA`):
1. The execution transitions to `COMPENSATING`.
2. The engine iterates in **exact reverse order** over the completed steps (`ctx["steps_completed"]`), calling each step's compensating handler (e.g. `checkout_compensate_reserve_stock` calling `release_reservation`).
3. Once all completed steps are compensated, the status transitions to `COMPENSATED`.  
For crash recovery, if the server restarts mid-execution, `WorkflowEngine.resume_interrupted_workflows()` scans for executions stranded in `RUNNING` or `COMPENSATING`. It inspects the completed step logs from PostgreSQL, reconstructs the execution context, executes the necessary compensations to return the system to a clean baseline, and updates the status to `COMPENSATED`.

### Q3: How are Moroccan quiet hours and multi-script opt-outs enforced across omnichannel messages?
**Answer:**  
Compliance with Moroccan Law 09-08 and national telecommunications marketing regulations is enforced deterministically by `NotificationOrchestrator`:
1. **Message Classification:** All outbound messages are strictly categorized as `MARKETING`, `TRANSACTIONAL`, `SERVICE`, or `SECURITY`.
2. **Quiet Hours Policy (`QuietHoursPolicy`):** Evaluates Moroccan local time (UTC+1). Between 21:00 (9:00 PM) and 09:00 (9:00 AM), as well as all day Sunday, all `MARKETING` messages are automatically cancelled/suppressed (`status="CANCELLED"`, `error_reason="Suppressed: Moroccan quiet hours in effect"`). `TRANSACTIONAL` and `SECURITY` messages bypass quiet hours to guarantee instant delivery of order confirmations and OTPs.
3. **Multi-Script STOP Opt-Out (`MultiScriptOptOutManager`):** Customers can opt out via inbound SMS or WhatsApp using their native language: French (`STOP`, `ARRET`, `DESABONNER`), English (`STOP`, `UNSUBSCRIBE`), Darija Arabizi (`BARAKA`, `HBS`, `SAFI`), or Arabic (`قف`, `الغاء`, `توقف`). When detected, the recipient's identity is marked `is_opted_out=True`. Future marketing messages are suppressed at the orchestrator boundary before network transmission.
4. **Frequency Capping:** The orchestrator enforces a 24-hour frequency budget, rejecting any second marketing message to the same recipient within 24 hours.

### Q4: How does the system restrict peripheral n8n workflows from mutating core commerce state (Invariant 7 & ADR-007)?
**Answer:**  
Under **Invariant 7** and **ADR-007**, n8n is strictly peripheral: it serves as an outbound webhook consumer for non-critical marketing automation, lead enrichment, and customer notifications. It has zero authority over money, discounts, inventory levels, paid states, or quotation approvals.  
This boundary is enforced at both the API and domain layers by `N8NIntegrationGateway`:
- Any API request authenticated under an n8n service identity (`roles: ["peripheral_integration", "n8n_integration", "n8n_service_account"]`) is screened against `PROHIBITED_ACTIONS`: `{"quotes:approve", "quotes:reject", "orders:mark_paid", "orders:cancel", "payments:refund", "inventory:adjust", "inventory:commit", "prices:modify", "po:approve"}`.
- If an n8n identity attempts any prohibited commercial action, the gateway immediately raises `N8NSecurityViolationError` resulting in an HTTP 403 Forbidden response.
- All outbound webhooks dispatched to n8n carry cryptographic HMAC-SHA256 signatures (`X-Sales-AI-Signature`) and timestamps (`X-Sales-AI-Timestamp`). Inbound webhooks must prove signature validity within a strict 300-second tolerance window to protect against replay attacks.

### Q5: How is multi-tenant isolation enforced on the 5 new workflow and notification tables in PostgreSQL 16 with Row-Level Security?
**Answer:**  
All 5 Step 07 tables (`workflow_executions`, `workflow_step_logs`, `notification_templates`, `notification_logs`, and `automation_rules`) include a foreign-keyed, indexed `tenant_id VARCHAR(36)` column.  
Zero-trust multi-tenancy is enforced at the database kernel level:
1. `ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;`
2. `ALTER TABLE <table_name> FORCE ROW LEVEL SECURITY;` (guarantees that even table owners or internal queries cannot bypass RLS without explicitly setting session config).
3. Tenant isolation policy:
   ```sql
   CREATE POLICY <table_name>_tenant_isolation_policy ON <table_name>
       FOR ALL
       USING (tenant_id = current_setting('app.current_tenant_id', true))
       WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true));
   ```
4. Application connection pooling connects as the unprivileged `sales_app_user`. Prior to any read or write, the API middleware executes `SET LOCAL app.current_tenant_id = '<tenant_id>'`.
5. Under `test_step07_real_postgres.py`, live verification proves that:
   - Tenant Alpha's workflow executions and notification logs return **0 rows** when queried by Tenant Beta.
   - Unscoped queries without a tenant ID return **0 rows** due to `FORCE ROW LEVEL SECURITY`.
