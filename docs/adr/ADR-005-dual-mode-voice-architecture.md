# ADR-005: Dual-Mode Voice Architecture (Customer Voice vs. Manager Copilot)

## Status
Accepted

## Date
2026-11-18

## Context
Voice AI provides transformative value for both inbound customer engagement (phone/web calls for inquiries, orders, appointments) and internal executive management (spoken analytics briefings, hands-free approvals, pipeline reviews). However, customer and manager voice interactions operate under fundamentally distinct threat models, trust boundaries, and authorization levels (SAI-01, SAI-02, SAI-03, SAI-04, SAI-05). Treating voice as a single generic pipeline invites catastrophic privilege escalation, caller-ID spoofing, and unauthorized data disclosure.

## Decision
1. **Architectural Separation of Voice Modes**:
   - Both modes share the underlying streaming media foundation (SIP/WebRTC, VAD, STT, TTS, Model Gateway) and query the same deterministic business core, but operate with strictly isolated session managers, authorization pipelines, and tool access boundaries.
2. **Customer Voice Agent (Mode 1)**:
   - **Inbound Context**: WebRTC web audio or SIP telephony (Twilio/FreeSWITCH).
   - **Identity & Trust**: Inbound Caller-ID (ANI) is treated as untrusted metadata (subject to spoofing).
   - **Verification Gate (SAI-01)**: Public catalog questions require no verification. However, prior to disclosing sensitive PII, order tracking, shipping addresses, or payment status, the customer must complete secondary verification (SMS OTP sent to registered number, or account PIN entry).
   - **Recording & Consent (SAI-04)**: Automated mandatory legal disclaimer played immediately upon connection ("This call is recorded and assisted by an AI agent for quality and sales service").
3. **Manager Voice Copilot (Mode 2)**:
   - **Authenticated Management Context**: Initiated exclusively from authenticated executive/manager sessions (web console or mobile app with active OIDC JWT).
   - **Step-Up MFA (SAI-02)**: Accessing voice copilot requires valid manager credentials + active MFA verification.
   - **Spoken Action Limitation (SAI-02)**: Managers may query real-time analytics, pipeline velocity, forecast reports, and draft approval requests via voice. However, **spoken voice alone cannot authorize high-risk actions** (e.g. approving discounts > 25%, initiating refunds > $500, wire disbursements, bulk user deletion). High-risk actions require explicit two-factor visual confirmation on the management dashboard.
4. **Anti-Spoofing & Audio Safety (SAI-03, SAI-05)**:
   - Telephony rate-limiting, silence-timeout disconnection (30s max silence), and audio packet sequence analysis to prevent SIP trunk flooding and automated audio injection.

## Invariants Enforced
- Under no circumstances can a customer voice session invoke manager-scoped tools, query cross-customer analytics, or bypass OTP verification for account disclosures.
- Raw voice audio recordings are encrypted at rest with AES-256 and purged automatically after 90 days (GDPR / Moroccan Law 09-08 compliance).

## Consequences
### Positive
- Prevents vishing (voice phishing) and unauthorized account takeovers via spoofed phone numbers.
- Prevents accidental or coerced high-value financial commitments via spoken audio.
- Ensures compliance with telecommunications and privacy regulations.

### Negative / Trade-offs
- Customer experience requires a brief OTP verification step when inquiring about private orders.
- Managers cannot execute 100% hands-free critical financial approvals while driving.

### Mitigation
- Streamline OTP verification (e.g. 4-digit code delivered via WhatsApp or SMS in <3 seconds).
