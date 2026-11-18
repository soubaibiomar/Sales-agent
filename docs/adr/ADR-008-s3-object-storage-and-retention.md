# ADR-008: Encrypted S3-Compatible Object Storage and Lifecycle Data Retention

## Status
Accepted

## Date
2026-11-18

## Context
The platform generates and consumes large binary files: customer contracts, PDF quotation proposals, official tax invoices, supplier spec sheets, customer support attachments, and audio recordings of inbound/outbound phone and voice copilot sessions. Storing binary assets in the transactional database degrades PostgreSQL query performance and complicates backups. Storing them insecurely on local filesystems or public cloud buckets creates critical data breach vulnerabilities (Baseline Controls 08, 21, 22, 48; SAI-04).

## Decision
1. **S3-Compatible Private Storage**:
   - Store all unstructured binary assets in private, S3-compatible object storage (AWS S3 in cloud, MinIO for local/on-premise environments).
   - Dedicated bucket architecture:
     - `sales-ai-documents`: PDFs, invoices, quotation attachments, customer contracts.
     - `sales-ai-recordings`: Raw call audio, voicemail snippets, voice copilot audio segments.
   - All buckets are private by default (`BlockPublicAcls`, `BlockPublicPolicy`, `IgnorePublicAcls`, `RestrictPublicBuckets`). No direct public URL access.
2. **Access Control via Pre-Signed Scoped URLs**:
   - Access to documents and audio files is mediated strictly via backend domain services generating time-limited pre-signed URLs (expiration <= 15 minutes).
   - The backend validates tenant membership and user permissions before issuing a pre-signed download or upload URL.
3. **Encryption at Rest and in Transit**:
   - Server-Side Encryption (SSE-S3 or SSE-KMS) enforced for all stored objects.
   - All object transfers require TLS 1.3 in transit.
4. **Automated Lifecycle & Data Retention (SAI-04, GDPR, Moroccan Law 09-08)**:
   - Voice audio bucket (`sales-ai-recordings`) configures an automated S3 Lifecycle Rule: objects expire and are permanently deleted after **90 days**.
   - Redacted text transcripts are retained for **365 days** in database archives, unless a customer DSAR erasure request is received.
   - Invoices and tax documents are retained for legal audit requirements (10 years) with S3 Object Lock (WORM - Write Once, Read Many) where applicable.

## Invariants Enforced
- Zero public buckets. Direct unauthenticated access to customer contracts or voice recordings is impossible.
- File uploads are validated server-side for magic byte MIME types, file size limits (<= 25MB), and stored under random UUID paths preventing path traversal.

## Consequences
### Positive
- Offloads heavy binary storage from PostgreSQL.
- Transparent compliance with statutory data privacy limits on voice recordings.
- Complete audit trail of who generated pre-signed URLs to download customer data.

### Negative / Trade-offs
- File viewing requires an extra API call to obtain a temporary pre-signed URL.
- S3 / MinIO infrastructure must be provisioned and monitored.

### Mitigation
- MinIO instance included in local Docker Compose stack for seamless local development and automated CI testing.
