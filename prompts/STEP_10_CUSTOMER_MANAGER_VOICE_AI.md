# STEP 10 IMPLEMENTATION PROMPT — DUAL-MODE CUSTOMER AND MANAGER VOICE AI

**Sprint:** 5 — Voice  
**Objective:** Deploy secure real-time multilingual customer voice assistance and separately authenticated manager voice copilot.  
**Entry criteria:** STEP 09 PASS; tested tenant policy, agents, business tools and human handoff.

## Mandatory instructions for this execution
1. Read `prompts/00_MASTER_PROMPT.md` fully; then inspect the reference PDF, original 70-control workbook, repository root instructions, prior step reports and code. When these files are not already in your working repository, locate this ZIP's `references/` directory, copy/reference them without rewriting source facts, and record the location.
2. Work **only on this step**. This is one complete target product delivered at the end of STEP 12; steps are engineering validation checkpoints, not versions, MVPs or public releases.
3. Implement and run tests rather than writing a speculative implementation plan. Keep prior behavior intact. Make minimal coherent changes; use mocks/fixtures where external services are unavailable and label them explicitly.
4. Every claimed result must have a command, output/log, environment, and source artifact. DO NOT claim to have run unexecuted benchmarks, provider calls, integration tests or security controls.
5. Never push, release, provision billable infrastructure, call customers, send campaigns, connect production accounts or expose environments without explicit user authorization. Never read or publish real production secrets.
6. Stop after the step's final report and gate verdict. Do not start another step even if current work passed.

## Exact implementation scope
1. Create replaceable phone/SIP/WebRTC providers with signature-authenticated call events, secure media, streaming session ID, voice activity detection, barge-in/turn-taking, interrupt cancellation, STT, TTS and provider fallback.
2. Implement language/intent routing for Darija Arabic and Latin/Arabizi, Arabic, French, English and code switching; collect **consented and rights-cleared** labeled evaluation audio, preserving language boundaries.
3. Customer mode: explicit AI disclosure, verified customer identity before sensitive order/account data, permitted product/quote/order/support/booking tools, state-change confirmation and human transfer.
4. Manager mode: authenticated web/phone binding, MFA/step-up, authorized KPI/report reads and approval initiation; voice itself never signs or completes high-risk actions.
5. Implement call ownership, redacted transcripts, recording-off-by-default unless approved, consent retention policy, fraud/rate controls, callback queues, observability and accessible voice controls.

## Invariants and architectural constraints
- Caller ID, voice matching and spoken affirmations cannot establish privileged authorization.
- Customer and manager voices share core services but not permission grants or session credentials.
- No fabricated recording-consent, language benchmark or live-telephony result; provider simulation labeled.

## Required executable validation
1. Voice session signature/replay, malformed media and denial of service, call flood quotas, cross-call context leakage.
2. Spoofed caller ID, replayed audio, synthesized speech and attempted manager high-risk approval bypass.
3. Multilingual evaluated audio with explicit sample counts, WER/intent/policy outcomes, confusion/fallback by language and code switching.
4. Human takeover while speaking, network/STT/TTS outage, interruption and callback creation; evidence of current domain facts.

## Required deliverables and artifacts
- `services/voice-gateway`
- `integrations/telephony`
- `ai/voice and multilingual evaluation assets/metadata`
- `apps/web-manager voice copilot UI`
- `tests/voice/*`
- `evidence/step-10/`
- `reports/step-10-report.md`

## Security control traceability
**Controls specifically relevant to this step:** 04–07, 28, 35, 39–40, 49, 55, 63–67, 70; SAI-01–SAI-05, SAI-09–SAI-12.

Review and link these to tests and evidence. Do not assume other baseline controls are exempt: keep project-wide P0 gates and dependencies under review. If a control is missing or not applicable to this step, explain why and who owns its later validation.

## Acceptance gate
**PASS only if customer disclosure requires verification, manager voice cannot execute high-risk decisions, privacy/handoff and adversarial multilingual tests are evidenced.**

Set `PASS / PARTIAL / FAIL / BLOCKED` according to executed evidence, record any checks as `NOT RUN`, and do not automatically proceed. A blocking prerequisite or unverified critical requirement prevents PASS.

## Mandatory report (write the file, don't merely describe it)
Create `reports/step-10-report.md` with sections: objective; inspected baseline/Git state; plan and architecture decisions; detailed implementation/files and API/data contracts; original-vs-current comparison; security control mapping/evidence; positive, negative, adversarial and regression commands/results; screenshots if UI was changed; performance/cost if measured; **at least five technical questions with complete answers**; outstanding risks; PASS/PARTIAL/FAIL/BLOCKED verdict; next-step eligibility. End by returning a concise report and exact evidence paths to the user.
