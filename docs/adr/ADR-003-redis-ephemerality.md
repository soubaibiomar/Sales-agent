# ADR-003: Redis Ephemerality, Caching, and Ephemeral Locks

## Status
Accepted

## Date
2026-11-18

## Context
High-throughput systems require fast caching, distributed rate-limiting, and short-lived synchronization primitives. However, architectures frequently suffer from "dual-write divergence" when Redis is treated as a secondary database or state store for orders, carts, stock counts, or payments. If Redis crashes, experiences eviction, or falls out of sync with the primary database, state corruption ensues.

## Decision
1. **Redis is Strictly Ephemeral and Rebuildable**:
   - Redis is designated exclusively for transient, non-authoritative data: read-through response caching, distributed sliding-window rate limiting, WebSocket pub/sub message distribution, short-lived idempotency tokens (TTL <= 24 hours), and distributed mutex locks (Redlock pattern with strict TTLs).
   - Redis must never store permanent business truth, financial balances, active stock reservations, or uncommitted shopping carts. If Redis is completely flushed or restarted (`FLUSHALL`), the system must recover fully from PostgreSQL without data loss or inconsistency.
2. **Cache Invalidation & Freshness**:
   - Cache keys must include the tenant identifier as a mandatory prefix: `{tenant_id}:cache:{domain}:{entity_id}`.
   - Cache invalidation occurs via PostgreSQL transactional outbox events or explicit domain service triggers upon entity mutation.
   - Financial quotes, active discount approvals, and inventory availability checks always query PostgreSQL directly or use strict, short-lived cache TTLs (<= 5 seconds) with immediate write-through invalidation.

## Invariants Enforced
- The system must be capable of executing all commercial transactions, checkout operations, and voice interactions with Redis temporarily unavailable (graceful degradation with reduced throughput).
- No uncommitted or business-critical state exists solely in Redis memory.

## Consequences
### Positive
- Zero risk of state drift or ghost inventory due to Redis persistence failures.
- Clean operational maintenance, cluster restarts, and simple scaling.
- Guarantees strict multi-tenant cache isolation via namespacing.

### Negative / Trade-offs
- Database reads for un-cached hot entities require efficient indexing in PostgreSQL.
- Distributed locks in Redis require strict lease timeouts to prevent deadlocks.

### Mitigation
- Maintain comprehensive PostgreSQL index coverage and connection pooling (HikariCP / SQLAlchemy asyncpg pool).
