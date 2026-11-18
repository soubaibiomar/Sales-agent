# REQUIREMENTS TRACEABILITY CATALOG — SALES AI MANAGEMENT PLATFORM

## 1. ACTORS AND CAPABILITY BOUNDARIES

| Actor ID | Actor Name | Description | Capability Boundary |
|---|---|---|---|
| **ACT-01** | Customer (B2B / B2C) | External buyer or commercial lead | Product discovery, requesting verified quotes, checking own order/shipment status, scheduling appointments, returns, conversational support across web, WhatsApp, and customer voice. |
| **ACT-02** | Sales Representative | Internal sales executive | Managing assigned leads, pipeline opportunities, customer briefs, generating draft quotes, conducting sales calls with copilot assistance. |
| **ACT-03** | Support & Operations Agent | Warehouse & support specialist | Resolving customer tickets, receiving human conversation handoffs, managing warehouse pick/pack, inspecting returns. |
| **ACT-04** | Sales Manager / Owner | Sales director or business executive | Reviewing pipeline velocity, approving special discount tiers, configuring commercial policies, accessing manager voice copilot briefings. |
| **ACT-05** | Tenant Administrator | Company administrator | Managing company users, roles, channel integrations (WhatsApp, email, SIP trunks), viewing tenant usage and invoices. |
| **ACT-06** | Platform Administrator | Super admin / SRE | Multi-tenant platform provisioning, infrastructure health, system audits, platform-wide security and incident response. |

---

## 2. CORE END-TO-END USER JOURNEYS

### Journey 1: Inbound Omnichannel Discovery to Verified Quotation
- **Step 1.1**: Customer arrives via WhatsApp or Web Chat, asking about enterprise product specifications.
- **Step 1.2**: Router classifies intent as conversational inquiry; Supervisor invokes Product & Catalog Specialist.
- **Step 1.3**: Customer requests bulk purchase for 500 units with custom delivery.
- **Step 1.4**: Quotation Specialist checks Pricing Service for volume discount rules; requested discount is 18%.
- **Step 1.5**: Pricing policy specifies discounts > 10% require Sales Manager approval.
- **Step 1.6**: System generates draft quote `Q-2026-001` in `PENDING_APPROVAL` status and dispatches an approval task to the Manager.
- **Step 1.7**: Customer is informed the quote is under review and will be delivered once authorized.

### Journey 2: Inbound Customer Voice Inquiry with Identity Gate
- **Step 2.1**: Customer calls company phone number via PSTN; SIP trunk connects to Voice Media Gateway.
- **Step 2.2**: Immediate automated disclosure: "This call is recorded and assisted by an AI voice agent for service quality."
- **Step 2.3**: Customer asks general questions about product warranty; Voice Agent responds using direct cached knowledge.
- **Step 2.4**: Customer asks: "Where is my order #ORD-9842 and what is my shipping address?"
- **Step 2.5**: Identity Verification Gate (SAI-01) triggers: Voice Agent informs customer an OTP has been sent via SMS/WhatsApp to the registered phone number.
- **Step 2.6**: Customer speaks the 4-digit OTP; Voice Gateway validates OTP against Redis token store.
- **Step 2.7**: Upon validation, Order Service retrieves tracking details and Voice Agent speaks the current delivery status.

### Journey 3: Manager Voice Copilot Briefing & Second-Factor Approval
- **Step 3.1**: Sales Manager opens mobile app, logs in with corporate OIDC credentials and completes TOTP MFA.
- **Step 3.2**: Manager taps Voice Copilot icon and asks: "What is our team pipeline closing rate this week, and do I have pending quote approvals?"
- **Step 3.3**: Manager Voice Copilot queries Analytics Service and Quote Service, speaking a concise executive summary.
- **Step 3.4**: Manager says: "Approve quote Q-2026-001 for Acme Corp at 18% discount."
- **Step 3.5**: High-Risk Action Gate (ADR-005, SAI-02) activates: Voice Copilot responds: "Approval prepared. For compliance, please confirm on your screen."
- **Step 3.6**: Mobile app displays prompt with exact quote terms; Manager taps "Sign & Approve" with biometric confirmation.
- **Step 3.7**: Quote state updates to `APPROVED` with cryptographic audit entry; customer receives notification via WhatsApp.

### Journey 4: Checkout, Stock Hold, and Payment Settlement Saga
- **Step 4.1**: Customer accepts quote and clicks checkout link.
- **Step 4.2**: Order Service creates order `ORD-7712` in `PENDING_PAYMENT` and triggers Temporal Checkout Workflow.
- **Step 4.3**: Inventory Service places a 15-minute pessimistic hold on the 500 units in Warehouse Casablanca.
- **Step 4.4**: Customer completes card payment via Stripe/CMI checkout session.
- **Step 4.5**: Payment gateway dispatches webhook to backend with HMAC signature.
- **Step 4.6**: Webhook endpoint validates HMAC and verifies nonce against replay cache.
- **Step 4.7**: Payment Service commits settlement, Order Service advances status to `PAID`, Inventory Service converts hold to committed allocation, and official tax invoice PDF is generated and archived in S3.

---

## 3. MASTER REQUIREMENTS TRACEABILITY MATRIX

| Req ID | Domain | Actor | Requirement Description | Service Owner | API Contract Route | Test ID | Security Link |
|---|---|---|---|---|---|---|---|
| **REQ-IAM-01** | SaaS & IAM | ACT-05 | Tenant onboarding with cryptographic isolation and dedicated schemas/RLS. | IAMService | `POST /api/v1/tenants` | `TEST-IAM-001` | Control 05, 49 |
| **REQ-IAM-02** | SaaS & IAM | ACT-02 | OIDC / OAuth2 token authentication with RS256 validation. | AuthService | `POST /api/v1/auth/token` | `TEST-IAM-002` | Control 04, 26 |
| **REQ-IAM-03** | SaaS & IAM | ACT-04 | Mandatory MFA enforcement for administrative and management roles. | AuthService | `POST /api/v1/auth/mfa/verify` | `TEST-IAM-003` | Control 55, SAI-02 |
| **REQ-IAM-04** | SaaS & IAM | ACT-05 | Fine-grained RBAC/ABAC role assignment and permission verification. | PolicyService | `GET /api/v1/users/{id}/permissions` | `TEST-IAM-004` | Control 05, 34 |
| **REQ-OMN-01** | Omnichannel | ACT-01 | Web chat messaging with session resumption and history retrieval. | ConversationService | `POST /api/v1/conversations/web/messages` | `TEST-OMN-001` | Control 25, 70 |
| **REQ-OMN-02** | Omnichannel | ACT-01 | Inbound WhatsApp Business message processing via Meta Cloud API webhook. | WhatsAppAdapter | `POST /api/v1/webhooks/whatsapp` | `TEST-OMN-002` | Control 31, 59 |
| **REQ-OMN-03** | Omnichannel | ACT-01 | Inbound/outbound email thread tracking and automated drafting. | EmailAdapter | `POST /api/v1/webhooks/email` | `TEST-OMN-003` | Control 16, 21 |
| **REQ-OMN-04** | Omnichannel | ACT-02 | Seamless human agent takeover silencing autonomous AI responses. | ConversationSupervisor | `POST /api/v1/conversations/{id}/takeover` | `TEST-OMN-004` | SAI-11 |
| **REQ-VOI-01** | Voice AI | ACT-01 | Inbound SIP/WebRTC call reception with automated recording disclaimer. | VoiceGateway | `POST /api/v1/voice/inbound` | `TEST-VOI-001` | SAI-04, SAI-05 |
| **REQ-VOI-02** | Voice AI | ACT-01 | OTP challenge before disclosing private customer/order data over voice. | VoiceIdentityService | `POST /api/v1/voice/verify-otp` | `TEST-VOI-002` | SAI-01, SAI-03 |
| **REQ-VOI-03** | Voice AI | ACT-04 | Authenticated Manager Voice Copilot with session binding and step-up MFA. | ManagerVoiceService | `POST /api/v1/voice/manager/session` | `TEST-VOI-003` | SAI-02, Control 55 |
| **REQ-VOI-04** | Voice AI | ACT-04 | Restriction barring spoken voice from executing high-risk financial mutations. | ManagerVoiceService | `POST /api/v1/voice/manager/execute` | `TEST-VOI-004` | SAI-02, ADR-005 |
| **REQ-CRM-01** | CRM | ACT-02 | Lead capture, enrichment, and deduplication across channels. | CRMService | `POST /api/v1/crm/leads` | `TEST-CRM-001` | Control 16, 33 |
| **REQ-CRM-02** | CRM | ACT-02 | Sales pipeline opportunity stages and expected deal value tracking. | CRMService | `POST /api/v1/crm/opportunities` | `TEST-CRM-002` | Control 05, 33 |
| **REQ-CAT-01** | Catalog | ACT-05 | Product catalog management with SKU, pricing tiers, and tax codes. | CatalogService | `POST /api/v1/catalog/products` | `TEST-CAT-001` | Control 05, 51 |
| **REQ-CAT-02** | Catalog | ACT-01 | Real-time product search with semantic embedding and filtering. | CatalogService | `GET /api/v1/catalog/search` | `TEST-CAT-002` | Control 16, SAI-06 |
| **REQ-QTE-01** | Quotes | ACT-02 | Dynamic quotation generation with deterministic tax and discount math. | QuoteService | `POST /api/v1/quotes` | `TEST-QTE-001` | Control 57, SAI-08 |
| **REQ-QTE-02** | Quotes | ACT-04 | Multi-tier approval workflow for discounts exceeding policy thresholds. | ApprovalService | `POST /api/v1/quotes/{id}/approve` | `TEST-QTE-002` | Control 09, 42 |
| **REQ-ORD-01** | Orders | ACT-01 | Order creation and checkout state machine (DRAFT -> PENDING -> PAID). | OrderService | `POST /api/v1/orders` | `TEST-ORD-001` | Control 57, 58 |
| **REQ-ORD-02** | Orders | ACT-03 | Official tax-compliant invoice generation with sequential numbering. | InvoiceService | `POST /api/v1/orders/{id}/invoice` | `TEST-ORD-002` | Control 42, ADR-008 |
| **REQ-PAY-01** | Payments | ACT-01 | Payment gateway checkout session initiation (Stripe / CMI). | PaymentService | `POST /api/v1/payments/checkout-session` | `TEST-PAY-001` | Control 32, ADR-001 |
| **REQ-PAY-02** | Payments | ACT-06 | Webhook signature verification and replay prevention. | PaymentService | `POST /api/v1/webhooks/stripe` | `TEST-PAY-002` | Control 31, 59 |
| **REQ-INV-01** | Inventory | ACT-03 | Multi-warehouse stock tracking and pessimistic 15-minute checkout hold. | InventoryService | `POST /api/v1/inventory/reserve` | `TEST-INV-001` | Control 58, ADR-001 |
| **REQ-INV-02** | Inventory | ACT-03 | Automatic stock hold release via Temporal workflow upon payment timeout. | TemporalWorker | `N/A (Temporal Activity)` | `TEST-INV-002` | ADR-007 |
| **REQ-LOG-01** | Logistics | ACT-03 | Purchase order generation to suppliers based on low stock triggers. | ProcurementService | `POST /api/v1/procurement/orders` | `TEST-LOG-001` | Control 05, 42 |
| **REQ-LOG-02** | Logistics | ACT-01 | Shipping label generation, carrier dispatch, and shipment tracking. | LogisticsService | `POST /api/v1/logistics/shipments` | `TEST-LOG-002` | Control 23, 33 |
| **REQ-SUP-01** | Support | ACT-01 | Support ticket creation, SLA tracking, and resolution workflows. | SupportService | `POST /api/v1/support/tickets` | `TEST-SUP-001` | Control 16, 33 |
| **REQ-SUP-02** | Support | ACT-01 | Returns & refunds request processing with deterministic policy checks. | ReturnsService | `POST /api/v1/support/returns` | `TEST-SUP-002` | Control 57, SAI-08 |
| **REQ-SCH-01** | Scheduling | ACT-01 | Sales demo and service appointment booking with calendar sync. | SchedulingService | `POST /api/v1/scheduling/appointments`| `TEST-SCH-001` | Control 58 |
| **REQ-AGY-01** | AI Core | ACT-01 | Intent classification and routing (Direct Read vs Reasoning Turn). | InboundRouter | `POST /api/v1/ai/route` | `TEST-AGY-001` | ADR-004 |
| **REQ-AGY-02** | AI Core | ACT-01 | PII redaction and multilingual prompt injection detection. | ModelGateway | `POST /api/v1/ai/sanitize` | `TEST-AGY-002` | SAI-09, SAI-10 |
| **REQ-AGY-03** | AI Core | ACT-01 | Typed tool gateway executing domain actions with server-injected context. | ToolGateway | `POST /api/v1/ai/tools/execute` | `TEST-AGY-003` | Control 40, SAI-07 |
| **REQ-AGY-04** | AI Core | ACT-01 | Deterministic Output Guard verifying commercial claims against DB. | OutputGuard | `POST /api/v1/ai/verify-claims` | `TEST-AGY-004` | Control 66, SAI-08 |
| **REQ-ANL-01** | Analytics | ACT-04 | Executive revenue, pipeline velocity, and conversion rate analytics. | AnalyticsService | `GET /api/v1/analytics/dashboard` | `TEST-ANL-001` | Control 05, 06 |
| **REQ-ANL-02** | Analytics | ACT-04 | Predictive sales forecasting model based on historical deal stages. | ForecastingService | `GET /api/v1/analytics/forecast` | `TEST-ANL-002` | Control 05 |
| **REQ-SEC-01** | Security | ACT-06 | Cryptographically chained, append-only security and operational audit logs. | AuditService | `GET /api/v1/audit/logs` | `TEST-SEC-001` | Control 42, ADR-010 |
| **REQ-SEC-02** | Security | ACT-06 | Automated data retention lifecycle purging voice audio after 90 days. | RetentionWorker | `N/A (Cron / Lifecycle)` | `TEST-SEC-002` | SAI-04, ADR-008 |
