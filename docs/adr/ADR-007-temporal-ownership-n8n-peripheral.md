# ADR-007: Temporal Workflow Ownership and Peripheral n8n Integration

## Status
Accepted

## Date
2026-11-18

## Context
Enterprise sales pipelines involve long-running business processes: customer onboarding, asynchronous payment webhooks, stock reservation expiration timers (e.g. 15-minute checkout hold), multi-tier discount approval escalations, procurement supplier purchase orders, and multi-channel fulfillment tracking. 

Using ad-hoc cron jobs, arbitrary database poller threads, or visual low-code automation tools (such as n8n) to manage financial state transitions and critical sagas creates unmonitored failure states, race conditions, duplicate charges, and untraceable data corruptions.

## Decision
1. **Temporal as Master Workflow Orchestrator**:
   - Temporal is designated as the authoritative engine for all business-critical, long-running, multi-step sagas:
     - Checkout & payment settlement (reserving inventory, charging gateway, creating invoice, updating ledger, rolling back on failure).
     - Stock reservation release timers (releasing held stock back to available pool if order unpaid after expiration).
     - Multi-tier quote approval escalations (notifying managers, auto-expiring quotes).
     - Procurement order generation and logistics fulfillment dispatch.
   - Temporal workflows are written in deterministic Python code, versioned with workflow versioning primitives, and executed by dedicated workers.
   - All state mutations within workflow activities execute via the authoritative domain service APIs using transactional outbox events and idempotency keys.
2. **n8n Restricted to Peripheral Automation**:
   - n8n is strictly positioned as a peripheral notification and external integration utility (e.g. posting lead notifications to an external Slack channel, forwarding marketing contacts to external CRM sheets, triggering marketing newsletter syncs).
   - **Non-Negotiable Restriction**: n8n workflows possess **read-only** or strictly scoped non-financial event listener roles. n8n cannot independently mutate inventory, change order statuses, issue refunds, or authorize payments.

## Invariants Enforced
- Financial and inventory state machines are never controlled by n8n.
- All Temporal workflows are strictly idempotent; replaying an activity with the same transaction ID will never result in duplicate billing or double-decrementing stock.

## Consequences
### Positive
- Resilient distributed sagas with guaranteed compensation (rollback) upon payment failure or downstream service outages.
- Complete visual observability of active business workflows via Temporal UI.
- Prevents rogue or insecure changes by low-code operators affecting core financial truth.

### Negative / Trade-offs
- Requires running and maintaining Temporal cluster infrastructure (or managed cloud).
- Developers must adhere to Temporal's deterministic execution constraints (no non-deterministic time, random numbers, or direct network calls inside workflow logic).

### Mitigation
- Isolate all side-effects and external network calls inside Temporal Activities.
- Run lightweight local Temporal development server via Docker Compose during development and testing.
