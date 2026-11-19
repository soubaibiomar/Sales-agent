# SALES AI MANAGEMENT — FRONTEND SCREEN INVENTORY & ARCHITECTURE MAP

## 1. OVERVIEW

The Sales AI Management Platform consists of 28 functional screen views in `src/frontend/`. Every screen belongs to a coherent operational domain, connects to the underlying FastAPI modular backend, and shares the unified application shell (sidebar, top header, breadcrumb, and tenant selector).

---

## 2. SCREEN INVENTORY TABLE

| # | Screen File | Domain / Family | Primary Visual Reference / Layout | Key Interactive Components & Functionality |
|---|---|---|---|---|
| **01** | `index.html` | Executive Overview | **Reference A (Dashboard)** | 4 Top KPI cards with sparklines, 5-stage pipeline funnel (`Prospection` → `Gagné`), revenue evolution spline chart, revenue breakdown donut, recent quotes & orders tables, AI Commercial Assistant with recommendations, live activity stream. |
| **02** | `inbox.html` | Omnichannel Communications | **Reference B (Omnichannel Inbox)** | 3-column workspace: filterable conversation list (WhatsApp, Email, Web, SMS), active timeline with AI Intent Detection card (98% confidence), customer vs dark-green AI bubbles, AI response suggestion chips, CRM deal context card with rapid actions (`Créer un devis`). |
| **03** | `quote_builder.html` | Commercial Quotations | **Reference C (Quotations Builder)** | 5 KPI metrics, sub-tabs (`Quotes`, `Orders`, `Approvals`), 3-column layout: customer selection & product catalog on left; quotation editor with line items, TVA 20%, totals in center; AI Sales Assistant & 3-stage approval workflow on right. |
| **04** | `pipeline.html` | Sales CRM & Pipeline | Pipeline & Deal Management | Visual Kanban board across sales stages, deal cards with win probability progress bars, estimated value in MAD, quick deal creation, drag-and-drop status update. |
| **05** | `catalog.html` | Product Catalog & Price Books | Grid / Table Workspace | Product catalog with SKU, Category, Stock status, Multi-currency pricing (MAD/EUR/USD), tier discounts, and new product modal. |
| **06** | `orders.html` | Orders & Fulfillment | Commercial Execution | Order lifecycle table (Pending, Confirmed, Shipped, Delivered), order line items, invoice generation trigger, and customer delivery tracking. |
| **07** | `approvals.html` | Commercial Governance | Two-Tier Approvals | Manager approval queue, rule threshold evaluation (`≥ 150 000 MAD` or discount `> 15%`), step-up MFA verification, approve/reject/delegate actions. |
| **08** | `inventory.html` | Warehouse & Stocks | Multi-Location Inventory | Warehouse stock levels (Casablanca, Tangier, Rabat), safety thresholds, low-stock alerts, transfer orders, and barcode lookup. |
| **09** | `procurement.html` | Procurement & Suppliers | Supplier Sourcing | Supplier directory (Morocco & International), purchase orders (PO), restock triggers, goods receipt notes, and supplier lead-time tracking. |
| **10** | `logistics.html` | Logistics & Dispatch | Shipping & Courier | Carrier integration (CTM Messagerie, Aramex, Ghazala), shipment manifest, tracking number generator, delivery status timeline. |
| **11** | `invoices.html` | Billing & Accounting | Moroccan Tax Ledger | Legal tax invoices, ICE / IF / RC tax compliance details, 20% TVA breakdown, PDF export, payment status ledger (Unpaid, Partial, Paid). |
| **12** | `checkout.html` | Digital Checkout & POS | Omnichannel Checkout | Cart checkout, payment gateway integration (CMI, Stripe, Wire Transfer, Cash on Delivery), order confirmation, and receipt generation. |
| **13** | `quote_view.html` | Customer Quote Portal | Public / Client View | High-fidelity interactive quote presentation for customers, item breakdown, digital signature pad, acceptance button, PDF download. |
| **14** | `support.html` | Customer Care & After-Sales | Support Ticketing & RMA | Support ticket queue, issue categorization, customer SLA timers, returns & RMA request processing, satisfaction rating. |
| **15** | `schedule.html` | Scheduling & Bookings | Commercial Calendar | Interactive appointment scheduler, sales rep availability slots, client booking form, Google/Outlook calendar sync. |
| **16** | `notifications.html` | Omnichannel Dispatcher | Notification Hub | Multi-channel dispatch center (WhatsApp templates, Email campaigns, SMS alerts), opt-out/STOP management, delivery receipts. |
| **17** | `integrations.html` | Connectors & Peripheral n8n | Integration Center | Third-party webhooks (WhatsApp Cloud API, CMI, n8n webhook triggers), HMAC secret configuration, sync logs, replay protection. |
| **18** | `workflows.html` | Durable Execution | Temporal Workflow Monitor | State machine viewer for long-running sagas (Checkout saga, Restock saga, Approval saga), step retries, compensation status. |
| **19** | `workflow_reliability_dashboard.html` | SRE & Workflow Health | Reliability Console | Dead-letter queue (DLQ) inspector, saga error rates, retry backoff graphs, incident alert triggers, and manual intervention triggers. |
| **20** | `ai_governance.html` | AI Safety & Policy | Model Gateway & Guardrails | Prompt injection detection logs, PII redaction audit, claim verification scorecard, RAG knowledge base sync, and latency percentiles. |
| **21** | `agent_workspace.html` | Multi-Agent Swarm | 18-Agent Ecosystem | Roster of 18 agent roles (Front Door, Interactive Specialists, Background Agents, Sales Copilot), live turn state, agent-to-agent handoffs. |
| **22** | `voice_agent.html` | Voice AI (Customer) | Inbound Call Center | WebRTC audio visualizer, caller verification (OTP/PIN), live speech transcript (Darija, Arabic, French, English), AI voice response player. |
| **23** | `voice_copilot.html` | Voice AI (Manager) | Privileged Voice Console | Manager voice command console, step-up MFA challenge, real-time query execution (Sales KPIs, pending approvals), voice telemetry. |
| **24** | `voice_observability.html` | Voice Telemetry | Real-Time Voice SRE | Audio latency (TTFT < 600ms target), VAD detection accuracy, G.711 / Opus codec metrics, SIP connection status, telephony call logs. |
| **25** | `analytics_dashboard.html` | BI & Observability | Executive Intelligence | Churn prediction heatmaps, sales rep quota leaderboard, customer acquisition cost (CAC), LTV analytics, cohort retention tables. |
| **26** | `ai_operations_dashboard.html` | Local AI Infrastructure | GPU & VRAM Telemetry | RTX 4060 VRAM monitor (8GB limit), Qwen 3.5 4B vs 9B mutual exclusion lock state, token generation throughput (tok/s), model load time. |
| **27** | `saas_admin_dashboard.html` | SaaS Multi-Tenancy | Multi-Tenant Administration | Tenant provisioning (`Atlas Commerce`, `Acme Corp`), tier limits, storage quotas, active user seats, PostgreSQL RLS audit status. |
| **28** | `release_console.html` | Release & QA Verification | Master Release Gate | Verification matrix of STEP 01–12, 381 automated test status, DR drill metrics, disaster recovery log, and production readiness certification. |

---

## 3. UNIFIED NAVIGATION MAPPING

All 28 screens are organized into the left sidebar under logical categories:

```
├── Tableau de bord (Dashboard) ── index.html
├── CRM & Ventes
│   ├── CRM & Opportunités ─────── pipeline.html
│   ├── Devis & Offres ─────────── quote_builder.html, quote_view.html
│   ├── Approbations ───────────── approvals.html
│   ├── Commandes ──────────────── orders.html, checkout.html
│   └── Rendez-vous ────────────── schedule.html
├── Catalogue & Opérations
│   ├── Catalogue Produits ─────── catalog.html
│   ├── Stocks & Entrepôts ─────── inventory.html
│   ├── Achats & Fournisseurs ──── procurement.html
│   └── Logistique & Expéditions ── logistics.html
├── Finance & Support
│   ├── Factures & Règlements ──── invoices.html
│   └── Support & Retours ──────── support.html
├── Communications & Omnicanal
│   ├── Boîte de réception IA ──── inbox.html
│   └── Notifications & Campagnes ─ notifications.html
├── Intelligence Artificielle & Voix
│   ├── Écosystème des 18 Agents ── agent_workspace.html
│   ├── Gouvernance IA & Sécurité ─ ai_governance.html
│   ├── Agent Vocal Client ─────── voice_agent.html
│   ├── Copilote Vocal Manager ─── voice_copilot.html
│   └── Télémétrie Vocale ──────── voice_observability.html
├── Workflows & Intégrations
│   ├── Workflows Durables ─────── workflows.html
│   ├── Fiabilité & Dead-Letter ── workflow_reliability_dashboard.html
│   └── Connecteurs & n8n ──────── integrations.html
└── Plateforme & Gouvernance
    ├── Analytics Exécutif ─────── analytics_dashboard.html
    ├── Opérations Modèles & VRAM ─ ai_operations_dashboard.html
    ├── Administration Multi-Tenant saas_admin_dashboard.html
    └── Console de Déploiement ─── release_console.html
```
