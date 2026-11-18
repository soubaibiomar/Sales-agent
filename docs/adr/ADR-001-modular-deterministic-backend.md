# ADR-001: Modular Deterministic Backend Architecture

## Status
Accepted

## Date
2026-11-18

## Context
The Sales AI Management Platform coordinates complex commercial operations including customer qualification, pricing calculations, discount approvals, stock reservations, order commitments, payment settlements, procurement, and warehouse logistics across web, chat, and voice channels. 

A common anti-pattern in AI-driven systems is granting LLMs, autonomous agents, or workflow engines direct write access to financial and operational ledgers, or breaking business domain services into dozens of independently deployed microservices prematurely, leading to distributed consistency anomalies, latency spikes, and unmanageable operational overhead.

## Decision
1. **Monolithic Modular Core**: Implement a cohesive, modular backend architecture using Python (FastAPI, Pydantic, SQLAlchemy) where domain services (CRM, Catalog, Pricing, Quotes, Orders, Payments, Inventory, Logistics, Approvals) exist as clearly separated internal modules within a unified process and database transaction boundary.
2. **Deterministic Domain Authority**: 
   - All calculations involving currency, discounts, taxes, margin requirements, inventory levels, and payment state machines are executed exclusively by deterministic domain services.
   - AI models, agents, and prompt pipelines never commit state or directly modify database records. They produce structured intent proposals (`ProposalPayload`) that are submitted to domain service APIs for validation, authorization, and transactional commitment.
3. **Transactional Integrity**: Financial and inventory state changes utilize PostgreSQL ACID transactions, pessimistic row locking (`SELECT FOR UPDATE`) or optimistic concurrency versioning, and transactional outbox events to guarantee consistency.

## Invariants Enforced
- No model, prompt, or external webhook can directly mark an invoice as paid, alter product catalog prices, or bypass discount approval policies.
- Every state transition generates an immutable audit log entry containing actor ID, tenant ID, timestamp, and signed transition evidence.

## Consequences
### Positive
- Prevents catastrophic commercial hallucinations (e.g. AI promising 90% discounts or selling phantom stock).
- High performance and low operational latency (<50ms for domain transactions).
- Simplified debugging, local testing, and deterministic replayability.

### Negative / Trade-offs
- AI agent tool definitions must adhere to rigid Pydantic schemas.
- Changes to commercial business rules require code updates and unit tests rather than simple prompt adjustments.

### Mitigation
- Provide clean, versioned internal Python APIs and typed tool definitions exposed through a centralized Tool Gateway.
