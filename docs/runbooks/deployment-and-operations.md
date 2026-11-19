# PRODUCTION RUNBOOK: DEPLOYMENT & OPERATIONS GUIDE

**Architecture Model**: Unified Multi-Tenant Enterprise SaaS  
**Infrastructure Stack**: Docker Compose / Kubernetes, PostgreSQL 16, Redis 7, MinIO S3, Ollama  
**Target Hardware Envelope**: Intel Core i7-13620H, RTX 4060 Laptop (8GB VRAM), 16GB DDR5 RAM  

---

## 1. Zero-Downtime Deployment Lifecycle

```
[ Git Release Tag ] -> [ Docker Image Build ] -> [ Migration Check ] -> [ Canary Health Check ] -> [ Blue/Green Switch ]
```

### 1.1 Pre-Flight Prerequisites
1. Validate clean Git working tree matching signed `RELEASE_MANIFEST.json`.
2. Confirm regression test suite passed: `python -m pytest tests/ -v` (381/381 passing).
3. Confirm PostgreSQL canonical parity: `python scripts/verify_init_db_parity.py` (84/84 tables).
4. Confirm hardware GPU status: `nvidia-smi` reports resident `qwen3.5:4b` in ~4067MB VRAM.

### 1.2 Running Production Containers
Launch authoritative infrastructure:
```bash
docker compose -f docker-compose.yml up -d
```
Verify container health:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

---

## 2. Connection Pool Tuning & PostgreSQL GUC Configuration

Configure `postgresql.conf` for high-throughput multi-tenancy:
```ini
max_connections = 100
shared_buffers = 2GB
effective_cache_size = 6GB
work_mem = 64MB
maintenance_work_mem = 512MB
row_security = on
```

Application SQLAlchemy connection pool parameters (`src/backend/core/database.py`):
```python
engine_kwargs = {
    "pool_size": 20,
    "max_overflow": 10,
    "pool_pre_ping": True,
    "pool_recycle": 1800,  # 30 minutes
}
```

---

## 3. GPU VRAM Scheduling & Model Lifecycle Operations

1. **Resident LLM**: `qwen3.5:4b` must remain resident on GPU (`keep_alive: -1`).
2. **On-Demand LLM**: `qwen3.5:9b-q4_K_M` is loaded strictly for complex reasoning turns.
   - On load: 4B evicted from GPU VRAM (`keep_alive: 0`).
   - On finish: 9B evicted and 4B restored.
   - **Absolute Prohibition**: Never allow 4B and 9B to be co-resident on GPU simultaneously.
3. **Auxiliary Audio Models**: ASR, TTS, and Moroccan Darija tools run strictly on CPU.

---

## 4. Operational Monitoring Endpoints

- Health Probe: `GET /api/health`
- Deep Readiness: `GET /api/ready`
- Real-Time Hardware Telemetry: `GET /api/admin/telemetry/hardware`
- Security Audit Status: `GET /api/admin/security/status`
