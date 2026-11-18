# ADR-009: Centralized Model Gateway, Tool Security, and Provider Isolation

## Status
Accepted

## Date
2026-11-18

## Context
Directly embedding proprietary LLM vendor SDKs (OpenAI, Google Gemini, Anthropic) across business modules creates vendor lock-in, bypasses centralized security monitoring, risks prompt injection attacks, leaks customer PII to external third parties, and prevents granular cost/quota controls (Baseline Controls 39, 40, 65, 66, 67; SAI-07, SAI-09, SAI-10, SAI-12).

## Decision
1. **Centralized Model Gateway Architecture**:
   - All AI interactions pass exclusively through an internal, stateless Model Gateway service.
   - Domain services and LangGraph agents interact with the Model Gateway using vendor-agnostic Pydantic request/response interfaces.
   - Gateway capabilities:
     - Multi-provider routing (Gemini 1.5 Pro/Flash, Claude 3.5 Sonnet, GPT-4o, local Ollama fallbacks).
     - Automated fallback and retry logic upon vendor rate limits or outages.
     - Token tracking, latency monitoring, and per-tenant budget quota enforcement.
2. **Pre-Inference Security & PII Redaction (SAI-09)**:
   - Inbound prompts pass through an automated PII redaction layer that masks credit card numbers, tax IDs, passwords, and sensitive Moroccan/international personal identifiers before sending payloads to external cloud LLM providers.
3. **Multilingual Prompt Injection Defense (SAI-10)**:
   - Dedicated regex, heuristic, and embedding classifiers evaluate incoming user prompts for jailbreaks, prompt injection, and delimiter hijacking across English, French, Standard Arabic, and Moroccan Darija (Arabizi and Arabic script).
4. **Typed Tool Gateway with Least Privilege (SAI-07)**:
   - Tools are exposed to LLMs as strongly-typed JSON schema functions.
   - LLM cannot generate arbitrary code or execute shell commands.
   - The Tool Gateway validates tool arguments with Pydantic, injects the verified server-side `SecurityContext`, and routes execution to domain services.
5. **Deterministic Output Guard (Baseline 66, SAI-08)**:
   - Before an LLM response is returned to the user or committed to a draft, the Output Guard verifies:
     - Schema conformity.
     - Price & stock claim verification: any mentioned numerical prices, discounts, or stock status must match fresh database query facts attached in the tool execution context. If a discrepancy is detected, the claim is blocked or corrected.

## Invariants Enforced
- External LLM provider downtime never halts core transactional processing or order fulfillment.
- No raw prompt input reaches an external provider without PII inspection.
- LLM outputs containing hallucinated financial promises cannot be transmitted to customers.

## Consequences
### Positive
- Total vendor independence and ability to switch models with zero code refactoring.
- Centralized audit logging of all prompt/completion pairs, tool invocations, and token expenditure.
- Effective protection against prompt injection across multiple languages.

### Negative / Trade-offs
- Adds small latency overhead (10-30ms) for preprocessing and output guard validation.
- Requires maintaining PII redaction regexes and adversarial prompt filters.

### Mitigation
- Benchmark gateway overhead to ensure p95 latency remains under 35ms.
