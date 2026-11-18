# ADR-004: Three-Path AI Execution and Intent Routing

## Status
Accepted

## Date
2026-11-18

## Context
Routing every customer message, web chat turn, or voice utterance through heavy multi-agent LLM reasoning graphs introduces unacceptable latency, excessive token costs, unpredictable behavior, and expanded attack surfaces. Conversely, simple static chatbots fail to handle nuanced commercial discovery, objections, or multi-step checkout negotiations.

## Decision
1. **Three Execution Classes**:
   - **Path A: Direct Safe Read (Deterministic / Non-LLM)**:
     - For high-frequency, deterministic queries: order tracking by ID, store hours, standardized returns policy FAQs, appointment slot availability lookups.
     - Routed directly to domain read APIs or cached responses.
     - Latency: < 50ms; Token cost: $0; Risk: Zero hallucination.
   - **Path B: Bounded Reasoning Turn (Single-Turn LLM with Typed Tools)**:
     - For interactive conversational dialogue: product recommendations, objection handling, lead qualification, conversational quote generation.
     - Managed by the Conversation Supervisor and a single active domain Specialist (from the 9 interactive roles).
     - Bound by rigid Pydantic input/output schemas, Model Gateway safety checks, and deterministic Output Guards.
     - Latency: 500ms - 1500ms; Risk: Controlled by tool contracts and claim checkers.
   - **Path C: Durable Workflow (Stateful Orchestration via Temporal)**:
     - For asynchronous, multi-step, transactional operations: order payment processing, procurement purchase order placement, cross-channel notification dispatch, multi-day lead nurture sequences, supervisor approval escalations.
     - Orchestrated by Temporal with durable execution, exponential backoff retries, and compensation/rollback logic.
2. **Intent Classification & Confidence Gating**:
   - Inbound messages pass through an Inbound Router & Intent Classifier.
   - If intent confidence < 0.85 or input triggers adversarial safety filters, the conversation is routed to safe deterministic fallbacks, clarification prompts, or human agent escalation.

## Invariants Enforced
- High-risk operations (e.g. charging a credit card or confirming an order) can only be initiated via Path C (Durable Workflow) and never completed directly inside a Path B reasoning loop.
- One active conversation owner per version; human rep takeover immediately silences automated agent responses.

## Consequences
### Positive
- Minimizes token consumption and operational cost by 60-80% for routine queries.
- Guarantees sub-second response times where deterministic data is requested.
- Provides unbreakable boundary between conversational drafting and transactional execution.

### Negative / Trade-offs
- Router classification must be maintained and calibrated as new domains are added.
- Requires dual testing: deterministic tests for Path A & C, evaluation benchmarks for Path B.

### Mitigation
- Maintain automated intent classification test suites with adversarial test cases across English, French, and Darija/Arabic.
