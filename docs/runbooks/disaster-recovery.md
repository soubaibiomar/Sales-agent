# PRODUCTION RUNBOOK: DISASTER RECOVERY & FAILOVER PROCEDURE

**Platform**: Sales AI Management Platform  
**Target RTO**: < 15 minutes (900 seconds) | **Measured RTO**: 1.35 seconds  
**Target RPO**: < 1 minute (60 seconds) | **Measured RPO**: 0.00 seconds  
**Authoritative Evidence**: `evidence/step-12/dr/backup_restore_drill.json`

---

## 1. Objective & Scope

This runbook establishes standard operating procedures for catastrophic failure recovery, unrecoverable database corruption, hardware loss, or host compromise. It details how to restore the unified PostgreSQL 16 database, preserve Row-Level Security (RLS) policies on all 84 tables, restore S3 encrypted artifacts, and restart omnichannel services.

---

## 2. Emergency Trigger Criteria

Disaster Recovery is initiated under the following P0 Sev-1 conditions:
1. Complete unrecoverable storage failure of PostgreSQL volume `postgres_data`.
2. Multi-region Cloud outage exceeding 15 minutes.
3. Cryptographic ransomware or catastrophic operator corruption destroying primary tables.
4. Total hardware failure of local server infrastructure.

---

## 3. Step-by-Step Restoration Procedure

### Step 3.1: Provision Fresh PostgreSQL 16 Target
Ensure PostgreSQL 16 with pgvector extension is running:
```bash
docker run -d --name sales-ai-postgres-dr \
  -e POSTGRES_PASSWORD=postgres_dev_password_change_in_prod \
  -p 5432:5432 \
  postgres:16-alpine
```

### Step 3.2: Retrieve Latest Encrypted Backup Artifact
Fetch the latest automated snapshot from offsite S3 / MinIO:
```bash
aws s3 cp s3://sales-ai-backups/daily/sales_ai_db_latest.dump /tmp/sales_ai_db_latest.dump
sha256sum /tmp/sales_ai_db_latest.dump
```
Verify checksum against the signed release manifest.

### Step 3.3: Execute Full Database Restore
Restore the custom-format pg_dump archive into a clean target database:
```bash
docker exec -i sales-ai-postgres pg_restore -U postgres -d sales_ai_db \
  --clean --if-exists --no-owner --no-privileges /tmp/sales_ai_db_latest.dump
```

### Step 3.4: Re-Establish Least-Privilege Role Grants
Re-apply database application grants:
```sql
GRANT USAGE ON SCHEMA public TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sales_app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sales_app_user;
```

### Step 3.5: Run Automated Parity Verification
Execute the automated parity verifier:
```bash
python scripts/dr_backup_restore_drill.py
```
**Verification Checklist**:
- [x] 84/84 Tables restored with matching column types
- [x] Row-level security ENABLE and FORCE confirmed on all tables
- [x] 79 RLS policies active and verified
- [x] Canary transactions intact (RPO = 0s)
- [x] Application user `sales_app_user` context fail-closed check passes

---

## 4. Post-Restoration Verification & Service Ramp-Up
1. **Redis Flush**: Flush ephemeral Redis cache (`redis-cli flushall`) to prevent stale session tokens.
2. **Ollama Resident Model Check**: Confirm `qwen3.5:4b` resident in GPU VRAM (`nvidia-smi` ~4067MB).
3. **Omnichannel Health Check**: Send heartbeat probe to `/api/health` and verify HTTP 200 `status: HEALTHY`.
4. **Traffic Unfreezing**: Re-enable DNS CNAME / load balancer traffic to platform.
