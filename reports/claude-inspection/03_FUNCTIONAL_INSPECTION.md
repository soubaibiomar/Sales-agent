# 03 — Functional Inspection

Status of every module: `module_implementation_status.csv`.

## What the product actually is
A **well-structured FastAPI + PostgreSQL commerce back-end**, with real, tested service-level logic for:
- CRM, catalog and pricing
- quotes and approvals
- orders and inventory
- invoicing, procurement, support and scheduling

Around it sits a **high-fidelity HTML mock-up front-end** and an **AI/voice layer that is mostly scaffolding**: generic agent, fixture tools, placeholder speech. The domain core is the strongest part of the codebase. The AI, voice and integration claims are the weakest.

## Domain summary
| Domain | Classification | Notes |
|---|---|---|
| CRM, leads, accounts, contacts, opportunities | Implemented and functional (service/API) | Pipeline UI renders an empty board when served (CSP). |
| Catalog / pricing / tax / discounts | Implemented and functional | Integer cents with `Decimal`, `ROUND_HALF_UP`; float multiplication raises `TypeError` (`money.py:74`). |
| Quotations, versions, approvals | Partially integrated | Terms hash and anti-self-approval are good; MFA bypass (F-04); public accept (F-14). |
| Orders / state machine | Functional (service) | Optimistic `version` + `FOR UPDATE`. No DB-level unique constraint on `quote_id`. |
| Payments | **Simulated** | Intents get fake IDs; there is no provider call; webhook forgeable. |
| Refunds | Partially integrated | Marked COMPLETED with a fake `re_…` ID; no cumulative cap. |
| Invoices | Functional (service) | Numbering and hash present; immutability not enforced in the DB. |
| Suppliers / RFQ / PO / receipts | Functional (service) | Over-receipt checks tested. |
| Warehouses / reservations / transfers | Partially integrated | Reservation expiry requires a saga that nothing schedules. |
| Logistics / tracking | Simulated | Carrier simulator and Amana adapter return generated events. |
| Support / warranty / RMA | Functional (service) | — |
| Scheduling | Functional (service) | Overlap checked in code; no exclusion constraint. |
| Model Gateway | Partially integrated | Real Ollama inference works warm; fabricated fallback (F-16). |
| RAG | Partially integrated | Real `embeddinggemma` when reachable, MD5 fallback otherwise; ACL issue. |
| Router / supervisors | Partially integrated | Keyword router; turn fencing and human takeover tested. |
| Tool Gateway / ClaimVerifier / OutputGuard | Simulated / fail-open | F-07, F-08. |
| 18 agents / Sales Copilot | Scaffolding / simulated | F-17. |
| Customer Voice Agent | Simulated | F-05, F-15. |
| Manager Voice Copilot | Partially integrated | KPI reads from the DB work; actions are simulated. |
| Workflows / sagas / outbox / DLQ | Partially integrated | No worker (F-19). |
| Notifications | Partially integrated | Consent, STOP, quiet hours and caps are coded; no channel provider; API unauthenticated. |
| n8n | Scaffolding | F-33. |
| Analytics / forecasting | Partially integrated | Real SQL; in-sample backtest. |
| SaaS tiers / quotas / metering | Partially integrated | Service functions; not enforced on AI/voice calls. |
| Tenant admin / users | Partially integrated | Login only works when RLS is bypassed (F-09). |

## External integrations
| Integration | Classification |
|---|---|
| WhatsApp Business | ADAPTER ONLY (signature verification + payload parsing; no outbound send) |
| Gmail / email | ADAPTER ONLY |
| SMS / OTP delivery | NOT IMPLEMENTED (OTP is never delivered) |
| Payment provider (Stripe "sandbox") | LOCAL SIMULATION |
| Carriers (Amana, simulator) | LOCAL SIMULATION |
| Twilio / SIP / PSTN | ADAPTER ONLY (signature helper; no media) |
| n8n | ADAPTER ONLY (stub) |
| Ollama | **LIVE VERIFIED** (local, this inspection) |
| embeddinggemma | LIVE VERIFIED for availability; whether RAG actually used it versus the fallback is NOT VERIFIED per run |

## End-to-end journeys
| Journey | Result | Evidence / simulated stages |
|---|---|---|
| A — Lead → … → Delivery | **PARTIAL** | `test_scenario_a…` passes at service level on in-memory SQLite. Payment and carrier are simulated. Not reachable through the UI (no login) or under RLS. |
| B — Message → Supervisor → Specialist → RAG → Tool → Grounded answer | **FAIL (simulated)** | Tool answers are fixtures; guard fails open (SEC-PROBE-10/12). |
| C — Ticket → Warranty → RMA → Inspection → Restock/refund | **PARTIAL** | `test_scenario_c…` passes at service level; the refund step has no provider call. |
| D — Manager → Copilot → Data → Preview → Authorization | **FAIL** | Data reads are real. Authorization accepts any 6 characters; "execute" is a no-op (SEC-PROBE-06). |
| E — Tenant A → Tenant B denied | **FAIL** at API level / **PASS** at raw RLS level | SEC-PROBE-01 (header fallback). `cross_tenant_fk_probe.json` shows reads are isolated but FK cross-references are allowed. |
| F — Workflow interruption → restart → no duplicates | **PARTIAL** | `test_crash_recovery…` and `test_scenario_e…` pass in-process. There is no worker to kill, so a real crash is not testable. |
| G — Browser mic → STT → LLM → TTS → playback | **FAIL** | No `getUserMedia` in the UI. STT returns a constant string; TTS produces sine waves. |
| H — Transaction → analytics → dashboard | **PARTIAL** | Analytics SQL reads real tables. The executive dashboard (`index.html`) makes 0 API calls (static numbers). |
