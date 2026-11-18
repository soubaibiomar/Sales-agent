# IDENTITY, AUTHENTICATION, AND ZERO-TRUST TENANT ISOLATION ARCHITECTURE

## 1. Executive Architecture Summary

This document specifies the technical design, cryptographic controls, database row-level security (RLS), and operational governance implemented in **STEP 02** of the Sales AI Management Platform.

The platform implements a **Zero-Trust Multi-Tenant Architecture** where identity, tenant boundaries, and operational authorities are strictly established and verified server-side on every request.

```
                      [ Client Application / Web Shell ]
                                      │
                         (Bearer JWT + X-Correlation-ID)
                                      ▼
                      ┌───────────────────────────────┐
                      │    FastAPI Gateway & Middle   │
                      │  - Strict Security Headers    │
                      │  - CORS Policy Allowlist      │
                      │  - Correlation ID Injection   │
                      └──────────────┬────────────────┘
                                     │
                      ┌──────────────▼────────────────┐
                      │    Auth & Security Context    │
                      │  - PyJWT Verification (HS256) │
                      │  - JTI Revocation DB Check    │
                      │  - X-Tenant-ID Spoof Guard    │
                      │  - Privileged MFA Guard       │
                      └──────────────┬────────────────┘
                                     │
                      ┌──────────────▼────────────────┐
                      │    Policy & Authorization     │
                      │  - RBAC / ABAC Policy Engine  │
                      │  - Least Privilege Roles      │
                      └──────────────┬────────────────┘
                                     │
                                     ▼
                ┌───────────────────────────────────────────┐
                │   PostgreSQL 16 with Row-Level Security   │
                │  - Least-Privileged 'sales_app_user'      │
                │  - SET LOCAL app.current_tenant_id        │
                │  - FORCE ROW LEVEL SECURITY (RLS)         │
                │  - Pool Leakage Reset Protection          │
                └───────────────────────────────────────────┘
```

---

## 2. Invariants & Security Principles

1. **Deterministic Authority**: Domain services and PostgreSQL database engines calculate prices, allocate stock, issue invoices, validate identity, and enforce permissions. AI models, prompts, and peripheral workflows are strictly non-authoritative.
2. **Zero-Trust Multi-Tenancy**: The application never trusts client-supplied tenant identifiers (e.g. `X-Tenant-ID` HTTP headers, path parameter overrides, or prompt injection claims). The tenant identity is derived solely from cryptographically signed, verified JWT tokens and validated server-side.
3. **Connection-Pool Context Leakage Prevention**: Connection pools recycle PostgreSQL connections. The `tenant_session()` context manager guarantees that `app.current_tenant_id` is set transactionally via `SET LOCAL` and explicitly reset upon returning connections to the pool, preventing tenant context bleed across concurrent or consecutive requests.
4. **Mandatory Step-Up MFA for Privileged Roles**: Users possessing privileged administrative or managerial roles (`super_admin`, `tenant_admin`, `sales_manager`) cannot execute high-risk operations (user creation, custom discounts, approvals, tenant settings) without active `mfa_verified: true` authentication.
5. **Fail-Closed Authorization**: All authorization evaluations default to denial unless an explicit grant exists in the server-side RBAC/ABAC policy.

---

## 3. Database Row-Level Security & Persistence Architecture

### 3.1 Least-Privilege Application Database Role
The application operates in PostgreSQL under a dedicated, unprivileged role (`sales_app_user`), not as a database superuser:
```sql
CREATE ROLE sales_app_user WITH LOGIN PASSWORD 'app_secure_password';
GRANT CONNECT ON DATABASE sales_ai_db TO sales_app_user;
GRANT USAGE ON SCHEMA public TO sales_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sales_app_user;
```

### 3.2 Row-Level Security (RLS) Policies
Every multi-tenant table enforces RLS unconditionally using `FORCE ROW LEVEL SECURITY`:
```sql
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_policy ON users
    AS RESTRICTIVE
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
```

### 3.3 Transaction-Scoped Context Setting
When acquiring a database connection from SQLAlchemy async pool, the transaction is bound to the verified tenant:
```python
await session.execute(
    text("SET LOCAL app.current_tenant_id = :tenant_id"),
    {"tenant_id": verified_tenant_id}
)
```
Upon transaction completion (`commit`, `rollback`, or unhandled exception), the context is sanitized:
```python
await session.execute(text("RESET app.current_tenant_id"))
current_tenant_id_ctx.reset(token)
```

---

## 4. Cryptographic Identity & Session Lifecycle

### 4.1 Token Specifications
- **Algorithm**: `HS256` (PyJWT 2.14.0) with minimum 256-bit entropy secret key.
- **Audience & Issuer**: `aud: sales-ai-api`, `iss: sales-ai-platform`.
- **Claims**: `sub` (User UUID), `tenant_id` (Tenant UUID), `roles` (List of strings), `permissions` (List of granted codes), `mfa_verified` (Boolean), `jti` (Unique Token ID), `iat`, `exp`.
- **Access Token TTL**: 30 minutes.
- **Refresh Token TTL**: 7 days.

### 4.2 Immediate Session Revocation (JTI Blacklisting)
Upon `/api/v1/auth/logout`, the token's unique identifier (`jti`) is persisted to `session_revocations` with an expiration timestamp. The authentication dependency (`get_security_context`) queries this table on every request, guaranteeing that revoked tokens cannot be reused even prior to natural JWT expiration.

### 4.3 Multi-Factor Authentication (RFC 6238 TOTP)
- **Secret**: 160-bit cryptographically secure Base32 encoded random string.
- **Algorithm**: HMAC-SHA1, 6 digits, 30-second time steps.
- **Drift Tolerance**: $\pm 1$ window (total 90-second valid interval) to accommodate client clock skew without sacrificing security.

---

## 5. AI Hardware & Model Governance Invariants

In accordance with Step 02 mandatory requirements:

1. **Cross-Process Mutual Exclusion**:
   - The GPU model lifecycle manager utilizes `filelock.FileLock` (`sales_ai_ollama_vram.lock`) combined with thread-level synchronization.
   - Prevents race conditions across multiple Uvicorn worker processes or background workers attempting concurrent model switching.
2. **Context Limit Enforcement (Qwen3.5 9B)**:
   - Hardware envelope: 8 GB VRAM on NVIDIA RTX 4060 Laptop.
   - The model execution path clamps `num_ctx = min(requested, 4096)` for `qwen3.5:9b-q4_K_M`.
   - Prevents out-of-memory (OOM) allocations and excessive KV-cache footprint on the laptop GPU.
3. **Synchronous 9B Voice Call Prohibition**:
   - If a request is received with `channel == "voice"`, any synchronous invocation of 9B is rejected immediately with `VoiceModelSafetyError`.
   - Protects real-time voice conversational cadence (TTFT < 600ms) by avoiding multi-second GPU model eviction/reload cycles during live calls.

---

## 6. Backup Encryption & Disaster Recovery

### 6.1 Cryptographic Backup Standard
- **Key Derivation**: PBKDF2-HMAC-SHA256 with 100,000 iterations and 16-byte random salt.
- **Cipher**: AES-256-GCM (Authenticated Encryption with Associated Data).
- **Integrity**: Full SHA-256 checksum calculated over ciphertext and stored in decoupled `.meta.json`.
- **Log Hygiene**: Backup and restore utilities strictly sanitize outputs, preventing passwords, encryption keys, or PII from appearing in logs or terminal stdout.

### 6.2 Tamper Detection & Restore Assurance
Prior to decryption, `restore_database.py` recalculates the SHA-256 checksum of the backup file. If any byte is altered or corrupted, restoration fails immediately with `ChecksumMismatchError` before any database mutations occur.

---

## 7. Authoritative Security Control Traceability Matrix (Step 02 Scope)

Control IDs and definitions are reconciled verbatim against the authoritative baseline (`references/70-security.xlsx` and `security/CONTROL_INDEX.md`).

| Control ID | Category / Name (`70-security.xlsx`) | Implementation Mechanism | Executable Test Verification |
|---|---|---|---|
| **04** | Weak or missing authentication | PyJWT token validation, expiration, and active status checks | `test_auth_missing_or_malformed_header` |
| **05** | Missing server-side authorization | Server-side RBAC/ABAC policy engine (`PolicyService`) | `test_rbac_least_privilege_enforcement` |
| **06** | Cross-user data access | PostgreSQL RLS on all tenant-scoped tables | `test_tenant_cross_select_denial`, `test_cross_tenant_user_access_isolation` |
| **07** | Open database permissions | Application connects strictly as `sales_app_user` with restricted DML | `test_application_role_cannot_bypass_rls` |
| **08** | Misconfigured Firebase / Supabase / S3 | MinIO object storage bound to localhost on private internal Docker network | Container binding verification |
| **09** | Unprotected admin routes | Mandatory step-up MFA and permission checks on `/tenants` and `/users` | `test_privileged_actions_require_step_up_mfa` |
| **10** | Production debug tools exposed | Swagger / OpenAPI endpoints disabled in production environment | `src/backend/main.py` environment switch |
| **16** | Missing input validation | Strict Pydantic v2 schemas across all API request models | `test_auth_missing_or_malformed_header` |
| **17** | SQL injection | SQLAlchemy 2.0 parameterized queries + `set_config` bind parameters | `test_postgres_rls.py` |
| **25** | Weak session management | JTI tracking, short-lived tokens (30m), and immediate revocation | `test_immediate_session_revocation_on_logout` |
| **26** | Weak or incorrectly validated JWTs | Cryptographic signature, audience, issuer, and expiration validation | `test_auth_expired_token` |
| **30** | Default credentials left unchanged | Config validation and deployment fail-safes for environment variables | `src/backend/core/config.py` |
| **33** | IDOR / BOLA | Row-Level Security + tenant ownership verification per endpoint | `test_cross_tenant_user_access_isolation` |
| **34** | APIs trusting user-controlled roles or IDs | Roles and permissions derived strictly from verified JWT claims | `test_client_header_tenant_spoofing_rejection` |
| **41** | Excess database privileges | Unprivileged `sales_app_user` role without DDL or superuser rights | `test_application_role_cannot_bypass_rls` |
| **42** | Missing audit logs | Append-only PostgreSQL `audit_logs` table tracking security events | `test_backup_and_restore_cycle_integrity` |
| **44** | No tested backup / restore plan | Encrypted JSON backup/restore across all 10 core relational tables | `test_backup_and_restore_cycle_integrity` |
| **48** | Sensitive data unprotected in transit / at rest | AES-256-GCM encryption for TOTP MFA secrets and backups at rest | `test_mfa_secret_encryption_at_rest_and_rotation` |
| **49** | Poor tenant isolation | PostgreSQL 16 RLS enforced on all 6 tenant tables | `tests/integration/test_postgres_rls.py` (10/10) |
| **55** | No MFA on privileged accounts | RFC 6238 TOTP MFA required for managers and administrators | `test_privileged_actions_require_step_up_mfa` |
| **56** | Account enumeration | Dummy PBKDF2 computation on non-existent emails eliminates timing leaks | `test_account_enumeration_timing_defense` |
| **63** | Security checks fail open | Fail-closed middleware, VRAM eviction fail-closed, DB pool fail-closed | `test_failed_eviction_fails_closed`, `test_missing_tenant_context_fails_closed` |
| **SAI-02** | Manager Voice Copilot MFA | Step-up MFA verification required for privileged manager operations | `test_privileged_actions_require_step_up_mfa` |
| **SAI-03** | Caller-ID Spoofing / Anti-Spoofing | Rejection of client-supplied tenant/caller headers | `test_client_header_tenant_spoofing_rejection` |
| **SAI-08** | Realtime Voice SLA / Deterministic Guard | Prohibit synchronous 9B invocation during live voice calls | `test_prevent_synchronous_9b_during_voice_calls` |
