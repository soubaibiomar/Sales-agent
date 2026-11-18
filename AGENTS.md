# AGENTS.md — SALES AI MANAGEMENT PLATFORM INSTRUCTIONS

## 1. MISSION AND CORE ARCHITECTURAL INVARIANTS

You are working on the **Sales AI Management Platform**, a unified, multi-tenant enterprise SaaS platform delivering end-to-end sales, omnichannel communications, dual-mode voice AI (Customer Voice Agent and Manager Voice Copilot), CRM, inventory, quotation, order processing, procurement, logistics, support, and marketing automation.

### Absolute Non-Negotiable Invariants
1. **One Unified Platform**: There are no disconnected MVP releases or separate commercial versions (no V1/V2/V3 slicing). Sprints and steps are internal engineering checkpoints towards a single enterprise-ready production release.
2. **Deterministic Commercial Authority**: Domain services calculate prices, reserve stock, issue tax-compliant invoices, validate payments, execute state transitions, and enforce authorization. AI models and prompts only interpret intent, draft proposals, and request typed actions. No model, prompt, LLM agent, or n8n workflow is ever an authority for money, discounts, inventory levels, paid states, customer identity, or tenancy.
3. **PostgreSQL as Single Source of Truth**: PostgreSQL with Row-Level Security (RLS) is the authoritative operational truth. Redis is strictly ephemeral and rebuildable (used only for caching, rate limiting, and short-lived locks); it is never a second order, payment, or inventory ledger.
4. **Zero-Trust Multi-Tenancy**: Identity and tenant boundaries are established and verified server-side on every request. Never trust tenant IDs, actor IDs, or roles supplied in user prompts or client headers. Multi-tenancy is enforced at API, domain service, database RLS, document storage, RAG retrieval, cache namespaces, and asynchronous worker queues.
5. **Three Execution Classes**:
   - **Direct Safe Read**: Bypasses LLM; executes deterministic cached queries for order status, FAQ lookups, and tracking.
   - **Bounded Reasoning Turn**: Single-turn LLM reasoning via Model Gateway for drafting answers, summarizing, or proposing quotes; strictly bounded by typed schemas and output guards.
   - **Durable Workflow**: Long-running asynchronous operations (checkout, fulfillment, approvals, background synchronization) orchestrated by Temporal or equivalent stateful orchestrators.
6. **Dual-Mode Voice Architecture**:
   - **Customer Voice Agent**: Inbound customer calls and web voice; requires caller verification (e.g. OTP/PIN) prior to disclosing sensitive order/account data; protected against caller-ID spoofing.
   - **Manager Voice Copilot**: Authenticated management interface requiring session authentication, step-up MFA, and strict role authorization. Spoken commands cannot authorize high-risk mutations (e.g. wire payments, custom discounts > 25%, bulk deletions) without explicit second-factor UI confirmation.
7. **Temporal vs. Peripheral n8n**: Temporal owns transactional sagas, retries, and compensation logic. n8n is strictly peripheral (outbound marketing notifications, non-critical webhooks) and cannot independently mutate core commerce state.
8. **Fact-Checked Outputs**: All production claims made to customers (prices, stock availability, discounts, delivery dates) must be backed by fresh deterministic database evidence. Schema validation and deterministic claim checkers filter all AI outputs before delivery.
9. **Local Hardware & VRAM Mutual Exclusion**:
   - Hardware envelope: Intel Core i7-13620H, NVIDIA RTX 4060 Laptop (8GB VRAM), 16GB DDR5 RAM, Windows + Docker + Ollama (port 11434).
   - Default generation model: `qwen3.5:4b` (resident in GPU VRAM during interactive turns).
   - High-complexity reasoning model: `qwen3.5:9b-q4_K_M` (loaded on-demand only).
   - **Absolute Prohibition**: Never keep `qwen3.5:4b` and `qwen3.5:9b-q4_K_M` resident on the GPU simultaneously. When routing to 9B, 4B must be evicted from VRAM (`keep_alive: 0`); once 9B completes, it is evicted and 4B restored.
   - Auxiliary models (embeddings, reranker, ASR, TTS) run strictly on CPU to protect GPU VRAM for the active LLM. Moroccan Darija tools (`DarijaLID`, `Transliteration-Moroccan-Darija`, `moulsot.v0.3`) are loaded into RAM on demand.
   - All 18 agent roles share the single active LLM instance via distinct role prompts and tool definitions.
   - Real-time telemetry tracks host RAM, VRAM, latency (TTFT), and generation throughput (tok/s).
   - Multilingual voice and text must be tested across 5 distinct matrices: French (`fr-FR`), English (`en-US`), Arabic (`ar-MA`), Darija (`ary-Arab`), and Arabizi (`ary-Latn`).

---

## 2. AGENT ECOSYSTEM (18-ROLE CATALOG)

The 18 roles form a modular capability catalog, not 18 concurrently running processes:

| Role Category | Roles | Execution Model |
|---|---|---|
| **Front Door** | 1. Inbound Router & Intent Classifier | Deterministic regex/classifier + lightweight model gate |
| **Supervision** | 2. Conversation Supervisor | Manages turn state, active specialist handoffs, and human takeover |
| **Interactive Specialists** (9 roles) | 3. Discovery & Qualification Specialist<br>4. Product & Catalog Specialist<br>5. Quotation & Pricing Specialist<br>6. Order & Checkout Specialist<br>7. Inventory & Availability Specialist<br>8. Logistics & Tracking Specialist<br>9. Support & Issue Resolution Specialist<br>10. Appointment & Scheduling Specialist<br>11. Returns & Refunds Specialist | Invoked on-demand per turn within bounded schema; interacts via typed tool contracts |
| **Governed Background** (6 roles) | 12. Lead Enrichment Agent<br>13. Follow-up & Nurture Agent<br>14. Churn Risk & Retention Agent<br>15. Restock & Procurement Agent<br>16. Pricing Optimization Analyst<br>17. Conversation Quality Auditor | Dispatched via Temporal durable background queues; idempotent batch/event processing |
| **Internal Copilot** | 18. Sales Representative Copilot | Read-heavy internal copilot assisting human reps with briefs, objections, and draft quotes |

*Protective Components (Non-Autonomous)*:
- **Output Guard**: Deterministic schema validation, PII redaction, and hallucination checker.
- **Offline Quality Reviewer**: Asynchronous evaluation pipeline testing transcripts for prompt injection, safety, and brand compliance.

---

## 3. REPOSITORY DIRECTORY LAYOUT

```
Sales agent/
├── .env.example                     # Environment template (NO SECRETS)
├── .gitignore                       # Git exclusion rules
├── AGENTS.md                        # Master architectural instructions & rules
├── README.md                        # Project entry point & sprint overview
├── STEP_01_REPORT.md                # Root-level current step validation report
├── docs/                            # Architectural documentation
│   ├── adr/                         # Architecture Decision Records (ADR-001..ADR-010)
│   ├── architecture/                # C4 diagrams & DFD/STRIDE threat models (.mmd)
│   └── requirements/                # Traceability catalog & user journeys
├── security/                        # Security workbook, mappings & risk register
│   ├── CONTROL_INDEX.md             # Original 70 baseline control index
│   ├── SAI_EXTENSION.md             # 12 proposed AI/voice security extensions
│   ├── control-mapping.md           # Full traceability matrix (01-70 + SAI-01-12)
│   └── risk-register.md             # Comprehensive STRIDE & AI threat register
├── src/                             # Application source code
│   ├── backend/                     # FastAPI modular core
│   │   ├── api/                     # REST & WebSocket route handlers
│   │   ├── core/                    # Security, auth, config, database session
│   │   ├── domain/                  # Deterministic domain services (CRM, Catalog, etc.)
│   │   ├── models/                  # SQLAlchemy ORM models with RLS
│   │   └── schemas/                 # Pydantic schemas (typed I/O)
│   ├── ai/                          # Model Gateway, prompt templates, tool definitions
│   ├── voice/                       # WebRTC/SIP adapters, VAD, STT/TTS streaming
│   └── frontend/                    # Next.js/React management console & web widgets
├── tests/                           # Multi-tier test suite
│   ├── step01/                      # Step 01 automated validation suite
│   ├── unit/                        # Unit tests for domain logic & schemas
│   ├── integration/                 # Integration tests with PostgreSQL & Redis
│   └── security/                    # Penetration, BOLA, injection, and tenant escape tests
├── evidence/                        # Verifiable test logs, traces, and metrics
│   └── step-01/                     # Step 01 execution output & audit logs
└── reports/                         # Formal step acceptance reports
    └── step-01-report.md
```

---

## 4. DESIGN TOKENS & UI SPECIFICATION

The frontend UI follows an accessible enterprise standard:
- **Primary / Brand**: Deep Forest Green (`#0A3A2A`, hover `#064E3B`, light tint `#E6F4EA`)
- **Accent / Emerald**: Emerald Green (`#10B981`)
- **Neutral Background**: Crisp Neutral White (`#FFFFFF`), Soft Page Background (`#F8FAFC`)
- **Neutral Borders / Dividers**: Slate Muted (`#E2E8F0` / `#CBD5E1`)
- **Typography**: Inter / system sans-serif; high contrast ratio exceeding WCAG AAA (minimum 7:1 for normal text).
- **Surface Elevation**: Subtle borders and clean shadows (`box-shadow: 0 1px 3px rgba(0,0,0,0.05)`).
- **Status Indicators**:
  - Success / Approved: Forest Green (`#16A34A`)
  - Warning / Under Review: Amber (`#D97706`)
  - Critical / Failed: Crimson Red (`#DC2626`)
  - Informational: Slate Blue (`#2563EB`)

---

## 5. SECURITY GOVERNANCE & P0 LAUNCH BLOCKERS

### Strict Policy on 70 Baseline Controls + 12 SAI Extensions
- All original 70 controls from `70-security.xlsx` are tracked. Original workbook remains untouched.
- Reassessed priorities elevate AI tools (40), prompt injection (39), AI disclosure (65), AI output handling (66), excessive agency (67), and realtime endpoints (70) to **P0**.
- The 12 proposed SAI controls (voice verification, manager MFA, anti-spoofing, recording disclosure, multilingual injections, etc.) are mandatory requirements for the AI/Voice layers.

### P0 Launch Blockers (Zero-Tolerance)
1. Any cross-tenant data leakage or bypass of PostgreSQL RLS.
2. Any hardcoded secrets, exposed database credentials, or unredacted PII in logs.
3. Any financial transaction, stock deduction, or discount calculation executed directly by an LLM without domain service authorization.
4. Any unauthenticated access to manager voice actions or sensitive customer voice disclosures.
5. Any webhook processing without cryptographic HMAC signature validation and replay deduplication.

---

## 6. TERMINOLOGY: MEASURED VS. TARGET SLOS

To avoid fabricated claims or unverified assumptions, all engineering documentation must adhere to the following strict distinction:
- **Target SLO (Design Goal)**: The theoretical SLA/SLO specified in the architecture (e.g. "Target API latency p95 < 200ms", "Target Voice TTFT < 600ms").
- **Measured Metric (Verified Evidence)**: The actual observed result from an executed benchmark or load test, citing command, duration, concurrency, hardware, and raw log output (e.g. "Measured in Step 01 test suite: 12 passing assertions in 0.42s on Python 3.14").
- **Rule**: Never declare a Target SLO as "Passed" or "Verified" without an accompanying executed test run and evidence file.

---

## 7. DATA RETENTION & COMPLIANCE (MOROCCAN LAW 09-08 & GDPR)

1. **Consent & Disclosure**: All inbound and outbound voice calls must play an explicit recording and AI disclosure prior to bi-directional audio streaming.
2. **Customer Audio Retention**: Raw voice audio recordings are encrypted at rest (AES-256) in private S3 buckets with lifecycle policies purging files after 90 days.
3. **Transcripts & Redaction**: Transcripts undergo automated PII/PCI-DSS redaction (redacting credit card numbers, national IDs, and passwords) before indexing in pgvector/RAG. Transcripts are retained for 365 days unless earlier customer erasure is requested.
4. **Data Subject Rights**: Platform must support automated programmatic workflows for Data Subject Access Requests (DSAR), rectification, and complete tenant-scoped erasure.
