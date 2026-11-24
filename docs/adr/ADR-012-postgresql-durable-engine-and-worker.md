# ADR-012: PostgreSQL-backed workflow engine and platform worker as interim Temporal substitute

- **Status:** Accepted (interim), supersedes the *implementation* part of ADR-007 until Temporal is adopted
- **Date:** 2026-11-24
- **Context source:** independent inspection finding F-19 (`reports/claude-inspection/`)

## Context
ADR-007 assigns long-running transactional workflows to Temporal. The codebase never
integrated Temporal: sagas run in-process through `src/backend/workflows/engine.py`
(state persisted in `workflow_executions` / `workflow_step_logs`), and until this ADR no
process ran anything outside HTTP requests, so outbox events were never relayed and
expired stock reservations were never released.

## Decision
1. The PostgreSQL-backed `WorkflowEngine` is the accepted **interim** durable engine.
   Its guarantees are limited to: persisted execution/step state, idempotency keys,
   reverse compensation, and operator-triggered recovery (`/api/v1/workflows/recovery/resume`).
2. A separate process, `python -m src.backend.worker` (`src/backend/worker.py`), runs the
   periodic jobs per tenant under Row-Level Security:
   - outbox relay (SKIP LOCKED leases + fencing tokens → safe with several workers);
   - stock reservation expiry (row locks).
3. Outbound delivery fails closed: without a registered channel provider the worker never
   marks an event as delivered; events retry and dead-letter.
4. n8n stays peripheral (ADR-007 unchanged on that point).

## What this does NOT provide (vs. Temporal)
- Durable timers / long sleeps, workflow versioning, deterministic replay, heartbeating
  activities and automatic resumption of a saga interrupted mid-step.
- Automatic crash recovery of RUNNING executions (still operator-triggered, because the
  engine cannot yet distinguish a crashed run from one in progress on another worker).
- Scheduled background-agent jobs (no job queue yet).

## Consequences
- Production use requires running at least one worker process next to the API.
- Re-evaluate before pilot customers: adopt Temporal, or add execution leases +
  heartbeats to the PostgreSQL engine and make recovery automatic.
