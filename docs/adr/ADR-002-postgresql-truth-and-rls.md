# ADR-002: PostgreSQL as Single Source of Truth with Row-Level Security (RLS)

## Status
Accepted

## Date
2026-11-18

## Context
In a multi-tenant SaaS application managing enterprise sales, quotation contracts, customer PII, and financial ledgers, tenant data isolation and transactional consistency are critical. Relying purely on application-level `WHERE tenant_id = :tenant_id` query filters is prone to developer oversight, ORM bypasses, and Broken Object Level Authorization (BOLA / IDOR) vulnerabilities (Baseline Controls 05, 06, 33, 49).

## Decision
1. **PostgreSQL as Authoritative Truth**: PostgreSQL is the sole system of record for all business entities (tenants, users, leads, opportunities, products, pricing rules, quotes, orders, invoices, payments, inventory, audit logs).
2. **Row-Level Security (RLS) Enforcement**:
   - Enable Row-Level Security (`ENABLE ROW LEVEL SECURITY`) and enforce it strictly (`FORCE ROW LEVEL SECURITY`) on all tenant-partitioned database tables.
   - Establish tenant context at database connection/transaction initialization using PostgreSQL session variables: `SET LOCAL app.current_tenant_id = :tenant_id;`.
   - Implement database policies ensuring queries automatically restrict reads and writes to rows where `tenant_id = current_setting('app.current_tenant_id', true)::uuid`.
   - Global platform administrators or cross-tenant maintenance operations require explicit elevated roles that bypass RLS only under strict, audited conditions.
3. **Integrated Vector Search**: Use `pgvector` within PostgreSQL for RAG embeddings and knowledge retrieval, ensuring that semantic vector searches inherently inherit the exact same RLS tenant boundaries as relational data.

## Invariants Enforced
- Data belonging to Tenant A is mathematically and logically unreachable by Tenant B at the database engine level, even if an application SQL query omits a tenant predicate.
- No separate, out-of-sync vector database is required; vector embeddings and document ACLs reside in the same transactional database.

## Consequences
### Positive
- Defense-in-depth against IDOR, BOLA, and multi-tenant data leakage.
- Atomic ACID transactions across both structured business records and AI semantic embeddings.
- Simplifies backup, restore, and point-in-time recovery (single database target).

### Negative / Trade-offs
- Slight overhead on query planning with complex RLS policies.
- Connection pooling requires ensuring session variables are cleanly cleared or reset (`SET LOCAL` within transaction blocks or explicit pool reset hooks).

### Mitigation
- Use transactional scoping (`SET LOCAL`) in SQLAlchemy session context managers so tenant variables automatically evaporate on commit or rollback.
