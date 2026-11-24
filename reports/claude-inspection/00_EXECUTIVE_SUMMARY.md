# Sales AI Management — Independent Inspection: Executive Summary

This is an engineering assessment, not a certification. Every statement comes from code that was read or commands that were executed. Evidence is in `evidence/claude-inspection/`.

- **Git HEAD:** `1a74c491901d17a6b1c185756440200113ccb218` (24 commits). No application files were modified.
- **Environment:**
  - PostgreSQL 16.15 (container `sales-ai-postgres`), Redis 7, MinIO.
  - Ollama with `qwen3.5:4b`, `qwen3.5:9b-q4_K_M` and `embeddinggemma`.
  - Python 3.14.6.
  - i7-13620H, RTX 4060 Laptop 8 GB, 16 GB RAM.

## Verdict
| Use | Verdict |
|---|---|
| Release / paying customers | **NO-GO** |
| Academic demonstration | **Conditional yes** (simulated parts must be disclosed) |
| Score | **32.5 / 100** (`weighted_scorecard.csv`) |

The earlier Step 12 claims — "APPROVED FOR PRODUCTION RELEASE", "82/82 controls verified, 0 unresolved P0s" and "measured voice latency 518–569 ms" — are contradicted by the evidence.

## Key numbers
- **Tests:** **381 / 381 pass** (326 s, real PostgreSQL + Ollama). They pass *with* every P0 below present; some tests assert the bypasses.
- **Routes:** 199 total, **45 without authentication**.
- **Controls:** baseline 01–70 → 14 PASS / 18 PARTIAL / 28 FAIL / 9 NOT VERIFIED / 1 N/A. SAI-01–12 → 0 PASS / 3 PARTIAL / 8 FAIL / 1 NOT VERIFIED.
- **Steps:** 01 PASS; 03, 06, 11 PARTIAL; 02, 04, 05, 07, 08, 09, 10, 12 FAIL.
- **Findings:** 34 (10 P0, 12 P1, 11 P2, 1 P3) — `findings_register.csv`.
- **Real inference (4B):** cold TTFT 15.2 s; warm 0.67–0.74 s at ~65 tok/s.
- **Real inference (9B):** cold TTFT 27.6 s at ~38 tok/s. 4B and 9B were never co-resident, but that was enforced by Ollama's own scheduler, not by the project code.

## P0 defects
Seven were confirmed by runtime PoC on a throwaway database (`security/runtime_security_probes.json`); F-04, F-09 and F-10 are from code review plus database checks.

| ID | Defect |
|---|---|
| F-01 | Unauthenticated cross-tenant read/write through a client-supplied `X-Tenant-ID` header. |
| F-02 | Payment webhook secret is a constant in Git → forged event marks an order PAID. |
| F-03 | Refund approval: "MFA" taken from a client header; 300 % refunded; idempotency key ignored; self-approval allowed. |
| F-04 | Quote approval: any `mfa_code` counts as verified. |
| F-05 | Customer voice: static OTP `123456` always accepted. |
| F-06 | Manager voice: any 6-character "TOTP" accepted; action tokens usable across tenants; "execute" does nothing. |
| F-07 | AI tools return hardcoded fixtures (any order = PAID, stock = 15). |
| F-08 | OutputGuard passes unverified price, discount and payment claims when there is no evidence. |
| F-09 | RLS is correct but unusable: under the least-privileged role, login, webhooks and quote acceptance see 0 rows, so the working configurations are the superuser template (RLS bypassed) or SQLite (no RLS). |
| F-10 | Default JWT, MFA and webhook secrets with no production guard. |

## What is real
- Exact money arithmetic.
- Versioned, locked order/quote state machines.
- Anti-self-approval and terms-hash checks.
- Channel webhook HMAC and deduplication.
- Outbox leasing.
- Correct, forced RLS policies.
- Password, lockout and TOTP-crypto primitives.
- G.711 codec and VAD.
- A polished visual design close to the agreed forest-green identity.

## What is simulated or missing
- Payments, carriers, outbound channels, SIP/WebRTC, n8n.
- STT (constant text) and TTS (sine waves).
- AI tools and copilot output.
- AI "evaluations" (rule checks only).
- Temporal and any worker process.
- OIDC.
- Login UI and data wiring on 13 of 28 pages.
- A deployable stack: no dependency manifest, no CI, no TLS.

## Deliverables
| Report | Topic |
|---|---|
| 01 | Architecture, with Mermaid diagrams |
| 02 | Traceability |
| 03 | Functional inspection and journeys A–H |
| 04 | Security |
| 05 | Database and multi-tenancy |
| 06 | AI, RAG and model benchmarks |
| 07 | Voice |
| 08 | Frontend, with screenshots |
| 09 | Tests |
| 10 | Performance and deployment |
| 11 | Remediation plan |
| 12 | Verdict and answers to the 15 questions |

CSV registers: `findings_register.csv`, `security_control_assessment.csv`, `requirements_traceability.csv`, `module_implementation_status.csv`, `weighted_scorecard.csv`.

## Not done
- **Not executed:**
  - Platform load benchmark and DR drill (both write to the shared database).
  - Migration runner.
  - Dependency vulnerability scan (no manifest; pip-audit unavailable).
  - gitleaks scan; the git-history secret scan was regex only.
  - Accessibility tooling.
  - Real audio test (no STT/TTS exists).
- **Not available:** the three agreed preview images were not found on disk; the visual comparison uses the written design specification instead.
