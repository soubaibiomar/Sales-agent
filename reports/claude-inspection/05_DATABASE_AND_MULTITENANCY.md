# 05 — Database and Multi-Tenancy

## Facts (live container `sales-ai-postgres`)
| Item | Observed |
|---|---|
| Version | PostgreSQL 16.15 (alpine) |
| Tables | 84 in `public` (init-db.sql = migrations 001–010 = 84; ORM has 83, `role_permissions` is association-only) |
| RLS | ENABLE + FORCE on 79. Not on `tenants`, `roles`, `permissions`, `role_permissions`, `tenant_channel_integrations`. |
| Policies | 79, all `tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')` for both USING and WITH CHECK |
| Owner | `postgres` owns all 84 tables |
| App role | `sales_app_user`: rolsuper=f, rolbypassrls=f; SELECT/INSERT/UPDATE/DELETE on **all 84** tables |
| Foreign keys | 203, all single-column; **0 composite tenant FKs** |
| Money types | No float/real money columns (integer `*_cents`) |
| CHECK constraints | Only `appointments (end_time > start_time)` |
| Extensions | plpgsql, uuid-ossp, pgcrypto (**no pgvector**) |
| Data present | Only synthetic test tenants left behind by earlier test runs (63 before this inspection) |

Evidence: `evidence/claude-inspection/db/*`.

## RLS behaviour (verified with two synthetic tenants, everything rolled back)
| Check | Result |
|---|---|
| Tenant A reads tenant B's account | 0 rows — **isolated** |
| No tenant context | 0 rows — **fails closed** |
| Tenant A inserts an opportunity referencing tenant B's account | **ACCEPTED** (RI checks bypass RLS) → F-11 |
| App role UPDATE on another tenant's row in `tenants` | 1 row updated → F-12 |
| App role UPDATE on `audit_logs` | Permitted → F-12 |
| App role sees users/quotes/payment_intents without context | 0 / 0 / 0 (superuser sees 57 users) → F-09 |

## The central contradiction (F-09)
RLS is correctly built, but the application cannot use it:
- **Login** (`api/auth.py:40`) looks up `users` before any tenant is known, so the app role finds nobody.
- **Public routes** (quote accept, payment webhook, telephony) query tenant tables with no context set.
- **Result:** these features only work when RLS is bypassed:
  - `.env.example` → `postgres` superuser (RLS bypassed even with FORCE);
  - code default → SQLite (no RLS).
- The project's own end-to-end scenarios A–E use **in-memory SQLite**. Only scenario F and the `*_real_postgres` tests use the app role, at service level with the context set manually.

**Recommended correction:**
- Add `SECURITY DEFINER` functions owned by a dedicated `auth_lookup` role: `auth_find_user(email, tenant_slug)` and `webhook_route(channel, asset_id)`. Each returns the minimum columns.
- Run the API as `sales_app_user`.
- At startup, refuse a connection with `rolsuper` or `rolbypassrls`.

## Transactions and pooling
- **Tenant context** is set with `set_config(..., is_local=true)`. A pool checkin hook runs `RESET`. That is correct.
- **Caveat:** after any `commit()` inside a request, the tenant context is lost for the rest of that request. Under RLS this fails closed, but it can produce silent empty results.
- **Optimistic versions:** orders and quotes use `version` + `SELECT … FOR UPDATE` (cross-process safe on PostgreSQL).
- **Process-local locks:** the `asyncio.Lock` dictionaries add nothing across processes and grow without bound (F-28).

## Constraints that are missing (F-28)
- `UNIQUE (tenant_id, quote_id)` on `sales_orders`.
- `UNIQUE (tenant_id, idempotency_key)` on `refund_requests`.
- `CHECK (amount_cents >= 0)`, quantity > 0, and `reserved <= on_hand`.
- An exclusion constraint for overlapping appointments.
- Composite tenant FKs (F-11).

## Migration reproducibility
- `scripts/verify_init_db_parity.py` was not re-run. A manual comparison of `CREATE TABLE` names shows **84 = 84** between init-db and the migrations.
- Migrations use plain SQL files with a small runner. There is no down-migration. Running the migration runner against the shared dev DB was not attempted, to avoid mutating it.

## Cross-tenant access via other channels
| Channel | Assessment |
|---|---|
| Direct APIs | Unauthenticated header path (F-01) |
| FK references | F-11 |
| Search / analytics | Filtered by `ctx.tenant_id` (authenticated) |
| RAG | Tenant filter on both document and chunk — OK |
| Exports | No export endpoint found |
| Background workers | None exist |
| Voice sessions | Tenant taken from header/query (F-13) |
