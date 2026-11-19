# PRODUCTION RUNBOOK: BACKUP, ARCHIVAL & DATA RETENTION

**Standards**: Moroccan Law 09-08, GDPR Article 5 (Storage Limitation), PCI-DSS  
**Backup Frequency**: Continuous WAL Archiving + Hourly Custom Dump Snapshots  
**Retention Policy**: 90 Days Audio Recordings, 365 Days Redacted Transcripts, 7 Years Tax Invoices  

---

## 1. Automated Snapshot Schedules

### 1.1 Hourly Database Snapshots
Automated cron/task executing custom-format pg_dump:
```bash
docker exec sales-ai-postgres pg_dump -U postgres -d sales_ai_db \
  -Fc -f /tmp/backup_hourly.dump

# Encrypt artifact with AES-256 before upload
openssl enc -aes-256-cbc -salt -pbkdf2 \
  -in /tmp/backup_hourly.dump \
  -out /tmp/backup_hourly.dump.enc \
  -pass file:/etc/sales-ai/backup_key.bin

# Ship to offsite S3
aws s3 cp /tmp/backup_hourly.dump.enc s3://sales-ai-backups/hourly/$(date +%Y%m%d_%H%M%S).dump.enc
```

---

## 2. Audio & Transcript Retention Lifecycle

1. **Customer Audio Files (`voice_recordings`)**:
   - Encrypted at rest in S3 (`AES-256`).
   - S3 Lifecycle Rule: Transition to GLACIER at 30 days; permanent purge at **90 days**.
2. **Conversation Transcripts (`voice_transcripts`)**:
   - PII redacted at ingestion (CIN, bank cards, phone numbers).
   - Stored in PostgreSQL with RLS.
   - Retained for **365 days** unless customer exercises right to erasure (Moroccan Law 09-08 / GDPR).
3. **Legal Commercial Documents (`invoices`, `sales_orders`)**:
   - Immutable audit logs and tax invoices retained for **10 years** in compliance with Moroccan Commercial Code (Code de Commerce).

---

## 3. Data Subject Access & Erasure (DSAR) Procedure

When an authenticated customer requests data erasure:
1. Verify identity via caller verification OTP or government CIN check.
2. Execute tenant-scoped programmatic erasure workflow:
   ```python
   await privacy_service.execute_right_to_erasure(
       tenant_id=tenant_id,
       contact_id=customer_contact_id,
       redact_transcripts=True,
       purge_audio_recordings=True
   )
   ```
3. Retain anonymized transaction logs strictly for legal tax accounting.
