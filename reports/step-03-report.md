# STEP 03 IMPLEMENTATION & VALIDATION REPORT
## Omnichannel Ingestion, Conversation Ownership, Transactional Outbox & Sales Workspace Inbox

**Project:** Sales AI Management Platform  
**Sprint:** 2 — Connect  
**Date:** 2026-11-18  
**Author:** Lead Software Architect, Senior Backend Engineer, Security Engineer, AI Systems Engineer  
**Status:** **REMEDIATION ROUND 2 COMPLETE** (153/153 Tests Passing — Ready for Independent Codex Re-Audit)  
**Round 2 Remediation Report:** [reports/STEP_03_REMEDIATION_ROUND_2.md](file:///c:/Users/omar/Documents/Sales%20agent/reports/STEP_03_REMEDIATION_ROUND_2.md)  
**Round 1 Remediation Report:** [reports/STEP_03_REMEDIATION_REPORT.md](file:///c:/Users/omar/Documents/Sales%20agent/reports/STEP_03_REMEDIATION_REPORT.md)  
**Evidence Artifacts:**
- Full Regression Test Log: `evidence/step-03-remediation-round-2/test_run.log`
- Canonical Parity Verification Log: `evidence/step-03-remediation-round-2/canonical_parity.log`  

---

## 1. EXECUTIVE SUMMARY & OBJECTIVE

STEP 03 delivers the **Omnichannel Communication Gateway, Durable Event Ingestion Pipeline, Transactional Outbox with Dead-Letter Queue (DLQ), and Sales Workspace Unified Inbox**. 

The platform normalizes inbound and outbound traffic across four primary commercial channels:
1. **WhatsApp Business** (Cloud API webhooks, HMAC-SHA256 signature verification, WAMID deduplication)
2. **Gmail / Inbound Email** (MIME parsing, SPF/DKIM verification check simulation, HTML XSS sanitization)
3. **Authenticated Web Chat** (Session token validation, guest/authenticated customer context, rate limiting)
4. **Voice / SIP Telephony Transport** (Call signaling events, duration tracking, explicit recording disclosure consent)

### Non-Negotiable Invariants Upheld:
- **Durable Ingest Before Routing:** Raw provider envelopes are persisted in the PostgreSQL operational database (`inbound_raw_events`) before batching, debouncing, or routing. Replayed or duplicated events are rejected without side effects.
- **Deterministic Commercial Authority:** Contact matching does not perform fuzzy or unverified auto-merges across channels. Deterministic multilingual STOP/opt-out directives (English, French, Standard Arabic, Moroccan Darija/Arabizi) outrank all LLM suggestions and halt automated outbound messaging immediately.
- **Atomic Human Handoff & Versioning:** Conversations enforce monotonic integer versioning (`version`). When a human operator claims a conversation (`status = 'HUMAN_ACTIVE'`), the AI assistant is silenced (`is_ai_silenced = True`). Any in-flight background AI turn with a stale expected version is rejected upon submission with `StaleTurnError`.
- **Out-of-Order Message Ingestion Handling:** Inbound messages arriving out of sequence retain physical event timestamps, ensure chronological timeline sorting (`created_at.asc()`), prevent `last_message_at` regression, and advance versioning to immediately fence stale AI turns.
- **Transactional Outbox & Dead-Letter Queue (DLQ):** Outbound events (`outbox_events`) are enqueued atomically with state transitions. Failed deliveries retry with exponential backoff (`base * 2^retry`), route to `DEAD_LETTER` upon exhausting retries with `AuditEvent` emission, and support high-priority immediate safety bypass for STOP confirmations and alerts.
- **Zero-Trust Multi-Tenancy & RLS:** All 13 platform tables (6 core + 7 omnichannel) enforce PostgreSQL 16 Row-Level Security (`ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`) with permissive policies tied to `app.current_tenant_id`. Unprivileged role `sales_app_user` cannot access cross-tenant data.
- **Canonical Parity Verified:** An automated parity verifier (`scripts/verify_init_db_parity.py`) verified 100% catalog, column, nullability, RLS, and policy parity between `infra/init-db.sql` and the live migrated database.
- **Hardware Envelope Integrity:** Ingestion, deduplication, contact resolution, STOP detection, outbox dispatch, and inbox management run deterministically on the CPU/backend, preserving discrete GPU VRAM (8 GB) for active AI model lifecycle turns.

---

## 2. INSPECTED BASELINE & GIT STATE

- **Initial Commit:** `a8eaedc` (Step 02 Remediation Commit)
- **Phase 0 Completion:** Before commencing Step 03 implementation, the outstanding Step 02 advisory condition regarding `infra/init-db.sql` `AS RESTRICTIVE` policy syntax was investigated and remediated. The fix was verified on an isolated fresh PostgreSQL instance on port `5433` and documented in `reports/STEP_02_CONDITION_CLOSURE.md`.
- **Active Infrastructure:**
  - `sales-ai-postgres`: PostgreSQL 16.1 Alpine on `127.0.0.1:5432` (Healthy)
  - `sales-ai-redis`: Redis 7.2.4 Alpine on `127.0.0.1:6379` (Healthy)
  - `sales-ai-minio`: MinIO Object Storage on `127.0.0.1:9000` (Healthy)
  - `ollama`: Ollama v0.5.12 on `127.0.0.1:11434` (Healthy)
- **Starting Test Baseline:** 79/79 tests passing.
- **Current Test Count:** 153/153 tests passing (including 17/17 live PostgreSQL tests in `test_step03_real_postgres.py`).

---

## 3. ARCHITECTURE DECISIONS & COMPONENT DESIGN

### 3.1 Durable Event Ingestion Architecture
```
[ Incoming Webhook (WhatsApp / Email / WebChat / SIP) ]
                         │
                         ▼
           [ Webhook Signature Validator ]
     (HMAC-SHA256 / Bearer Secret / Auth Token)
                         │
                         ▼
             [ Durable Raw Ingest Buffer ]
      (inbound_raw_events: UNIQUE(tenant_id, channel, provider_event_id))
        ├── If Duplicate -> Return 200 OK (Duplicate Ignored, No side-effects)
        └── If New -> Status: PENDING -> Persist to DB
                         │
                         ▼
             [ Channel Adapter Normalizer ]
           (WhatsAppAdapter / EmailAdapter / WebChatAdapter / VoiceSIPAdapter)
                         │
                         ▼
        [ Deterministic Multilingual STOP Guard ]
  (English, French, Standard Arabic, Darija/Arabizi)
        ├── If STOP -> is_opted_out = True -> Audit Log -> Silence AI
        │               └── Enqueue High-Priority STOP Ack to Outbox
        └── If Normal -> Continue
                         │
                         ▼
          [ Contact & Channel Identity Resolver ]
   (Strict Identifier Matching: E.164 Phone / Email / Session UUID)
                         │
                         ▼
        [ Conversation State Machine & Monotonic Version ]
   (Check: status == 'HUMAN_ACTIVE'? Silence AI : Increment Version)
                         │
                         ▼
        [ Normalized Conversation Timeline & Attachments ]
  (conversation_messages + message_attachments + PII Redaction)
                         │
                         ▼
        [ Transactional Outbox & DLQ Service ]
  (outbox_events: PENDING -> PROCESSING -> DELIVERED / FAILED / DEAD_LETTER)
```

### 3.2 Monotonic Conversation State Machine & Out-of-Order Handling
Conversations transition through deterministic states:
- `BOT_ACTIVE` (Default): Automated AI specialists can propose draft replies if expected version matches.
- `HUMAN_PENDING`: Customer requested human agent or issue resolution requires escalation.
- `HUMAN_ACTIVE`: A sales representative or support agent took over the session; `is_ai_silenced = True`. AI replies are rejected.
- `CLOSED`: Conversation concluded.

**Out-of-Order Ingestion Resolution:**
- Provider event timestamps are preserved in `ConversationMessage.created_at`.
- Queries order messages strictly chronologically: `.order_by(ConversationMessage.created_at.asc())`.
- `last_message_at` is set to `max(current_last_message_at, event_timestamp)`, preventing timestamp regression.
- Every ingested message increments `conversation.version += 1`, immediately cancelling any in-flight AI turn whose `expected_version` was captured before the late message arrived.

### 3.3 Transactional Outbox, Exponential Backoff & DLQ Architecture
Outbound communication is governed by `OutboxService` (`src/backend/domains/conversations/outbox.py`):
1. **Atomic Enqueue:** When replies or alerts are generated, an `OutboxEvent` record is written inside the same ACID transaction as the message or state mutation.
2. **State Machine:** `PENDING` -> `PROCESSING` -> `DELIVERED` | `FAILED` -> `DEAD_LETTER`.
3. **Exponential Backoff:** When external delivery fails, `retry_count` is incremented and `next_retry_at = now + 2^retry_count` seconds.
4. **Dead-Letter Queue:** When `retry_count >= max_retries` (default 3), the event transitions to `DEAD_LETTER`, `last_error` is preserved, and an `AuditEvent` (`OUTBOX_DEAD_LETTER`) is emitted for security/operational alerting.
5. **High-Priority Safety Bypass:** Events with `is_high_priority = True` (STOP acknowledgements, compliance notices, safety alerts) are ordered first in dispatcher queries (`is_high_priority.desc()`), bypassing routine message queues.
6. **Administrative Redrive:** Administrators can inspect dead-letter queues and invoke `redrive_dead_letter_event()`, resetting state to `PENDING` and logging an `OUTBOX_REDRIVE` audit event.

### 3.4 Anti-SSRF URL & Media Security (Baseline Controls 20, 21, 23)
Inbound media (images, PDFs, voice recordings) submitted via webhooks often reference external provider CDN URLs. To prevent Server-Side Request Forgery (SSRF):
- `validate_media_url()` inspects hostnames, resolves DNS, and blocks:
  - Loopback (`127.0.0.0/8`, `::1`)
  - Private networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`)
  - Link-local and metadata addresses (`169.254.169.254`, `fe80::/10`)
  - Non-HTTP(S) schemes (`file://`, `gopher://`, `ftp://`).
- `validate_attachment_metadata()` validates MIME magic types against an allowed whitelist and enforces a 15 MB file size limit.

---

## 4. DETAILED IMPLEMENTATION & SOURCE ARTIFACTS

### 4.1 Schema Migration & ORM Entities
- `src/backend/migrations/002_omnichannel_schema.sql`:
  - `contacts`: Customer records scoped to tenant (`id`, `tenant_id`, `display_name`, `primary_phone`, `primary_email`, `is_verified`).
  - `channel_identities`: Channel linkage with consent tracking (`channel_type`, `identifier`, `is_opted_out`, `opt_out_at`, `opt_out_reason`, `consent_given_at`). Unique on `(tenant_id, channel_type, identifier)`.
  - `conversations`: Conversation entity with `version` integer, `is_ai_silenced` boolean, `status`, `assigned_user_id`, `unread_count`.
  - `inbound_raw_events`: Pre-debounce durable buffer with unique constraint `(tenant_id, channel_type, provider_event_id)`.
  - `conversation_messages`: Normalized message stream (`sender_type`, `content`, `content_redacted`, `event_type`, `conversation_version`).
  - `message_attachments`: File attachments with MIME type and safety flags.
  - `outbox_events`: Transactional outbox with retry count, backoff timestamp, DLQ status, and high-priority flag.
- `src/backend/models/entities.py`: Added SQLAlchemy declarative models for all 7 tables.
- `infra/init-db.sql`: Updated canonical SQL initialization with all 7 omnichannel tables, indexes, and permissive RLS policies.
- `scripts/apply_omnichannel_migration.py`: Executed live migration on PostgreSQL 16 container.
- `scripts/verify_init_db_parity.py`: Validated 100% schema, RLS, and policy parity between `infra/init-db.sql` and live PostgreSQL.

### 4.2 Integrations & Channel Adapters
- `src/backend/integrations/base.py`: Defined `BaseChannelAdapter` and `NormalizedInboundEvent`.
- `src/backend/integrations/whatsapp.py`: `WhatsAppAdapter` with `X-Hub-Signature-256` HMAC-SHA256 validation, Cloud API webhook payload parsing, and WAMID extraction.
- `src/backend/integrations/email.py`: `EmailAdapter` with SPF/DKIM verification checks, HTML XSS tag stripping, and email parsing.
- `src/backend/integrations/webchat.py`: `WebChatAdapter` for embedded website widgets.
- `src/backend/integrations/voice_sip.py`: `VoiceSIPAdapter` for call signaling, duration tracking, and legal recording disclosure consent.

### 4.3 Domain Logic, Outbox & Media Security
- `src/backend/domains/conversations/outbox.py`: `OutboxService` managing event enqueue, exponential backoff, DLQ exhaustion, high-priority safety bypass, and manual redrives.
- `src/backend/core/media_security.py`: Anti-SSRF URL validator, MIME type verification, file size limits.
- `src/backend/domains/conversations/service.py`: `ConversationService` implementing durable ingestion, contact matching without auto-merge, deterministic multilingual STOP regex detection, PII redaction, atomic handoff, out-of-order timeline preservation, and optimistic version checks.

### 4.4 API Routers & Frontend Workspace
- `src/backend/api/channels.py`:
  - `POST /api/v1/channels/webhooks/whatsapp/{tenant_id}`: Webhook receiver with signature verification.
  - `GET /api/v1/channels/webhooks/whatsapp/{tenant_id}`: Meta challenge verification endpoint.
  - `POST /api/v1/channels/webhooks/email/{tenant_id}`: Inbound email receiver.
  - `POST /api/v1/channels/webhooks/voice/{tenant_id}`: Telephony session event receiver.
  - `POST /api/v1/channels/webchat/send`: Customer webchat message endpoint.
- `src/backend/api/inbox.py`:
  - `GET /api/v1/inbox/conversations`: Unified inbox queue listing with channel/status filtering.
  - `GET /api/v1/inbox/conversations/{id}/timeline`: Full chronological message timeline.
  - `POST /api/v1/inbox/conversations/{id}/handoff`: Atomic human takeover endpoint.
  - `POST /api/v1/inbox/conversations/{id}/release`: Release conversation back to AI.
  - `POST /api/v1/inbox/conversations/{id}/reply`: Human agent reply endpoint.
- `src/backend/main.py`: Mounted `channels_router` and `inbox_router`.
- `src/frontend/inbox.html`: Sales Workspace Unified Inbox UI styled with brand design tokens (`#0A3A2A`, `#10B981`, `#FFFFFF`, `#F8FAFC`). Includes responsive multi-column layout, channel filter pills, unread badges, message timeline, AI silenced banner, composer, and customer context sidebar.
- `src/frontend/index.html`: Added navigation link to the Unified Inbox.

---

## 5. ORIGINAL VS. CURRENT COMPARISON

| Feature / Subsystem | Prior Step (Step 02) | Current State (Step 03) | Impact & Architectural Invariant |
|---|---|---|---|
| **Commercial Channels** | Zero channel ingestion | WhatsApp, Email, WebChat, Voice/SIP | Omnichannel normalization into single conversation model |
| **Inbound Event Persistence** | None | Durable raw buffer (`inbound_raw_events`) | Zero message loss before routing; duplicate protection |
| **Transactional Outbox & DLQ** | None | `outbox_events` + `OutboxService` | Reliable outbound dispatch, exponential backoff, DLQ audit |
| **Contact Identity** | User accounts only | `contacts` + `channel_identities` | Multi-channel linkage without unverified auto-merge |
| **Conversation State Machine** | None | Monotonically versioned state machine | Atomic human takeover; stale AI turn rejection |
| **Out-of-Order Messages** | None | Chronological sorting + version fence | Prevents timestamp regression; cancels stale AI turns |
| **Regulatory Consent & STOP** | Conceptual | Deterministic multilingual STOP engine | English, French, Darija/Arabic STOP outranks AI |
| **Media & SSRF Defense** | None | Anti-SSRF URL validator & MIME filter | Blocks internal network reconnaissance and malware |
| **PostgreSQL RLS Tables** | 6 tenant tables | 13 tenant tables (all `PERMISSIVE` + forced) | Comprehensive tenant isolation across omnichannel entities |
| **Canonical SQL Parity** | Advisory condition | 100% verified parity on fresh DB | Clean initialization matches active schema exactly |
| **Unified Sales Inbox** | Console overview only | Interactive Sales Workspace Inbox UI | Multi-channel queue management and human takeover |

---

## 6. SECURITY CONTROL TRACEABILITY (STEP 03)

The following controls from `references/70-security.xlsx` and `security/SAI_EXTENSION.md` were directly implemented and tested during Step 03:

| Control ID | Control Name (Canonical Excel) | Implementation Mechanism in Step 03 | Verified Test Module |
|---|---|---|---|
| **16** | Missing input validation | Pydantic models, MIME checking, and payload validation in adapters. | `tests/contract/test_channel_adapters.py` |
| **17** | SQL injection | SQLAlchemy ORM parameterized queries across all conversation services. | `tests/integration/test_omnichannel_rls.py` |
| **19** | Cross-site scripting (XSS) | `EmailAdapter.sanitize_content()` strips `<script>`, `<style>`, and raw HTML tags. | `tests/contract/test_channel_adapters.py` |
| **20** | Cross-site request forgery (CSRF) | SameSite cookies, JWT bearer headers, and HMAC signatures on webhooks. | `tests/contract/test_inbox_and_channel_apis.py` |
| **21** | Insecure file uploads | `validate_attachment_metadata()` enforces MIME whitelist and 15MB file cap. | `tests/security/test_channel_security.py` |
| **22** | Path traversal | Filename sanitization in `validate_attachment_metadata()` (`_` replacement, dot rejection). | `tests/security/test_channel_security.py` |
| **23** | Server-side request forgery (SSRF) | `validate_media_url()` rejects private, loopback, link-local, and non-HTTP IPs. | `tests/security/test_channel_security.py` |
| **27** | Overly permissive CORS | Explicit CORS allowlist (`settings.cors_origins_list`) in `main.py`. | Preserved from Step 02 |
| **28** | Missing rate limits | WebChat endpoints rate-limiting and payload size bounds. | `tests/contract/test_inbox_and_channel_apis.py` |
| **33** | IDOR / BOLA | In `inbox.py`, timeline queries require `tenant_id == context.tenant_id`. | `tests/contract/test_inbox_and_channel_apis.py` |
| **34** | APIs trusting user-controlled roles or IDs | SecurityContext derives tenant and user from verified JWT signature. | Preserved from Step 02 |
| **35** | Sensitive data in logs | `redact_pii()` scrubs credit cards, passwords, and PINs in `content_redacted`. | `tests/security/test_channel_security.py` |
| **42** | Missing audit logs | `AuditEvent` emitted on consent opt-out (STOP), DLQ exhaustion, and handoff. | `tests/contract/test_outbox_and_dlq.py` |
| **57** | Business-logic abuse | AI replies blocked when conversation is opted-out or owned by a human. | `tests/concurrency/test_conversation_races.py` |
| **58** | Race conditions | Monotonic conversation `version` prevents stale AI turns from overwriting turns. | `tests/concurrency/test_conversation_races.py` |
| **59** | Webhook replay / duplicate processing | Unique constraint on `(tenant_id, channel, provider_event_id)` marks duplicates. | `tests/security/test_channel_security.py` |
| **SAI-11** | Multilingual STOP & Human Takeover Guard | Regex STOP detection across 4 languages; atomic AI silencing on handoff. | `tests/unit/test_deterministic_stop.py` |

---

## 7. EXECUTED TEST SUITE RESULTS

The test suite was executed against the running PostgreSQL 16 database, Redis, MinIO, and Ollama environment:

```powershell
$env:PYTHONPATH="."
python -m pytest tests/ -v
```

### 7.1 Measured Execution Summary
- **Total Test Cases Executed:** 153
- **Passed:** 153 (100%)
- **Failed:** 0
- **Errors:** 0
- **Skipped:** 0
- **Measured Duration:** 47.44 seconds (Full Regression Suite)
- **Evidence Log Path:** [evidence/step-03-remediation-round-2/test_run.log](file:///c:/Users/omar/Documents/Sales%20agent/evidence/step-03-remediation-round-2/test_run.log)
- **Canonical Parity Verification Log:** [evidence/step-03-remediation-round-2/canonical_parity.log](file:///c:/Users/omar/Documents/Sales%20agent/evidence/step-03-remediation-round-2/canonical_parity.log)

### 7.2 Breakdown by Test Module
1. `tests/integration/test_step03_real_postgres.py`: **17 passed** (Direct real PostgreSQL 16 tests verifying all 5 Round 2 audit defects: CRIT-01 cross-tenant route URL parameter swap 403, unregistered asset 404, deactivated asset 403; CRIT-02 connection pool context wipe on checkin and `is_local=true` transaction isolation; HIGH-01 selective STOP cancellation of marketing messages while preserving transactional notices; MED-01 3-phase outbox lease/commit releasing DB locks before network callable and fencing token protection; MED-02 composable domain transaction rollback on error; concurrent inbound version bursts, unprivileged staff inbox RBAC).
2. `tests/contract/test_channel_adapters.py`: **8 passed** (WhatsApp HMAC signature verification, text and media payload parsing, Email SPF/DKIM verification, HTML XSS stripping, WebChat normalization, Voice/SIP recording consent).
3. `tests/contract/test_inbox_and_channel_apis.py`: **4 passed** (WhatsApp challenge verification, webhook duplicate replay rejection, WebChat send endpoint, Unified Inbox conversation listing, timeline, and agent reply).
4. `tests/contract/test_outbox_and_dlq.py`: **5 passed** (Transactional outbox enqueue, successful dispatch, exponential backoff retries, dead-letter queue exhaustion with AuditEvent emission, high-priority safety bypass, manual redrive).
5. `tests/contract/test_out_of_order_messages.py`: **3 passed** (Out-of-order timeline sorting, non-regressing `last_message_at`, monotonic version incrementation, stale AI turn rejection on version mismatch, out-of-order STOP immediate AI silencing).
6. `tests/unit/test_deterministic_stop.py`: **18 passed** (Multilingual STOP regex matrix across English, French, Standard Arabic, and Moroccan Darija/Arabizi; channel opt-out and AI silencing).
7. `tests/concurrency/test_conversation_races.py`: **4 passed** (Monotonic version incrementation, stale AI turn cancellation on customer message race, human takeover cancelling in-flight AI turn, burst handling).
8. `tests/security/test_channel_security.py`: **13 passed** (Durable raw event deduplication, anti-SSRF IP blocking across private/loopback/metadata ranges, MIME whitelist validation, file size limits, PII credit card redaction).
9. `tests/integration/test_omnichannel_rls.py`: **2 passed** (Real PostgreSQL 16 RLS tests connecting as `sales_app_user` on port 5432 verifying zero cross-tenant leakage on all 7 omnichannel tables including `outbox_events`).
10. `tests/integration/test_postgres_rls.py`: **10 passed** (Live PostgreSQL Step 02 RLS regression covering all 13 policies).
11. `tests/step01/`: **27 passed** (Architecture, repo hygiene, requirements traceability, security controls, hardware lifecycle).
12. `tests/security/test_auth_and_rbac.py` & `test_backup_restore.py` & `test_ai_model_governance.py`: **28 passed** (Step 02 regression).
13. `tests/unit/`: **14 passed** (Local AI constraints, telemetry, multilingual language matrix).

---

## 8. FIVE TECHNICAL QUESTIONS WITH COMPLETE ANSWERS

### Q1: Why must raw inbound webhook envelopes be persisted durably before any debounce, parsing, or agent routing?
**Answer:**  
In production omnichannel environments, webhook deliveries are subject to network drops, application process restarts, worker crashes, and provider retry storms. If an event is acknowledged (`HTTP 200 OK`) while held only in memory, or if it is held in a Redis buffer that crashes before database persistence, the customer message is permanently lost. By persisting the raw metadata-minimized payload into `inbound_raw_events` within the primary ACID PostgreSQL database *first*, three critical invariants are achieved:
1. **Zero Message Loss:** Once committed, the event survives process crashes and can be replayed or recovered.
2. **Idempotent Deduplication:** A database unique constraint on `(tenant_id, channel_type, provider_event_id)` immediately catches duplicate deliveries from Meta or email providers, returning `200 OK` without triggering duplicate agent responses or double-incrementing conversation unread counters.
3. **Legal Auditability:** Under Moroccan Law 09-08 and GDPR, an uncorrupted raw record of what was received at the edge is retained for forensic verification prior to transformation.

### Q2: How does monotonic versioning prevent race conditions between human operator handoff and in-flight AI turn generation?
**Answer:**  
When an AI model generates an inference response (especially high-complexity models running locally on CPU or GPU), generation takes between 500ms and several seconds. During this window, two race conditions frequently occur:
1. The customer sends a second message changing or qualifying their request.
2. A human sales representative clicks "Take Over Conversation" to address an escalated lead.

Without monotonic versioning, the background AI worker would blindly commit its outdated response, speaking over the human agent or answering an obsolete premise. In our architecture, the `conversations` table maintains an integer `version` that increments monotonically on *every* message or state transition. When an AI turn begins, it captures `expected_version = conv.version`. When the AI finishes, `ConversationService.post_ai_reply()` executes an atomic check:
`IF conv.is_ai_silenced OR conv.version != expected_version THEN RAISE StaleTurnError`.
If the human operator took over (`is_ai_silenced = True`, `version += 1`), the AI output is discarded without reaching the customer.

### Q3: Why is auto-merging contacts across channels based solely on display name or fuzzy matching strictly prohibited?
**Answer:**  
Auto-merging customer records based on non-unique attributes like names (e.g. "Mohamed Alami" or "Sara") is a critical security vulnerability that leads to cross-customer data leakage and privacy breaches. If Customer B happens to have the same name as Customer A, merging their timelines would expose Customer A's private quotations, order histories, delivery addresses, and voice recordings to Customer B. In our architecture, a new `Contact` is created for every unverified channel identity unless cryptographically or deterministically linked (e.g. phone number verified via SMS OTP, authenticated email link, or verified portal session). Explicit human authorization or two-factor identity proofing is required before any cross-channel identity merge occurs.

### Q4: What are the security implications of server-side media URL fetching (e.g. WhatsApp/Email media attachments), and how is SSRF mitigated?
**Answer:**  
When providers notify our API of media attachments, they typically provide a CDN URL where the media can be downloaded. An attacker could forge a webhook or craft an email referencing an internal infrastructure endpoint (e.g. `http://169.254.169.254/latest/meta-data` for AWS/cloud credentials, `http://127.0.0.1:6379/` for Redis exploitation, or `http://sales-ai-postgres:5432/`). If the server blindly issues a `GET` request to fetch the attachment, the server acts as an internal proxy for the attacker (Server-Side Request Forgery).  
Our `validate_media_url()` guard defends against this by parsing the scheme (only `http`/`https` allowed), resolving the hostname via DNS, and testing every resolved IP against standard IP network classifications. It strictly rejects loopback (`127.0.0.0/8`), RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local metadata addresses (`169.254.0.0/16`), and non-routable multicast IPs.

### Q5: How is deterministic multilingual STOP/opt-out handling architected to outrank LLM interpretations and guarantee regulatory compliance under Moroccan Law 09-08 and GDPR?
**Answer:**  
Article 10 of Moroccan Law 09-08 and Article 21 of GDPR grant data subjects the absolute right to object to commercial processing and opt-out of marketing communications at any time. Relying on an LLM to interpret whether a customer wants to opt out is unsafe: models can hallucinate, misunderstand dialectal slang, or misclassify intent due to system prompt drift.  
Our architecture implements deterministic regex matching before any event is handed to routing or LLM agents. The regex matrix covers English (`STOP`, `UNSUBSCRIBE`, `QUIT`), French (`ARRET`, `DESABONNER`), Standard Arabic (`حبس`, `وقف`, `إلغاء`), and Moroccan Darija/Arabizi (`baraka`, `safii baraka`, `stoppi`, `7bes`). When detected, `ChannelIdentity.is_opted_out` is immediately set to `True`, a permanent legal `AuditEvent` is written, and the conversation is marked `is_ai_silenced = True`. In addition, a high-priority opt-out acknowledgement is enqueued directly to the transactional outbox with `is_high_priority = True`. Any subsequent attempt by an automated agent to send outbound messages through that channel is blocked deterministically at the domain layer.

---

## 9. OUTSTANDING RISKS & LIMITATIONS

1. **Simulated vs. Live External Credentials:**
   In compliance with Master Prompt Rule 5 (*"Never push, release, provision billable infrastructure, call customers, connect production accounts or expose environments without explicit user authorization"*), tests use cryptographic webhook simulation (valid HMAC-SHA256 signatures, real Meta JSON schemas, RFC 822 email payloads) rather than live production Meta WhatsApp Cloud API credentials. Live provider verification will occur in staging during Step 12.
2. **Audio Streaming Intelligence Deferred to Step 10:**
   The `VoiceSIPAdapter` correctly captures SIP signaling, duration, and consent disclosures. In accordance with the prompt (*"Do not prematurely implement STEP 10 speech-recognition or voice-generation intelligence"*), speech-to-text (ASR) transcription and text-to-speech (TTS) streaming are not executed in Step 03.
3. **Temporal Saga Orchestration for Distributed Commerce:**
   `OutboxService` provides database-level transactional durability, retries, and DLQ. Multi-step distributed transactions spanning payment gateways, ERPs, and warehouse logistics will be orchestrated by Temporal sagas starting in Step 07.

---

## 10. FINAL ACCEPTANCE GATE VERDICT

In accordance with the STEP 03 acceptance gate specification (*"PASS only if every configured channel ingests safely, persists before routing, deduplicates correctly, and human ownership/consent is unbypassable"*):

- **Every configured channel ingests safely:** Verified across WhatsApp, Email, WebChat, and Voice/SIP.
- **Persists before routing:** Proven by `InboundRawEvent` table persistence before normalizer dispatch.
- **Deduplicates correctly:** Proven by duplicate provider event replay returning `duplicate_ignored` with 0 side-effects.
- **Transactional Outbox & DLQ:** Proven by `OutboxService` retry backoff, DLQ exhaustion audit, and high-priority bypass.
- **Out-of-order message handling:** Proven by chronological timeline ordering and stale AI turn rejection.
- **Human ownership & consent unbypassable:** Proven by `StaleTurnError` on AI submission, atomic handoff, and multilingual STOP opt-out.
- **PostgreSQL 16 RLS & Webhook Tenant Context:** Proven on all 13 tables with live tests under unprivileged `sales_app_user`.
- **Provider Asset Binding (CRIT-01):** Proven by route URL parameter swap returning 403, unregistered assets returning 404, and deactivated integrations returning 403.
- **Connection Pool Context Hygiene (CRIT-02):** Proven by engine checkin hook resetting GUC context and subsequent pool checkout finding zero context and reading zero rows.
- **Selective STOP Cancellation (HIGH-01):** Proven by STOP directive purging only MARKETING messages while preserving TRANSACTIONAL, SERVICE, and SECURITY messages.
- **Outbox Concurrency & 3-Phase Leasing (MED-01):** Proven by claim token generation and transaction commit prior to external dispatch network callable, plus fencing token rejection of stale workers.
- **Domain Service Transaction Composability (MED-02):** Proven by `flush()` usage across ConversationService and clean atomic rollback of multi-operation transactions.
- **Canonical DB Parity:** Proven 100% identical between `infra/init-db.sql` and live active database.
- **Test Suite:** 153 passing assertions in 47.44s (100% pass, 0 failed, 0 skipped).

### **FINAL VERDICT: REMEDIATION ROUND 2 COMPLETE**

---

## 11. NEXT-STEP ELIGIBILITY

STEP 03 Round 2 critical remediation is complete and verified against live PostgreSQL 16.  
In accordance with strict project rules:  
**STEP 04 IS STRICTLY BLOCKED** until the independent Codex re-audit inspects `reports/STEP_03_REMEDIATION_ROUND_2.md` and issues an official PASS verdict.
