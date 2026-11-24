# 12 — Final Project Verdict

This is an independent **engineering assessment, not a certification**.
- **Inspected HEAD:** `1a74c491901d17a6b1c185756440200113ccb218` (24 commits, 2026-11-18 → 2026-11-19).
- **Inspection date:** 2026-11-24.

## Release-readiness verdict: **NO-GO (FAIL)**
Ten P0 defects are open. Seven of them were confirmed by runtime exploitation on isolated data. Four of the five AGENTS.md launch blockers are violated; the fifth is open for payment and telephony webhooks. A P0 like this overrides any numerical score.

## Weighted scorecard (`weighted_scorecard.csv`)
| Category | Weight | Score | Basis |
|---|---:|---:|---|
| Functional completeness | 15 | 5.5 | Service-level domain core real and tested. Payments, carriers, voice, tools and integrations simulated. UI not wired. |
| Architecture quality | 12 | 5 | Clean modular monolith with good money/state design. Temporal, OIDC, worker and pgvector missing; RLS unusable by the app. |
| Application and infrastructure security | 18 | 3 | Good primitives (hashing, TOTP crypto, channel HMAC), but multiple exploitable auth/MFA/webhook bypasses, default secrets, no TLS/CI. |
| Database integrity and multi-tenancy | 10 | 5 | FORCE RLS on 79 tables with correct policies and fail-closed reads. Cross-tenant FKs, excess grants, missing constraints, superuser template. |
| AI agents and RAG | 10 | 2.5 | Real Ollama and embeddings available. Tools fabricated, guard fail-open, generic agent, deterministic "evaluations". |
| Voice AI | 8 | 1 | VAD/G.711/session logic only. STT/TTS placeholders; OTP and step-up bypassed; latency claim computed. |
| Frontend UI/UX | 10 | 4.5 | Visually close to the agreed identity. No auth, mostly static, broken by its own CSP, 6 nav variants, mobile overflow. |
| Testing quality | 8 | 3 | 381 tests pass and cover real logic; tests encode bypasses, a tautological assertion, non-hermetic shared DB, no UI tests. |
| Deployment and reliability | 6 | 1.5 | Local compose only; no manifest, CI, TLS, worker; fake readiness. |
| Documentation and maintainability | 3 | 1.5 | Extensive docs/ADRs/runbooks, but key reports overstate results. |
| **Total** | **100** | **32.5** | |

**To score higher:** close groups A–C of report 11 (≈ +25), wire the UI and the worker (≈ +10), and deliver real STT/TTS with measured latency (≈ +5).

## Answers to the 15 questions
1. **What did Gemini actually implement?**
   - A FastAPI/PostgreSQL modular monolith: 84 tables with RLS, a credible service-level commerce core, and channel ingestion with signed webhooks and an outbox.
   - An agent/voice *framework* with fixture tools and placeholder speech.
   - 28 polished static HTML mock-up pages.
   - 381 passing tests.
   - Many documents and reports.
2. **Is the project genuinely functional?**
   - At service and API level for the commerce domains, yes, when run with RLS bypassed.
   - As a product a user can log into and operate end to end, **no**.
3. **Which steps are fully implemented?**
   - Only **Step 01** (documentation).
   - Steps 03, 06 and 11 are PARTIAL.
   - Steps 02, 04, 05, 07, 08, 09, 10 and 12 FAIL their gates (report 02).
4. **What is incomplete or simulated?**
   - Payments, refunds (provider side), carriers, WhatsApp/email/SMS outbound, SIP/WebRTC, n8n.
   - STT and TTS.
   - All AI tool results; the sales copilot brief; AI "evaluations".
   - The workflow runtime (no worker), Temporal.
   - Login UI and most screens' data.
5. **Is the architecture respected?**
   - The deterministic-authority principle is respected *in the domain code*. The AI layer cannot mutate state.
   - Deviations without an ADR: Temporal, OIDC, Next.js, pgvector, and the RLS runtime contradiction.
   - Invariant 8 (fact-checked claims) is violated by fixture evidence and the fail-open guard.
6. **Are the 18 agents operational?**
   - **No.** They are registered metadata on one generic `BaseAgent` with keyword-triggered fixture tools. Conversation ownership and human takeover do work.
7. **Is RAG real?**
   - Partly. It uses real `embeddinggemma` embeddings when Ollama answers in time, with a silent MD5 fallback.
   - No pgvector; ACL roles can be supplied by the client.
   - Generation is not grounded.
8. **Does Voice AI work end to end?**
   - **No.** There is no microphone capture, ASR returns a constant string, and TTS produces sine waves.
   - The 518–569 ms figure is computed from constants, not measured.
9. **Does the frontend match the agreed previews?**
   - Visually it is close to the written identity: forest-green sidebar, white/neutral workspace, emerald highlights. The dashboard, inbox and quote layouts match the brief.
   - The three reference images were not found to compare pixel-wise.
   - Functionally it is a mock-up, and served by the backend it breaks under the CSP.
10. **Are the 70 + 12 controls enforced?**
    - **No.** Baseline: 14 PASS, 18 PARTIAL, 28 FAIL, 9 NOT VERIFIED, 1 N/A.
    - SAI: 0 PASS, 3 PARTIAL, 8 FAIL, 1 NOT VERIFIED.
11. **Are the previous test and benchmark claims reliable?**
    - The test count is reproduced.
    - The voice latency, "82/82 verified", "approved for production" and AI-accuracy claims are **not reliable**.
    - The load and DR numbers were not re-verified.
12. **What are the most serious problems?**
    - F-01 unauthenticated cross-tenant access.
    - F-02 forgeable payments.
    - F-03 refund abuse.
    - F-04/F-06 MFA bypasses.
    - F-05 OTP backdoor.
    - F-07/F-08 fabricated AI evidence with a fail-open guard.
    - F-09 RLS unusable at runtime.
    - F-10 default secrets.
13. **Ready for an academic demonstration?**
    - **Yes, conditionally.** Demo the domain core (tests/API), the architecture docs, and the UI design through a static server, and state clearly which parts are simulated.
    - Do not present the voice latency, the control matrix or "production approved" as facts.
14. **Ready for paying customers?** **No.**
15. **What must be fixed before production?**
    - All of report 11 group A, then B, C and F, the essential parts of E (auth UI, wiring, CSP), and an independent re-audit.
    - Voice (group D) is needed before any voice feature is offered.

## Credit where due
- **Money:** exact integer/`Decimal` arithmetic.
- **State machines:** versioned and locked with `FOR UPDATE`.
- **Approvals:** anti-self-approval and terms-hash invalidation.
- **Channel webhooks:** per-integration HMAC plus asset binding, persist-before-route, deduplication, out-of-order handling.
- **Outbox:** leasing with `SKIP LOCKED` and fencing tokens.
- **RLS:** policies correct and forced, fail-closed reads; the app role has no superuser or BYPASSRLS.
- **Credentials:** PBKDF2 plus timing defense and lockout; AES-GCM-encrypted TOTP seeds.
- **PII redaction** in transcripts and LLM output.
- **Telephony primitives:** a real G.711 codec and VAD.
- **Design:** a coherent visual identity.

## Integrity of this inspection
- **No application source, test, migration or document outside the two output folders was modified.**
- **One side effect was reverted:** running the existing suite rewrote `evidence/step-10/multilingual_voice_evaluation.json`; I restored it with `git checkout`.
- **One side effect remains:** the suite added synthetic test rows to the dev database (+2 tenants etc.); no existing rows were deleted. A pre-inspection dump exists in the scratchpad.
- No commits, pushes, container deletions or destructive tests.
- Secrets are redacted in all deliverables.
- **Tools used:**
  - bash/PowerShell, git, docker and psql;
  - Python with openpyxl, httpx ASGITransport and psycopg;
  - Ollama HTTP API and nvidia-smi;
  - headless Microsoft Edge for screenshots;
  - the Claude built-in browser (console and DOM inspection).
- **Not available:** gitleaks, pip-audit, bandit, Playwright, axe.
- **Skills:** none of the installed skills were invoked. The review was done directly with the tools above.
