# STEP 01 ACCEPTANCE REPORT: ARCHITECTURE, REQUIREMENTS AND THREAT MODEL

**Sprint:** 1 — Foundation  
**Step:** 01 — Architecture, Requirements, and Threat Model  
**Gate Verdict:** **PASS** (100% of Step 01 requirements verified with executed automated tests)  
**Execution Timestamp:** 2026-11-18T10:39:59Z  
**Environment:** Windows 11, Python 3.14.6, pytest 9.1.1, Git 2.47  
**Authoritative Location:** `C:\Users\omar\Documents\Sales agent`  

---

## 1. OBJECTIVE AND SCOPE REVIEW

The objective of Step 01 is to freeze one unified enterprise SaaS product architecture and establish authoritative trust boundaries, deterministic commercial authority, multi-tenant isolation, dual-mode voice AI governance, requirements traceability, and verifiable security controls before application implementation begins.

### Key Scope Delivered:
1. **Repository & Development Setup**: Initialized Git repository, established `.gitignore`, configured safe `.env.example` template with zero hardcoded credentials, and authored master `AGENTS.md`.
2. **Requirements Traceability**: Authored `docs/requirements/requirements-traceability.md` mapping 6 actors, 4 end-to-end user journeys, and 37 granular functional requirements across 17 business domains to named service owners, API contract routes, test IDs, and security controls.
3. **C4 Architecture & DFD/STRIDE Threat Models**: Produced 4 Mermaid architecture models in `docs/architecture/` covering Context, Containers, Components, and 8 critical Trust Boundaries.
4. **Architecture Decision Records (ADRs)**: Authored 10 foundational ADRs (`docs/adr/ADR-001` through `ADR-010`) establishing non-negotiable architectural invariants.
5. **Security Baseline & Extension Traceability**: Authored `security/control-mapping.md` auditing all 70 baseline controls from `references/70-security.xlsx` (preserving original facts) and integrating the 12 proposed Sales AI extensions (`SAI-01` to `SAI-12`).
6. **Threat & Risk Register**: Authored `security/risk-register.md` modeling 12 critical risks across STRIDE and AI vectors and formalizing 8 P0 Launch Blockers.
7. **Automated Verification**: Implemented and executed a 20-test automated validation suite in `tests/step01/` passing 100% in 0.42s with logs preserved in `evidence/step-01/test_run.log`.

---

## 2. INSPECTED BASELINE AND GIT STATE

### Pre-Execution State
- **Directory**: `C:\Users\omar\Documents\Sales agent`
- **Existing Content**: Unzipped prompt pack in `Sales_AI_Management_12_Implementation_Prompts/` containing prompts, references (`70-security.xlsx`, `Sales_AI_Management_Unified_Architecture.pdf`, `Sales_AI_Management_Unified_Architecture.tex`), and security indexes.
- **Git State**: Uninitialized (`fatal: not a git repository`).
- **Dependencies & Tools**: Python 3.14.6, Node.js v24.18.0, npm 11.16.0, Docker 29.9.3, pytest 9.1.1, openpyxl, pydantic, sqlalchemy, fastapi.

### Modifications & Normalization
- Initialized local Git repository via `git init`.
- Mirrored core reference folders (`prompts/`, `references/`, `security/`, `README.md`) to the repository root to ensure direct root-relative path resolution.
- Verified that original `references/70-security.xlsx` remains completely intact and unmodified (70 rows, 35 P0, 24 P1, 11 P2, 59 Applicable, 11 Conditional, all `NON VERIFIE`).

---

## 3. ARCHITECTURE DECISIONS SUMMARY (ADR-001 TO ADR-010)

| ADR ID | Title | Status | Core Architectural Invariant Enforced |
|---|---|---|---|
| **ADR-001** | Modular Deterministic Backend Architecture | Accepted | Domain services calculate prices, reserve stock, and commit payments. AI models only request typed proposals. |
| **ADR-002** | PostgreSQL Truth & Row-Level Security (RLS) | Accepted | PostgreSQL is the single source of truth. RLS enforced on all tenant tables. Integrated pgvector shares identical tenant security context. |
| **ADR-003** | Redis Ephemerality & Ephemeral Locks | Accepted | Redis is strictly rebuildable cache, rate limiter, and short-lived lock (Redlock <= 30s); never an order or inventory ledger. |
| **ADR-004** | Three-Path AI Execution & Intent Routing | Accepted | Three execution classes: Direct Safe Read (<50ms, non-LLM), Bounded Reasoning Turn (single-turn LLM with typed tools), Durable Workflow (Temporal). |
| **ADR-005** | Dual-Mode Voice Architecture | Accepted | Separate pipelines: Customer Voice Agent (untrusted Caller-ID, OTP verification for private data) vs. Manager Voice Copilot (OIDC session, MFA, no spoken high-risk mutations). |
| **ADR-006** | Authorization & Multi-Tenant Isolation | Accepted | Server-side OIDC/JWT validation; contextvars propagation; failure by default (deny-all); zero trust in client headers. |
| **ADR-007** | Temporal Workflow Ownership & Peripheral n8n | Accepted | Temporal orchestrates commercial checkout sagas and stock expiration timers. n8n is strictly peripheral (outbound marketing/notifications) and read-only. |
| **ADR-008** | Encrypted S3 Storage & Data Retention | Accepted | Private S3 buckets with time-limited pre-signed URLs (<=15m); automated 90-day audio purge (GDPR / Moroccan Law 09-08 compliance). |
| **ADR-009** | Model Gateway, Tool Security & Provider Isolation | Accepted | Centralized Model Gateway with PII redaction, multilingual prompt injection filters (Darija/Arabic/French/English), and deterministic Output Guard claim checking. |
| **ADR-010** | Security Controls Traceability & Evidence Structure | Accepted | Verifiable evidence-based audit structure; all 70 baseline controls + 12 SAI extensions tracked; zero unverified passes. |

---

## 4. DETAILED IMPLEMENTATION & DELIVERABLES

### 4.1 Master Governance (`AGENTS.md`)
Created root-level master instruction set establishing:
- 8 Absolute Non-Negotiable Invariants.
- 18-Role Agent Ecosystem Catalog (Front Door, Supervision, 9 Interactive Specialists, 6 Governed Background Agents, 1 Internal Copilot).
- Deep-Green (`#0A3A2A`) and Neutral White (`#FFFFFF`) UI Design Tokens exceeding WCAG AAA contrast (>= 7:1).
- Measured vs. Target SLO terminology distinction rules.
- Data retention and privacy compliance mandates (Moroccan Law 09-08 / GDPR).

### 4.2 C4 Architecture & Threat Models (`docs/architecture/`)
- `context.mmd`: System context showing Users, Ingress Channels, Sales AI Core, and External Providers (Stripe, Twilio, LLMs, Meta WhatsApp).
- `containers.mmd`: Application container architecture (FastAPI Business Core, Voice Gateway, Model Gateway, Temporal Engine, PostgreSQL+pgvector, Redis Cluster, MinIO/S3, Peripheral n8n).
- `components.mmd`: Component breakdown showing API controllers, security middleware, 9 domain services, outbox publisher, supervisor, 9 specialists, prompt injection filter, PII redactor, Tool Gateway, and Output Guard.
- `trust-boundaries.mmd`: Data Flow Diagrams (DFD) and STRIDE mitigations across 8 critical trust boundaries.

### 4.3 Requirements Traceability (`docs/requirements/requirements-traceability.md`)
- 6 Actors: Customer (`ACT-01`), Sales Rep (`ACT-02`), Support/Ops (`ACT-03`), Manager (`ACT-04`), Tenant Admin (`ACT-05`), Platform Admin (`ACT-06`).
- 4 Core End-to-End User Journeys detailed step-by-step.
- 37 Granular Requirements (`REQ-IAM-01` to `REQ-SEC-02`) mapped to service owners, API routes, test IDs, and security controls.

### 4.4 Security Mapping & Risk Register (`security/`)
- `security/control-mapping.md`: Comprehensive traceability matrix tracking all 70 original controls and 12 SAI extensions.
- `security/risk-register.md`: 12 comprehensive STRIDE/AI threat scenarios, inherent/residual risk ratings, mitigation controls, monitoring strategies, and 8 explicit P0 Launch Blockers.

---

## 5. SECURITY CONTROL MAPPING & AUDIT STATUS

### Baseline Controls (01 to 70)
- **Original Workbook Baseline (`references/70-security.xlsx`)**: 70 controls | P0 = 35, P1 = 24, P2 = 11 | 59 Applicable, 11 Conditional | All 70 = `NON VERIFIE`.
- **Sales AI Reassessment**:
  - Elevated to **P0**: Controls `31` (Webhook signatures), `32` (Frontend-only payments), `39` (Prompt injection), `40` (AI tool permissions), `59` (Webhook replay prevention), `65` (AI sensitive data disclosure), `66` (Unsafe AI output), `67` (Excessive AI agency), `70` (Realtime/WebSocket security).
  - Reclassified as **N/A**: Control `18` (NoSQL injection) due to pure relational PostgreSQL + pgvector architecture.
- **Workbook Integrity Verified**: Verified programmatically using `openpyxl`; 0 cells modified in source workbook.

### Proposed AI/Voice Extensions (SAI-01 to SAI-12)
- All 12 proposed controls incorporated with designated component owners, implementation mechanisms, verification test IDs, and target execution steps.

---

## 6. EXECUTED TEST EVIDENCE

### Execution Command
```powershell
python -m pytest tests/step01 -v
```

### Raw Output Log (Saved at `evidence/step-01/test_run.log`)
```
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\omar\AppData\Local\Python\pythoncore-3.14-64\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\omar\Documents\Sales agent
plugins: anyio-4.14.2, arize-phoenix-client-3.5.0, deepeval-4.2.5, asyncio-1.4.0, repeat-0.9.4, rerunfailures-16.7, xdist-3.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 20 items

tests/step01/test_architecture_consistency.py::test_all_10_adrs_exist_and_accepted PASSED [  5%]
tests/step01/test_architecture_consistency.py::test_c4_mermaid_diagrams_exist PASSED [ 10%]
tests/step01/test_architecture_consistency.py::test_c4_container_diagram_includes_key_containers PASSED [ 15%]
tests/step01/test_architecture_consistency.py::test_trust_boundaries_diagram_covers_all_8_threat_domains PASSED [ 20%]
tests/step01/test_architecture_consistency.py::test_risk_register_covers_stride_and_launch_blockers PASSED [ 25%]
tests/step01/test_repo_hygiene.py::test_gitignore_exists_and_contains_critical_patterns PASSED [ 30%]
tests/step01/test_repo_hygiene.py::test_env_example_has_no_real_secrets PASSED [ 35%]
tests/step01/test_repo_hygiene.py::test_agents_instructions_completeness PASSED [ 40%]
tests/step01/test_repo_hygiene.py::test_no_hardcoded_private_keys_in_repo PASSED [ 45%]
tests/step01/test_requirements_traceability.py::test_requirements_file_exists PASSED [ 50%]
tests/step01/test_requirements_traceability.py::test_actors_coverage PASSED [ 55%]
tests/step01/test_requirements_traceability.py::test_core_user_journeys_coverage PASSED [ 60%]
tests/step01/test_requirements_traceability.py::test_voice_modes_explicit_requirements PASSED [ 65%]
tests/step01/test_requirements_traceability.py::test_all_requirements_have_service_owners_apis_tests PASSED [ 70%]
tests/step01/test_requirements_traceability.py::test_major_business_domains_covered PASSED [ 75%]
tests/step01/test_security_controls.py::test_control_mapping_file_exists PASSED [ 80%]
tests/step01/test_security_controls.py::test_excel_workbook_integrity PASSED [ 85%]
tests/step01/test_security_controls.py::test_baseline_controls_traceability_in_mapping PASSED [ 90%]
tests/step01/test_security_controls.py::test_sai_extension_controls_traceability PASSED [ 95%]
tests/step01/test_security_controls.py::test_priority_reclassifications_for_sales_ai PASSED [100%]

============================= 20 passed in 0.42s ==============================
```

### Verification Matrix
| Test Suite File | Test Scenario Description | Invariants & Controls Verified | Status |
|---|---|---|---|
| `test_requirements_traceability.py` | Validates file existence, 6 actors, 4 journeys, voice requirements, 37 entries, domains | REQ-IAM through REQ-SEC | **PASS** |
| `test_security_controls.py` | Validates 70 baseline controls, 12 SAI extensions, Excel integrity (35 P0, 24 P1, 11 P2) | Controls 01-70, SAI-01-12 | **PASS** |
| `test_architecture_consistency.py` | Validates 10 ADRs accepted, 4 Mermaid diagrams, 8 trust boundaries, STRIDE risks | ADR-001-010, STRIDE | **PASS** |
| `test_repo_hygiene.py` | Validates `.gitignore`, safe `.env.example`, `AGENTS.md` rules, no private keys/secrets | Controls 01, 02, 03, 13 | **PASS** |

---

## 7. MEASURED VS. TARGET SLOS

In accordance with architectural invariant #6 (AGENTS.md), theoretical design targets are strictly decoupled from observed test measurements:

| Metric Category | Target SLO (Design Goal) | Measured Metric (Step 01 Verified Evidence) | Status |
|---|---|---|---|
| **Step 01 Test Execution Time** | Suite completes in < 5.0s | **0.42 seconds** (20 passing assertions on Python 3.14.6) | Verified |
| **Excel Baseline Integrity** | 100% cell integrity (70 rows) | **100% intact** (35 P0, 24 P1, 11 P2, all NON VERIFIE) | Verified |
| **Requirements Completeness** | 100% of 17 domains mapped | **37 granular requirements** mapped to owners & tests | Verified |
| **Hardcoded Secrets Found** | 0 secrets in repository | **0 detected** (Automated regex scan across all files) | Verified |
| **API p95 Response Latency** | Target: Direct Read < 50ms, Domain API < 200ms | *Not applicable for Step 01* (Architecture step; benchmark in Step 02) | Target Only |
| **Voice Streaming TTFT** | Target: Audio Time-To-First-Token < 600ms | *Not applicable for Step 01* (Audio engine benchmark in Step 10) | Target Only |

---

## 8. FIVE TECHNICAL QUESTIONS & IN-DEPTH ARCHITECTURAL ANSWERS

### Q1: Why must financial calculations, stock deductions, and discount approvals remain strictly in deterministic domain services rather than being handled by LangGraph agents or LLM prompts?
**Answer**: Large Language Models are probabilistic next-token predictors susceptible to hallucinations, jailbreaks, prompt injection, and stochastic variability. Permitting an LLM to directly evaluate discounts or write database records introduces catastrophic commercial vulnerability—such as an attacker coaxing an agent to accept a $1 quote for a $10,000 order or overselling limited warehouse stock. In our architecture, the LLM operates strictly within a "Bounded Reasoning Turn" producing a structured `ProposalPayload`. The deterministic Pricing Service evaluates this proposal against hardcoded business rules, active database pricing tables, and user discount limits. If a 30% discount is requested, the domain service halts automatic commitment and dispatches an approval task to the Sales Manager. The LLM interprets conversational intent; the deterministic domain service governs money, inventory, and legal commitment.

### Q2: How does Row-Level Security (RLS) in PostgreSQL protect against Broken Object Level Authorization (BOLA / IDOR) compared to standard application-level filters?
**Answer**: Application-level filtering relies on software engineers consistently appending `WHERE tenant_id = :tenant_id` to every query across hundreds of REST endpoints and ORM models. A single missing predicate in an update, delete, or join exposes data across tenants (OWASP API Top 10 #1). With PostgreSQL RLS (`ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`), isolation is enforced by the database engine itself. When our FastAPI security middleware authenticates a request, it executes `SET LOCAL app.current_tenant_id = :tenant_id;` within the transaction block. Even if a buggy application query executes `SELECT * FROM quotes WHERE id = :quote_id`, PostgreSQL filters the row set so that only records matching the session's active tenant ID are returned. If an attacker guesses another tenant's UUID, PostgreSQL returns zero rows, preventing unauthorized data disclosure.

### Q3: What is the exact security rationale for segregating the Customer Voice Agent from the Manager Voice Copilot, and why can spoken commands never authorize high-risk mutations?
**Answer**: Customer and manager voice sessions operate under fundamentally divergent trust boundaries. Customer voice ingress originates from public PSTN telephony or untrusted web clients where Caller-ID (ANI) can be trivially spoofed using standard VoIP softphones. If caller-ID were trusted, an attacker could call in pretending to be a CEO and exfiltrate private customer orders or shipping addresses. Hence, the Customer Voice Agent treats caller-ID as untrusted and enforces secondary OTP verification before disclosing sensitive records. Conversely, the Manager Voice Copilot has access to executive revenue analytics and approval workflows. However, voice audio is vulnerable to synthetic voice cloning (deepfakes), acoustic eavesdropping, and accidental approvals in noisy environments. Therefore, spoken voice is architecturally restricted to read operations and drafting proposals. High-risk mutations (discounts > 25%, refunds > $500, user deletions) require explicit visual confirmation and second-factor authentication on the manager's dashboard.

### Q4: Why is Temporal designated as the authoritative engine for transactional sagas, while n8n is strictly relegated to peripheral automations?
**Answer**: Sagas like e-commerce checkout involve multi-step, distributed, asynchronous state transitions: reserving inventory, charging credit cards, generating sequential tax invoices, decrementing stock ledgers, and scheduling shipping dispatch. If a network blip occurs during card charging, the reserved stock must be released deterministically, or compensation logic must execute. Temporal provides a durable, code-first state machine with event-sourced execution histories, guaranteed retries with exponential backoff, and bulletproof compensation sagas. In contrast, n8n is a visual low-code workflow tool designed for external webhook orchestration and notifications. Low-code visual workflows lack robust database-level ACID transaction guarantees, type safety, and transactional outbox patterns. If n8n managed financial truth, an accidental drag-and-drop edit or unhandled exception could leave orders paid but unfulfilled or stock permanently locked. Thus, n8n only receives outbound transactional events to format external marketing alerts.

### Q5: How does the platform achieve Moroccan Law 09-08 and GDPR compliance regarding call audio recordings and customer transcripts?
**Answer**: Both Moroccan Law 09-08 (CNDP) and GDPR mandate explicit consent, purpose limitation, storage minimization, and data subject rights (access, rectification, erasure). We satisfy these through four architectural controls:
1. **Consent & Disclosure**: All inbound and outbound calls trigger an immediate automated disclaimer ("This call is recorded and assisted by an AI agent for service quality") prior to bi-directional streaming.
2. **Automated Audio Lifecycle**: Raw audio files stored in private S3 buckets are subject to an automated S3 Lifecycle Rule that permanently purges recordings after 90 days.
3. **PII Masking on Transcripts**: Before transcripts are indexed in PostgreSQL or pgvector for RAG, an automated redaction engine strips credit card numbers, passwords, national identification numbers (CIN), and Moroccan phone numbers.
4. **Programmatic DSAR Workflows**: Data Subject Access Requests trigger an automated database deletion cascade scoped to the customer's identifier across all operational tables and vector stores.

---

## 9. OUTSTANDING RISKS AND LIMITATIONS

1. **Local Infrastructure Deployment (Pre-Step 02)**: PostgreSQL, Redis, and MinIO are defined architecturally but will be provisioned as live Docker Compose services during Step 02.
2. **OIDC Provider Dependency**: Production authentication relies on Keycloak or managed OIDC; local mock token generators are utilized for isolated contract testing until Step 02.
3. **Multilingual Dataset Calibration**: While prompt injection defense is architected for Darija, Arabic, and French, production tuning of the classifier model will occur in Step 08.

---

## 10. FINAL ACCEPTANCE VERDICT & NEXT-STEP ELIGIBILITY

- **Overall Step 01 Verdict**: **PASS**
- **Criteria Evaluation**:
  - All major business domains and both voice modes have documented boundaries and named service owners: **MET**.
  - All 70 baseline controls and 12 SAI extensions traced with zero duplicate IDs and source Excel untouched: **MET**.
  - 10 foundational ADRs accepted and aligned with C4/DFD architecture diagrams: **MET**.
  - 20 executable automated tests executed with 100% pass rate in 0.42s: **MET**.
  - Zero hardcoded secrets, no fabricated SLO claims, and strict repository hygiene: **MET**.

### Next-Step Eligibility
**STEP 02 (Secure Infrastructure, Identity, and Tenancy)** is fully eligible to proceed upon explicit user authorization.
