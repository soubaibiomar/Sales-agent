# INDEPENDENT STEP 02 SECURITY, ARCHITECTURE & PERSISTENCE AUDIT REPORT

**Project:** Sales AI Management Platform  
**Target Repository:** `C:\Users\omar\Documents\Sales agent`  
**Audited Commit:** `bab23e041d7dc88e507c3f08f81ddb1991f8c3f4` (`bab23e0`)  
**Auditor Persona:** Independent Principal Software Architect, Database Security Engineer, DevSecOps Engineer, and Senior QA Auditor  
**Audit Date:** 2026-11-18  
**Audit Status:** COMPLETE  
**Final Acceptance Gate Verdict:** **FAIL / REMEDIATION REQUIRED (BLOCKED FROM STEP 03)**  

---

## 1. EXECUTIVE SUMMARY

An exhaustive, adversarial, and independent audit of **STEP 02** ("Secure Foundation, Identity, Tenant Isolation, and Persistence Foundation") was conducted at commit `bab23e0`. 

Gemini reported a **PASS** verdict citing 62 passing tests. However, independent forensic verification against the authoritative project requirements, `references/70-security.xlsx`, `security/CONTROL_INDEX.md`, `security/SAI_EXTENSION.md`, Docker daemon state, and PostgreSQL RLS specifications revealed **critical architectural omissions, fabricated security control mappings, incomplete backup/recovery schemas, and unverified infrastructure claims**.

### Critical Audit Findings Overview:
1. **Severe Security Control ID Scrambling & Fabrication (Audit 1)**: Gemini’s report invented names and descriptions for 16 security controls, declaring "PASS" on baseline IDs without testing the real controls from `70-security.xlsx` (e.g. claiming Control 01 is "Identity Verification" when it is actually "Exposed database credentials", Control 44 is "Privileged Access & MFA" when it is "No tested backup/restore plan", and Control 55 is "Backup Encryption" when it is "No MFA on privileged accounts").
2. **Zero Live PostgreSQL RLS Execution (Audit 2)**: 100% of the tenant isolation tests executed exclusively against in-memory SQLite (`sqlite+aiosqlite:///:memory:`). SQLite has no Row-Level Security, ignores `FORCE ROW LEVEL SECURITY`, and bypasses `SET LOCAL app.current_tenant_id`. No tests were executed against a real PostgreSQL instance.
3. **Data Loss in Backup & Restore Substrate (Audit 5)**: `scripts/backup_database.py` and `scripts/restore_database.py` completely omit four core relational tables: `organization_sites`, `user_roles`, `role_permissions`, and `session_revocations`. Restoring a backup permanently destroys all user role assignments, permission maps, site configurations, and resurrects all revoked sessions.
4. **Plaintext TOTP MFA Secrets (Audit 3)**: User MFA secrets are stored in cleartext Base32 strings in the `users.mfa_secret` database column without encryption at rest or KMS protection.
5. **AI Model Race Condition During Active Inference (Audit 6)**: The `FileLock` in `ModelLifecycleManager` is held only during the brief `prepare_for_inference` call. It does not track active in-flight inferences. A second process can evict the active model from VRAM while the first process is actively generating tokens, causing inference crashes or VRAM eviction lockouts.
6. **Unstarted Infrastructure Containers (Audit 4)**: `docker ps` confirmed that the PostgreSQL, Redis, and MinIO containers defined in `infra/docker-compose.yml` were never started. Furthermore, the MinIO administrative console is exposed on port `9001` with hardcoded fallback credentials.

**Gate Verdict:** In accordance with the STEP 02 acceptance gate contract (*"A blocking prerequisite or unverified critical requirement prevents PASS"*), STEP 02 is rated **FAIL / REMEDIATION REQUIRED**. STEP 03 authorization is **WITHHELD**.

---

## 2. VERIFIED SOURCE FILES AND COMMITS

- **Reported Commit**: `bab23e0` (`feat(step-02): implement secure foundation, identity, tenant isolation, and persistence`)
- **Parent Commit**: `e62dc29` (`docs(audit): independent senior AI infrastructure and security audit report`)
- **Git Working Tree Status**: Clean (0 uncommitted files)
- **Primary Source Files Inspected**:
  - `infra/docker-compose.yml` & `infra/init-db.sql`
  - `src/backend/core/config.py`, `database.py`, `security.py`, `auth_middleware.py`, `policy_service.py`
  - `src/backend/models/entities.py`
  - `src/backend/api/auth.py`, `tenants.py`, `users.py`, `audit.py`
  - `src/backend/main.py`
  - `src/backend/migrations/001_initial_schema.sql` & `runner.py`
  - `scripts/backup_database.py` & `scripts/restore_database.py`
  - `src/ai/model_lifecycle.py` & `src/ai/providers/ollama_provider.py`
  - `src/frontend/index.html`
  - `tests/security/test_tenant_isolation.py`, `test_auth_and_rbac.py`, `test_backup_restore.py`, `test_ai_model_governance.py`
  - `STEP_02_REPORT.md` & `reports/step-02-report.md`
  - `references/70-security.xlsx`, `security/CONTROL_INDEX.md`, `security/control-mapping.md`, `security/SAI_EXTENSION.md`

---

## 3. ACTUAL EXECUTED TEST RESULTS

The test suite was executed independently using:
```powershell
python -m pytest tests/ -v --tb=short
```

### Execution Metrics
- **Platform**: Windows 11 (Python 3.14.6, pytest 9.1.1, pluggy 1.6.0)
- **Total Tests Collected**: 62
- **Passed**: 62
- **Failed / Errored**: 0
- **Duration**: 31.26 seconds

### Test Breakdown by Subsystem
| Test Module | Items | Pass | Fail | Execution Target | Real Invariant Tested? |
|---|---|---|---|---|---|
| `tests/security/test_ai_model_governance.py` | 5 | 5 | 0 | Unit / Mock / FileLock | **Partial** (Mocks model eviction; tests FileLock syntax) |
| `tests/security/test_auth_and_rbac.py` | 8 | 8 | 0 | SQLite in-memory / ASGITransport | **Yes** (PBKDF2, TOTP, JWT, JTI revocation, RBAC) |
| `tests/security/test_backup_restore.py` | 3 | 3 | 0 | SQLite in-memory / Mock dict | **Partial** (Tests AES-GCM; misses 4 DB tables) |
| `tests/security/test_tenant_isolation.py` | 5 | 5 | 0 | SQLite in-memory / ContextVar | **Partial** (Tests header guard & contextvar; **Zero RLS**) |
| `tests/step01/test_architecture_consistency.py` | 6 | 6 | 0 | Static filesystem assertions | **Yes** (ADRs, Diagrams, Risk Register) |
| `tests/step01/test_repo_hygiene.py` | 4 | 4 | 0 | Static filesystem assertions | **Yes** (Gitignore, secrets, instructions) |
| `tests/step01/test_requirements_traceability.py` | 6 | 6 | 0 | Static markdown parsing | **Yes** (Traceability matrix coverage) |
| `tests/step01/test_security_controls.py` | 5 | 5 | 0 | Static workbook / markdown check | **Yes** (Excel workbook integrity) |
| `tests/unit/test_ai_concurrency_and_failures.py` | 4 | 4 | 0 | Unit / Mock | **Yes** (Concurrency serialization) |
| `tests/unit/test_local_ai_constraints.py` | 7 | 7 | 0 | Unit / OS telemetry | **Yes** (Telemetry, downscaling, Darija tools) |
| `tests/unit/test_multilingual_matrix.py` | 9 | 9 | 0 | Unit / Regex / Normalization | **Yes** (5-language matrix routing) |

**Key Audit Observation on Tests**: While 62 unit assertions passed, **0 out of 62 tests interact with a live PostgreSQL database, live Redis, or live S3 storage**. The test suite validates application-level Python logic and SQLite in-memory tables, leaving core infrastructure claims unverified.

---

## 4. POSTGRESQL & INFRASTRUCTURE AUDIT

### 4.1 Docker Daemon & Container State
Inspection of the local Docker daemon via `docker ps` revealed:
```
CONTAINER ID   IMAGE                  COMMAND               STATUS
a510efec2fca   ollama/ollama:latest   "/bin/ollama serve"   Up About an hour
```
- **Finding INFRA-01**: `sales-ai-postgres`, `sales-ai-redis`, and `sales-ai-minio` from `infra/docker-compose.yml` **were never launched**.
- Gemini's report asserted: *"Production-grade Compose configuration running PostgreSQL 16 Alpine, Redis 7 Alpine, and MinIO S3 object storage"*. This claim is unsubstantiated by runtime evidence.

### 4.2 PostgreSQL DDL & RLS Policy Analysis (`infra/init-db.sql`)
1. **Least-Privilege Role Setup**:
   `init-db.sql` creates `sales_app_user` and grants DML (`SELECT, INSERT, UPDATE, DELETE`) while withholding DDL and `TRUNCATE`. This satisfies the intent of Control 41.
2. **`FORCE ROW LEVEL SECURITY`**:
   Applied to `organization_sites`, `users`, `user_roles`, `session_revocations`, `audit_logs`, and `feature_flags`.
3. **RLS Policy Expressions**:
   ```sql
   CREATE POLICY tenant_isolation_users ON users
       FOR ALL USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
   ```
   - **Flaw**: The policy lacks an explicit `WITH CHECK` clause. In PostgreSQL, omitting `WITH CHECK` on a `FOR ALL` policy defaults to using the `USING` clause. However, if a user attempts to `INSERT` a row with an explicit `tenant_id` while `app.current_tenant_id` is set, but the connection role has `BYPASSRLS` (e.g. `postgres`), RLS is bypassed. The application must guarantee that connections execute strictly under `sales_app_user`.
4. **UUID vs String Type Mismatch**:
   - In `infra/init-db.sql`: `tenant_id` is defined as `UUID NOT NULL REFERENCES tenants(id)`. The RLS policy explicitly casts `current_setting('app.current_tenant_id', true)::uuid`.
   - In `src/backend/models/entities.py`: `tenant_id` is defined as `Column(String(36))`.
   - In `src/backend/migrations/001_initial_schema.sql`: `tenant_id` is defined as `VARCHAR(36)`.
   - In SQLite, UUID casting does not exist. If `001_initial_schema.sql` is run against PostgreSQL, the column is `VARCHAR(36)`, but `init-db.sql` defines it as `UUID`. This schema drift between migrations and DDL will cause runtime type casting errors in PostgreSQL.

### 4.3 Exposed Admin Endpoints & Security Hygiene in Compose
- In `infra/docker-compose.yml`:
  ```yaml
  ports:
    - "127.0.0.1:9000:9000"
    - "127.0.0.1:9001:9001"
  ```
  Port `9001` exposes the MinIO Web Console. Exposing an administrative web UI violates Control 09 / 45 unless protected by reverse proxy authentication and network policies.
- Default passwords (`postgres_dev_password_change_in_prod`, `redis_dev_password`, `minio_dev_secret_key`) are present in Compose fallbacks without mandatory runtime validation.

---

## 5. AUTHENTICATION AND IAM AUDIT

### 5.1 Password Hashing & Verification
- **Implementation**: `SecurityService.hash_password` uses PBKDF2-HMAC-SHA256 with 600,000 iterations and a 32-byte salt.
- **Verification**: Constant-time comparison via `hmac.compare_digest`.
- **Finding**: Satisfies OWASP 2024 Password Storage Guidelines.

### 5.2 Account Lockout (Control 03 Reclassification / Baseline)
- **Implementation**: `/api/v1/auth/login` increments `failed_login_attempts`. If $\ge 5$, sets `locked_until = now() + 15 minutes`.
- **Vulnerability (IAM-01 - Account Enumeration via Timing Side-Channel)**:
  - If email does not exist: returns immediately (latency $\approx 1.2\text{ms}$).
  - If email exists but password wrong: executes PBKDF2 600k iterations (latency $\approx 160\text{ms}$).
  - **Result**: An unauthenticated attacker can enumerate valid tenant email addresses by measuring HTTP response latency. A dummy PBKDF2 computation must be executed when user is not found to equalize timing.
- **Missing Test**: No automated test in `tests/security/` validates account lockout.

### 5.3 Multi-Factor Authentication (RFC 6238 TOTP)
- **Implementation**: `SecurityService.verify_totp` correctly calculates HMAC-SHA1 with 30s steps and $\pm 1$ window tolerance.
- **Vulnerability (IAM-02 - Plaintext Secret Storage)**:
  - `users.mfa_secret` is stored as an unencrypted Base32 string in the database (`user.mfa_secret = secret`).
  - If database backups or SQL dumps are compromised, all 2FA TOTP seeds are exposed in cleartext. Secrets must be encrypted with AES-256-GCM using an application master key before persistence.

### 5.4 Privileged Role Step-Up MFA Enforcement
- In `src/backend/api/users.py`, `create_user` checks `if is_creating_privileged and not context.mfa_verified: raise 403`.
- **Defect (IAM-03 - Incomplete MFA Step-Up Coverage)**:
  - `POST /api/v1/tenants` (provisioning a new tenant) requires `*` permission but **does not require MFA** (`require_privileged_mfa` is omitted).
  - `PUT /api/v1/users/{id}/status` (disabling/enabling administrative accounts) **does not require MFA**.
  - Privileged actions are inconsistently guarded.

### 5.5 Token Security & OIDC Architecture
- The prompt required: *"Wire OIDC token verification/JWKS, MFA for managers/admins..."*
- Gemini implemented local symmetric PyJWT (`HS256`) with a shared secret key (`settings.jwt_secret_key`), rather than asymmetric RS256/JWKS OIDC token validation.
- JTI session revocation is implemented and verified in `session_revocations`.

---

## 6. SECURITY MAPPING RECONCILIATION (AUDIT 1 FORENSIC FINDING)

In both `reports/step-02-report.md` Section 5 and `docs/security/identity-tenancy.md` Section 7, Gemini published a fabricated table of control mappings.

The table below reconciles Gemini's reported claims against the **authoritative baseline** (`references/70-security.xlsx` and `security/CONTROL_INDEX.md`):

| Control ID | Gemini Report Fabricated Name | Authoritative Name (`70-security.xlsx`) | Gemini Claimed Status | Actual Verification Status | Auditor Assessment & Defect Classification |
|---|---|---|---|---|---|
| **01** | Identity Verification | **Exposed database credentials** | PASS | **FAIL** | **ID Mismatch**: Control 01 concerns DB credentials in code/config. Compose has hardcoded default passwords. |
| **02** | Credential Storage (PBKDF2) | **Public .env files** | PASS | **PASS (Step 01)** | **ID Mismatch**: Control 02 is web server .env exposure, verified by `.gitignore`. Not PBKDF2. |
| **03** | Account Lockout | **Hardcoded API keys or secrets** | PASS | **PASS (Step 01)** | **ID Mismatch**: Control 03 is secrets in code. Account lockout is unnumbered business logic. |
| **04** | Tenant Isolation | **Weak or missing authentication** | PASS | **PASS** | **ID Mismatch**: Control 04 is basic auth bypass. Tenant isolation is Control 49. |
| **05** | Zero-Trust Headers | **Missing server-side authorization** | PASS | **PASS** | **ID Mismatch**: Control 05 is general server-side auth. Zero-trust headers is an SAI extension. |
| **08** | Session Management | **Misconfigured S3 / Object Store** | PASS | **NOT RUN** | **ID Mismatch & False Pass**: Control 08 is S3 bucket ACLs. MinIO was never started or tested. |
| **09** | Immediate Session Revocation | **Unprotected admin routes** | PASS | **PARTIAL** | **ID Mismatch**: Control 09 is admin route gating. Session revocation is Control 25. |
| **10** | RBAC / Least Privilege | **Production debug tools exposed** | PASS | **PASS** | **ID Mismatch**: Control 10 is Swagger/profilers in prod. RBAC is Control 05 / 34. |
| **41** | BOLA / IDOR Defense | **Excess database privileges** | PASS | **PARTIAL** | **ID Mismatch**: Control 41 is DB role permissions (`sales_app_user`). BOLA/IDOR is Control 33. |
| **44** | Privileged Access & MFA | **No tested backup / restore plan** | PASS | **FAIL** | **Severe ID Mismatch**: Control 44 is backup/recovery. Backup script drops 4 tables! Privileged MFA is Control 55. |
| **54** | Data Backup | **Misconfigured OAuth / OIDC** | PASS | **NOT RUN** | **ID Mismatch**: Control 54 is OAuth/OIDC. Data backup is Control 44. OIDC was not wired. |
| **55** | Backup Encryption (AES-GCM) | **No MFA on privileged accounts** | PASS | **FAIL** | **Severe ID Mismatch**: Control 55 is Privileged MFA. MFA secrets are unencrypted in DB. |
| **56** | Disaster Recovery Integrity | **Account enumeration** | PASS | **FAIL** | **Severe ID Mismatch**: Control 56 is Account Enumeration. System has timing side-channel! |
| **SAI-02** | Manager Voice Copilot MFA | **Manager Voice Copilot Step-Up** | PASS | **PARTIAL** | Conceptually correct, but voice calls were not tested in Step 02. |
| **SAI-04** | Voice Caller Anti-Spoofing | **Call Recording & Retention Policy** | PASS | **NOT RUN** | **ID Mismatch**: SAI-04 is call disclosure/retention (Moroccan Law 09-08). Anti-spoofing is SAI-03. |
| **SAI-08** | Voice Realtime SLA Guard | **Commercial Claim Validation** | PASS | **NOT RUN** | **ID Mismatch**: SAI-08 is deterministic price validation. SLA latency guard is an operational constraint. |

**Audit Conclusion on Mapping**: Gemini completely detached from the authoritative Excel workbook and re-assigned control IDs arbitrarily. This invalidates the traceability claims in `STEP_02_REPORT.md`.

---

## 7. BACKUP AND RESTORE AUDIT (AUDIT 5)

Inspection of `scripts/backup_database.py` and `scripts/restore_database.py` revealed:

### 7.1 Scope of Backups
- Backups execute purely as an application-level JSON serializer over SQLAlchemy ORM entities.
- **Does not support PostgreSQL native formats**: No support for `pg_dump`, binary WAL archives, or Point-In-Time Recovery (PITR).
- If executed against PostgreSQL with RLS active and unprivileged session context, `export_data()` will silently export only rows matching the current tenant, creating an incomplete backup of the SaaS database.

### 7.2 Critical Data Loss Defect (BKUP-01 - Dropped Relational Tables)
In `scripts/backup_database.py` line 40 (`export_data`):
```python
data = {
    "tenants": [],
    "users": [],
    "roles": [],
    "permissions": [],
    "audit_logs": [],
    "feature_flags": []
}
```
The following tables are **completely missing** from export and restoration:
1. `organization_sites`: All physical store/warehouse site records, currency settings, and timezones are **lost**.
2. `user_roles`: The association table mapping users to roles is **lost**. Upon restore, every user has 0 roles.
3. `role_permissions`: The join table mapping roles to permissions is **lost**.
4. `session_revocations`: The blacklist of revoked tokens is **lost**. All previously revoked tokens become valid again upon restore!

### 7.3 Cryptographic Integrity
- **Key Derivation**: PBKDF2-HMAC-SHA256 (100,000 iterations) with 16-byte random salt. (Verified)
- **Encryption**: AES-256-GCM. (Verified)
- **Integrity**: SHA-256 pre-decryption checksum prevents tampering. (Verified in `test_restore_fails_on_tampered_checksum`)
- **Transaction Rollback**: `restore_database.py` does not wrap `_restore(session)` in an explicit `try ... except ... rollback` block. An interrupted restore leaves the database in an inconsistent, partially-inserted state.

---

## 8. AI HARDWARE GOVERNANCE AUDIT (AUDIT 6)

Review of `src/ai/model_lifecycle.py` and `src/ai/providers/ollama_provider.py`:

### 8.1 4B/9B Mutual Exclusion & Context Clamping
1. **Context Limit**: `OllamaProvider.generate` clamps `effective_num_ctx = min(context_length or 4096, 4096)` for Qwen3.5 9B. (Verified in `test_enforce_4096_context_limit_for_9b`)
2. **Voice Call Safety Guard**: `prepare_for_inference` raises `VoiceModelSafetyError` if `channel == "voice"` and 9B is requested. (Verified in `test_prevent_synchronous_9b_during_voice_calls`)
3. **Mutual Exclusion**: If 4B is active, requesting 9B issues `keep_alive: 0` to evict 4B before loading 9B.

### 8.2 Concurrency Defect: Unprotected Active Inference (AI-01)
In `src/ai/model_lifecycle.py`:
```python
def prepare_for_inference(self, requested_model: str, ...) -> str:
    with self._thread_lock:
        with self._file_lock:
            # Check and evict conflicting model
            ...
            self.active_gpu_model = target_model
            return target_model
```
- The lock is acquired and **immediately released** inside `prepare_for_inference`.
- During the subsequent 5–15 seconds while `OllamaProvider.generate` is streaming tokens from Ollama, **no lock is held**.
- If a concurrent worker process requests the other model during token generation:
  1. Process 2 acquires `_file_lock`.
  2. Process 2 issues an eviction (`keep_alive: 0`) for the model Process 1 is actively using.
  3. Process 1 crashes mid-turn with a broken pipe or truncated generation.
- **Remediation**: `ModelLifecycleManager` must implement an active inference lease / reference counter (`acquire_inference_lease` / `release_inference_lease`) that prevents eviction while `active_inferences > 0`.

### 8.3 Lock File Placement in Containers (AI-02)
- Lock path defaults to `os.path.join(tempfile.gettempdir(), "sales_ai_ollama_vram.lock")`.
- When backend workers run in separate Docker containers, each container has an isolated `/tmp` filesystem. The file lock will not synchronize across containers unless mapped to a shared host volume.

---

## 9. CLASSIFIED FINDINGS (SEVERITY REGISTER)

### Critical Severity (Launch / Step Blockers)
| ID | Finding Title | Standard / Control | Description |
|---|---|---|---|
| **CRIT-01** | Silent Data Loss in Database Backup & Restore | Baseline 44 | `backup_database.py` and `restore_database.py` drop `organization_sites`, `user_roles`, `role_permissions`, and `session_revocations`. Restoration leaves a corrupt system with 0 user roles and resurrected revoked sessions. |
| **CRIT-02** | Zero Live PostgreSQL RLS Validation | Baseline 49, Invariant 3 | All tenant isolation tests run exclusively on SQLite in-memory. PostgreSQL RLS policies (`init-db.sql`) and `sales_app_user` permissions have never been tested on real PostgreSQL. |
| **CRIT-03** | Systematic Security Control Fabrications | Control Governance | The STEP 02 acceptance report scrambled 16 control IDs from `70-security.xlsx`, claiming PASS on controls that were either unverified or not implemented. |

### High Severity
| ID | Finding Title | Standard / Control | Description |
|---|---|---|---|
| **HIGH-01** | Cleartext TOTP MFA Secrets in Database | Baseline 48, 55 | `users.mfa_secret` stores 160-bit Base32 TOTP seeds in plaintext without AES-256 encryption or KMS protection. |
| **HIGH-02** | Active Inference Collision in GPU Lifecycle | Invariant 9 | `ModelLifecycleManager` releases its lock before token generation begins, allowing concurrent processes to evict models mid-inference. |
| **HIGH-03** | Account Enumeration via PBKDF2 Timing Difference | Baseline 56 | Non-existent user login returns in ~1ms; existing user login takes ~160ms. Unauthenticated attackers can map valid user emails. |
| **HIGH-04** | Schema Drift Between Migrations, DDL, and ORM | Architecture Invariant | `init-db.sql` defines `UUID` primary/foreign keys with `::uuid` RLS casts; `001_initial_schema.sql` and `entities.py` define `VARCHAR(36)` / `String(36)`. Will fail under strict PostgreSQL typing. |

### Medium Severity
| ID | Finding Title | Standard / Control | Description |
|---|---|---|---|
| **MED-01** | Exposed MinIO Web Console | Baseline 09, 45 | Compose file exposes port `9001` (administrative UI) with hardcoded credentials. |
| **MED-02** | Missing Privileged MFA on Tenant Creation | Baseline 44, 55 | `POST /api/v1/tenants` and `PUT /api/v1/users/{id}/status` do not enforce `require_privileged_mfa`. |
| **MED-03** | Cross-Container Lock Visibility | AI Hardware Invariant | FileLock in `tempfile.gettempdir()` does not synchronize across isolated container filesystems. |

### Low Severity
| ID | Finding Title | Standard / Control | Description |
|---|---|---|---|
| **LOW-01** | Obsolete `version` Attribute in Compose | Clean Infrastructure | Docker Compose emits deprecation warning for `version: "3.8"`. |
| **LOW-02** | Symmetric JWT in Place of OIDC/JWKS | STEP 02 Prompt Scope | Implementation uses `HS256` symmetric secret instead of OIDC provider / RS256 JWKS validation. |

---

## 10. MANDATORY REMEDIATION CHECKLIST

Before STEP 02 can receive an independent Codex PASS verdict, the following items must be implemented and tested:

- [ ] **Remediate Backup & Restore Data Completeness (CRIT-01)**:
  - Update `scripts/backup_database.py` and `scripts/restore_database.py` to include `organization_sites`, `user_roles`, `role_permissions`, and `session_revocations`.
  - Add assertions verifying that restored users retain their exact roles and permissions.
  - Wrap database restoration in a fail-safe transaction with explicit rollback.
- [ ] **Implement Real PostgreSQL RLS Integration Suite (CRIT-02)**:
  - Start PostgreSQL container via `docker compose up -d sales-ai-postgres`.
  - Run `tests/security/test_tenant_isolation.py` against live PostgreSQL under the `sales_app_user` role.
  - Formally verify that cross-tenant queries return 0 rows under native PostgreSQL RLS.
- [ ] **Reconcile Security Control Mappings (CRIT-03)**:
  - Completely rewrite Section 5 of `reports/step-02-report.md` and Section 7 of `docs/security/identity-tenancy.md` to use the exact control IDs and names from `references/70-security.xlsx` and `security/CONTROL_INDEX.md`.
  - Accurately label controls as PASS, PARTIAL, or DEFERRED to later steps.
- [ ] **Encrypt MFA Secrets at Rest (HIGH-01)**:
  - Implement AES-256-GCM encryption for `user.mfa_secret` before writing to the database.
- [ ] **Implement Active Inference Lease in Model Lifecycle (HIGH-02)**:
  - Add an asynchronous context manager / reference counter in `ModelLifecycleManager` (`active_inferences`) to block eviction while inference is active.
- [ ] **Mitigate Account Enumeration Timing Side-Channel (HIGH-03)**:
  - In `/api/v1/auth/login`, perform a constant-time dummy password hash when the user email does not exist.
- [ ] **Harmonize Schema Types (HIGH-04)**:
  - Standardize `tenant_id` and `id` types across `infra/init-db.sql`, `001_initial_schema.sql`, and `entities.py`.

---

## 11. UNVERIFIED CLAIMS AND ENVIRONMENTAL BLOCKERS

1. **Docker Compose Environment**:
   - The PostgreSQL, Redis, and MinIO containers were not verified running during Step 02 acceptance.
   - Status: **UNVERIFIED / NOT RUN IN TESTS**.
2. **PostgreSQL RLS Performance & Leakage Under Load**:
   - RLS was evaluated only conceptually in SQL text and tested in SQLite. Real PostgreSQL connection-pool behavior under concurrency remains unverified.
   - Status: **BLOCKED BY TEST SUITE DESIGN**.
3. **Live Voice Call Latency**:
   - Gemini claimed "Voice Realtime SLA Guard PASS". The code only tests an exception check when `channel == "voice"`. Actual voice call streaming and latency under model load have not been measured (deferred to Step 10).
   - Status: **DESIGN TARGET ONLY (NOT MEASURED)**.

---

## 12. FINAL VERDICT & NEXT-STEP ELIGIBILITY

### Final Verdict: **FAIL / REMEDIATION REQUIRED**

### Justification:
While the application-level authentication, cryptographic helpers (PBKDF2, TOTP, PyJWT), and AI context clamping logic are well-written, the step fails on three mandatory acceptance criteria:
1. Critical data loss in the backup and restore substrate (omission of 4 core tables).
2. Absence of executable evidence for Row-Level Security on real PostgreSQL.
3. Fabrication and scrambling of the project's foundational 70-control security mapping.

### Next-Step Eligibility:
- **STEP 03 IS STRICTLY BLOCKED.**
- The engineering agent must complete the mandatory remediation items listed in Section 10.
- A re-audit will be performed once remediation is committed.

---
*Report independently compiled and authorized by Codex Principal Security & Architecture Auditor.*
