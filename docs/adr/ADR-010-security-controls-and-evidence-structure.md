# ADR-010: Security Controls Traceability, Verification, and Evidence Structure

## Status
Accepted

## Date
2026-11-18

## Context
Enterprise security audits and compliance certifications (SOC 2, ISO 27001, CNDP / Moroccan Law 09-08) require verifiable evidence of security controls rather than aspirational assertions. The platform incorporates 70 baseline security controls derived from the original STOKORA security workbook (`references/70-security.xlsx`) and 12 proposed AI/voice security extensions (`security/SAI_EXTENSION.md`). 

Without a rigorous evidence-based verification structure, controls remain theoretical, risks go unmitigated, and false passes compromise release security.

## Decision
1. **Preservation of Source Workbook**:
   - The original workbook (`references/70-security.xlsx`) is preserved as immutable source reference.
   - Original IDs (01 to 70), original priorities (35 P0, 24 P1, 11 P2), and original applicabilities (59 Applicable, 11 Conditional) are tracked without rewriting source historical facts.
2. **Sales AI Specific Reclassification**:
   - In `security/control-mapping.md`, every control receives an evaluated Sales AI priority and implementation target. Specifically, AI-related controls (39, 40, 65, 66, 67), payment/webhook controls (31, 32, 59), and realtime endpoints (70) are elevated to **P0** for this platform.
   - The 12 proposed SAI controls (SAI-01 to SAI-12) are formally integrated into the release gating framework.
3. **Evidence-Driven Verification Lifecycle**:
   - Control statuses follow a strict finite-state lifecycle:
     - `NON VERIFIE` (Initial unverified state)
     - `IN PROGRESS` (Implementation in flight)
     - `NOT RUN` (Test exists but unexecuted in current environment)
     - `FAIL` (Executed test failed assertion)
     - `PASS` (Executed automated test passed with recorded evidence file)
   - Under no circumstances is a control marked `PASS` based on code inspection alone. Every `PASS` must link to an executable test file, exact command line, execution timestamp, and output log in `evidence/`.
4. **Step-Gated Acceptance Architecture**:
   - The platform evolves across 12 sequential implementation steps (6 sprints).
   - Each step produces an authoritative acceptance report (`reports/step-XX-report.md` and `STEP_XX_REPORT.md` at root).
   - Progression to step N+1 is blocked if any P0 gate in step N fails.

## Invariants Enforced
- Zero tolerance for synthetic passes, fabricated benchmarks, or simulated audit results.
- Full two-way traceability: Requirement -> Domain Service -> Security Control -> Automated Test -> Evidence File.

## Consequences
### Positive
- Transparent, audit-ready compliance posture from day one.
- Clear technical accountability across engineering disciplines.
- Prevents regressions as complex AI and voice features are introduced.

### Negative / Trade-offs
- Demands disciplined test authoring and evidence logging on every step.
- Increases initial documentation overhead.

### Mitigation
- Provide automated testing scripts and verification utilities that validate the control mapping and evidence logs on every CI build.
