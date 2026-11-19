# PRODUCTION RUNBOOK: ZERO-DOWNTIME ROLLBACK PROCEDURE

**Application**: Sales AI Management Platform  
**Rollback Time Target**: < 3 minutes  
**Maximum Tolerable Data Loss**: 0 transactions  

---

## 1. Rollback Trigger Criteria

Initiate immediate automated or manual rollback if:
1. P95 API latency degrades above 500ms for more than 3 consecutive minutes.
2. Error rate exceeds 1.0% on core commerce routes (`/api/quotes`, `/api/orders`, `/api/checkout`).
3. PostgreSQL connection pool exhaustion occurs (`remaining_connections < 5`).
4. Any regression or failure in multi-tenant RLS isolation.

---

## 2. Immediate Traffic Diversion (Fast Rollback)

### Step 2.1: Revert Load Balancer Traffic to Previous Stable Target
If operating under Blue/Green or Canary deployment:
```bash
# Shift traffic from Green (v1.0.1) back to Blue (v1.0.0)
kubectl patch service sales-ai-service -p '{"spec":{"selector":{"app":"sales-ai-blue"}}}'
```

### Step 2.2: Docker Standalone Fast Revert
In single-host containerized deployments:
```bash
docker stop sales-ai-app-current
docker start sales-ai-app-previous
```

---

## 3. Database Schema Migration Rollback

If the release introduced a schema migration that needs reversal:
1. Ensure forward-compatible migrations (expand-and-contract pattern was strictly applied).
2. Execute downgrade migration:
   ```bash
   alembic downgrade -1
   ```
3. Verify table and RLS integrity:
   ```bash
   python scripts/verify_init_db_parity.py
   ```

---

## 4. Post-Rollback Validation Checklist
- [x] All active routes returning HTTP 200 on `/api/health`
- [x] PostgreSQL RLS intact across all tables
- [x] In-flight asynchronous tasks drained or re-queued
- [x] Post-mortem timeline recorded in incident log
