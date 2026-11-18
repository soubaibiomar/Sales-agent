# Sales AI Management — 12 Detailed Codex/Agent Implementation Prompts

## What this ZIP contains
- `prompts/00_MASTER_PROMPT.md`: universal architecture, security, coding, validation and reporting contract.
- `prompts/STEP_01_...md` through `STEP_12_...md`: 12 **independent ready-to-paste execution prompts**, organized as six sprints, two steps each.
- `security/CONTROL_INDEX.md`: a traceability index for the **original 70 workbook controls**, not a proof of implementation.
- `security/SAI_EXTENSION.md`: 12 additional proposed security controls for this AI/voice product.
- `references/Sales_AI_Management_Unified_Architecture.pdf`: the previously produced 20-page unified architecture.
- `references/Sales_AI_Management_Unified_Architecture.tex`: editable architectural source.
- `references/70-security.xlsx`: original uploaded workbook (kept unchanged).

## How to use with Codex / another coding agent
1. Unzip into your **project repository root**, ideally preserving directory names. If the repo already has `prompts`, `security` or `references`, merge carefully without overwriting existing files blindly.
2. Start a fresh agent task and paste **`prompts/STEP_01_ARCHITECTURE_REQUIREMENTS_THREAT_MODEL.md`**. It explicitly tells the agent to read the master prompt and references. Alternatively pre-load the master prompt as the root agent instructions (`AGENTS.md`), but only after reviewing it.
3. Let the agent INSPECT → PLAN → IMPLEMENT → TEST → FIX → DOCUMENT → VALIDATE, then STOP. Inspect `reports/step-01-report.md` and evidence; require real PASS.
4. Paste STEP 02 only after the blocking dependencies from STEP 01 have passed. Continue sequentially through STEP 12.
5. A single **complete product** is released after STEP 12. These are engineering checkpoints, **not 12 product versions**.

## Six sprints / twelve steps
| Sprint | Steps | Scope |
|---|---|---|
| 1 — Foundation | 01 Requirements/threat model; 02 IAM, tenancy, infrastructure | Secure ground truth |
| 2 — Sales | 03 Omnichannel; 04 CRM/catalog/pricing/quote/approval | Customer to quotation |
| 3 — Operations | 05 Orders/payments/reservations; 06 Procurement/warehouse/logistics/support | Quote to delivery and after-sales |
| 4 — Intelligence | 07 Events/workflows/notifications; 08 Model Gateway/RAG/Tools | Resilient bounded intelligence |
| 5 — AI + Voice | 09 Full 18-role catalog; 10 Dual customer/manager voice | Complete agent and voice ecosystem |
| 6 — Completion | 11 Analytics/forecasting/SaaS/UX; 12 Full integration/security/load/DR | One final acceptance/release |

## Acceptance policy
- `PASS`: proven with executed tests, evidence and controls.
- `PARTIAL`: progress exists but some mandatory scope or gate is incomplete.
- `FAIL`: a blocking invariant/test has failed.
- `BLOCKED`: required environment/access/input prevents completion.
- `NOT RUN`: test state only, never count it as PASS.

Every step generates `reports/step-XX-report.md`, evidence paths, security mapping, positive/negative test logs, and at least 5 technical Q&A. Do not accept synthetic success reports or invented benchmark values.

## Source priority
1. Explicit current user instructions and safety.
2. Actual source architecture PDF/TEX and original workbook for their stated facts.
3. Existing verified repo behavior / executed tests.
4. This prompt pack's proposed implementation details (modify only via documented ADR and review).

Prepared on 2026-11-17. Do not mistake project planning details for a completed deployment or passed security audit.
