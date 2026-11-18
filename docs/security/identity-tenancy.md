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

## 7. Security Control Traceability Matrix (Step 02 Scope)

| Control ID | Category / Name | Implementation Mechanism | Executable Test Verification |
|---|---|---|---|
| **01** | Identity Verification | JWT cryptographic signature + DB active status | `test_auth_missing_or_malformed_header` |
| **02** | Credential Storage | PBKDF2-HMAC-SHA256 (600,000 iterations) | `test_password_hashing_pbkdf2` |
| **03** | Account Lockout | Lockout for 15 min after 5 failed attempts | Handled in `/api/v1/auth/login` |
| **04** | Tenant Isolation | PostgreSQL RLS + `SET LOCAL app.current_tenant_id` | `test_cross_tenant_user_access_isolation` |
| **05** | Zero-Trust Headers | Reject client `X-Tenant-ID` mismatches | `test_client_header_tenant_spoofing_rejection` |
| **08** | Session Management | JWT expiration + JTI tracking in DB | `test_auth_expired_token` |
| **09** | Session Revocation | Immediate JTI blacklisting on logout | `test_immediate_session_revocation_on_logout` |
| **10** | RBAC Enforcement | Server-side `PolicyService` with fail-closed checks | `test_rbac_least_privilege_enforcement` |
| **41** | BOLA / IDOR Defense | Scoped database queries by active tenant | `test_cross_tenant_user_access_isolation` |
| **44** | Privileged Access | Mandatory RFC 6238 TOTP MFA for managers | `test_privileged_role_creation_requires_mfa` |
| **54** | Data Backup | Automated database schema & record export | `test_backup_and_restore_cycle_integrity` |
| **55** | Backup Encryption | AES-256-GCM authenticated encryption | `test_restore_fails_on_incorrect_key` |
| **56** | Disaster Recovery | SHA-256 integrity verification & restore cycle | `test_restore_fails_on_tampered_checksum` |
| **SAI-02** | Manager MFA | Mandatory step-up verification for high-risk mutations | `test_privileged_role_creation_requires_mfa` |
| **SAI-04** | Voice Anti-Spoofing | Rejection of unauthorized tenant/caller context | `test_client_header_tenant_spoofing_rejection` |
| **SAI-08** | Realtime Voice SLA | Prohibit 9B invocation synchronously during voice calls | `test_prevent_synchronous_9b_during_voice_calls` |
