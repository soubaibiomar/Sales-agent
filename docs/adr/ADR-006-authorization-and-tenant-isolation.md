# ADR-006: Server-Side Authorization, RBAC/ABAC, and Tenant Isolation

## Status
Accepted

## Date
2026-11-18

## Context
Multi-tenant enterprise platforms are frequent targets for Broken Object Level Authorization (BOLA), Insecure Direct Object References (IDOR), and privilege escalation attacks (Baseline Controls 04, 05, 06, 09, 15, 33, 34, 49, 55). Furthermore, AI agents equipped with tools can inadvertently act as confused deputies, executing actions on resources across tenant boundaries if tool parameters are unverified.

## Decision
1. **Server-Side Identity Establishment**:
   - Client-provided headers (e.g. `X-Tenant-ID`, `X-User-ID`, `role`) are rejected or ignored.
   - Authentication is performed via standard OIDC / OAuth2 JSON Web Tokens (JWT) cryptographically verified using public keys (RS256) issued by Keycloak or equivalent IdP.
   - The verified token contains `sub` (user_id), `tenant_id`, and assigned `roles`.
2. **Context Propagation & Defense-in-Depth**:
   - An immutable `SecurityContext` is constructed during request authentication and bound to the request's asynchronous execution context (`contextvars`).
   - Every API endpoint, domain service call, and AI tool execution retrieves tenant identity strictly from `SecurityContext.tenant_id`.
   - Database sessions execute `SET LOCAL app.current_tenant_id = :tenant_id;` on every transaction, ensuring PostgreSQL RLS blocks cross-tenant access regardless of application logic bugs.
3. **Role-Based & Attribute-Based Access Control (RBAC / ABAC)**:
   - Defined system roles: `platform_admin`, `tenant_admin`, `sales_manager`, `sales_rep`, `support_agent`, `customer`.
   - Access to sensitive domain operations (e.g. modifying pricing rules, issuing refunds, approving high discounts) requires explicit permission checks (`has_permission('quotes:approve')`).
   - MFA is strictly enforced for all administrative and management roles (`platform_admin`, `tenant_admin`, `sales_manager`).
4. **Tool Execution Guard**:
   - When an AI agent invokes a tool, the Tool Gateway injects the authenticated `SecurityContext` server-side.
   - AI models cannot pass or override `tenant_id` or `actor_id` in tool parameters.

## Invariants Enforced
- Zero cross-tenant data leakage across all REST APIs, WebSockets, RAG vector queries, and asynchronous worker tasks.
- Any request lacking valid authentication or attempting cross-tenant resource access fails closed with an HTTP 403 Forbidden and generates an immediate security audit event.

## Consequences
### Positive
- Robust, provable defense against OWASP API Security Top 10 vulnerabilities (BOLA, broken auth, lack of resource limits).
- Clear audit logs attributing every action to a verified user and tenant.

### Negative / Trade-offs
- Internal service-to-service calls must carry scoped signed service tokens.
- Slight performance cost for token validation and RLS session setup.

### Mitigation
- Public key caching with automated rotation (JWKS caching).
- Automated negative BOLA/IDOR test suites executed on every build.
