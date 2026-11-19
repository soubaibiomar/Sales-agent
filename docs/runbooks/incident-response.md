# PRODUCTION RUNBOOK: STRIDE SECURITY INCIDENT RESPONSE

**Classification**: Confidential / P0 Launch Protocol  
**Compliance Standards**: Moroccan Law 09-08, GDPR, OWASP Top 10, OWASP LLM Top 10  
**Related Controls**: Baseline Controls 01–70, SAI-01 to SAI-12  

---

## 1. Severity Classification Matrix

| Severity Level | Definition | SLA Response | Escalation Path |
|---|---|---|---|
| **P0 (Critical)** | Active cross-tenant data leak, PostgreSQL RLS bypass, prompt injection financial mutation, compromised master key | Immediate (< 15 min) | Lead Architect, CISO, Legal Counsel |
| **P1 (High)** | Webhook HMAC failure spike, voice spoofing attempt, auth brute force, rate-limit threshold exhaustion | < 1 hour | Security Lead, Backend On-Call |
| **P2 (Medium)** | Non-critical service degradation, localized PII redaction warning, temporary carrier webhook retry backlog | < 4 hours | Backend On-Call Engineer |

---

## 2. Threat Containment Procedures (STRIDE)

### Threat 1: Cross-Tenant Data Leakage or RLS Escape (Elevation of Privilege)
1. **Immediate Session Isolation**: Terminate suspicious active connections in PostgreSQL:
   ```sql
   SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'sales_app_user' AND query LIKE '%tenants%';
   ```
2. **Revoke Active Tokens**: Push affected user/tenant ID to Redis revocation denylist:
   ```python
   await session_manager.revoke_all_sessions(tenant_id=compromised_tenant_id)
   ```
3. **Verify RLS Enforcement**: Query `pg_class` to verify all 84 tables maintain `relrowsecurity = true` and `relforcerowsecurity = true`.

### Threat 2: Adversarial Prompt Injection or Jailbreak Attempt (Tampering / Spoofing)
1. **Automatic Silencing**: ConversationSupervisor immediately transitions the conversation to `SILENCED_TAKEOVER`.
2. **Review Turn Invariant**: Confirm that no ungrounded tool actions (discounts, refunds, stock deductions) were executed.
3. **Audit Ledger Inspection**: Extract offending transcript from `model_execution_logs` and flag hash for inclusion in adversarial regression tests.

### Threat 3: Compromised Secret or Exposed API Key (Information Disclosure)
1. **Rotate Credentials**:
   - Rotate JWT signing secret (`JWT_SECRET_KEY`).
   - Rotate database password for `sales_app_user`.
   - Rotate CMI Payment and Carrier Webhook HMAC keys.
2. **Redeploy Application**: Trigger zero-downtime rolling restart with updated `.env`.
3. **Audit Access Logs**: Scan `audit_logs` for any unauthorized access during the exposure window.

---

## 3. Moroccan Law 09-08 & GDPR Breach Notification Protocol
Under Moroccan Law 09-08 and GDPR Article 33:
1. Document the nature of the personal data breach, categories, and approximate number of data subjects.
2. If risk to data subjects exists, notify the CNDP (Commission Nationale de contrôle de la protection des données à caractère personnel) within 72 hours.
3. Provide affected customers with clear mitigation steps (password reset, session revocation).
