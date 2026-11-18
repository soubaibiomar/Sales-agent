# PROPOSED SALES AI SECURITY EXTENSIONS

These controls are **new recommendations**, not rows originally present in the 70-security workbook. Security owner must validate acceptance and applicability before production.

| ID | Proposed control | Suggested priority |
|---|---|---|
| SAI-01 | Verify customer identity before voice disclosure of sensitive customer/order information | P0 |
| SAI-02 | Enforce manager session authentication, MFA/step-up and separate authorization for privileged voice actions | P0 |
| SAI-03 | Mitigate caller-ID spoofing, synthetic voice impersonation and replay fraud | P0 |
| SAI-04 | Govern call disclosure, recording policy, consent and transcript retention | P0 |
| SAI-05 | Protect streaming voice media and detect telephony abuse/fraud | P0 |
| SAI-06 | Scope RAG, memory and retrieved documents to authorized tenant and per-document ACL | P0 |
| SAI-07 | Use least-privilege typed tools, short-lived scoped credentials and server-side authorization | P0 |
| SAI-08 | Validate all AI-suggested prices, amounts, inventory and payment claims via authoritative services | P0 |
| SAI-09 | Assess AI/STT/TTS provider privacy, data retention, geography and subprocessors | P1 |
| SAI-10 | Continuously test Darija, Arabic, French, English and mixed-script multilingual prompt attacks | P0 |
| SAI-11 | Implement secure human takeover/handoff with minimum context and auditable ownership | P1 |
| SAI-12 | Version model, prompt, agent and tool updates with security regression release gates | P1 |

Priority reassessment suggestion: original AI-related controls 39, 40, 65–67 and realtime 70 should be treated as P0 for this product; payment/webhook controls 31–32 and 59 similarly become P0 when those functions are enabled. Keep source columns unchanged.
