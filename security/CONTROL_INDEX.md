# ORIGINAL 70 SECURITY CONTROLS — INDEX (FROM PROVIDED WORKBOOK)

Source: `references/70-security.xlsx` (original STOKORA security audit tracker). Preserve original priority, applicability and status; assess Sales AI-specific priority in a separate column/report. The presence of a control does **not** constitute successful verification.

| ID | Original control | Original priority | Original applicability | Original status |
|---|---|---|---|---|
| 01 | Exposed database credentials | P0 | Applicable | NON VERIFIE |
| 02 | Public .env files | P0 | Applicable | NON VERIFIE |
| 03 | Hardcoded API keys or secrets | P0 | Applicable | NON VERIFIE |
| 04 | Weak or missing authentication | P0 | Applicable | NON VERIFIE |
| 05 | Missing server-side authorization | P0 | Applicable | NON VERIFIE |
| 06 | Cross-user data access | P0 | Applicable | NON VERIFIE |
| 07 | Open database permissions | P0 | Applicable | NON VERIFIE |
| 08 | Misconfigured Firebase / Supabase / S3 | P2 | Conditionnel | NON VERIFIE |
| 09 | Unprotected admin routes | P0 | Applicable | NON VERIFIE |
| 10 | Production debug tools exposed | P1 | Applicable | NON VERIFIE |
| 11 | Build logs leaking secrets | P1 | Applicable | NON VERIFIE |
| 12 | Verbose production errors | P1 | Applicable | NON VERIFIE |
| 13 | Secrets in Git history | P0 | Applicable | NON VERIFIE |
| 14 | Secrets shipped in frontend JavaScript | P1 | Applicable | NON VERIFIE |
| 15 | Client-side-only security checks | P0 | Applicable | NON VERIFIE |
| 16 | Missing input validation | P0 | Applicable | NON VERIFIE |
| 17 | SQL injection | P0 | Applicable | NON VERIFIE |
| 18 | NoSQL injection | P2 | Conditionnel | NON VERIFIE |
| 19 | Cross-site scripting (XSS) | P1 | Applicable | NON VERIFIE |
| 20 | Cross-site request forgery (CSRF) | P1 | Applicable | NON VERIFIE |
| 21 | Insecure file uploads | P0 | Applicable | NON VERIFIE |
| 22 | Path traversal | P0 | Applicable | NON VERIFIE |
| 23 | Server-side request forgery (SSRF) | P0 | Applicable | NON VERIFIE |
| 24 | Broken password-reset flows | P1 | Applicable | NON VERIFIE |
| 25 | Weak session management | P0 | Applicable | NON VERIFIE |
| 26 | Weak or incorrectly validated JWTs | P0 | Applicable | NON VERIFIE |
| 27 | Overly permissive CORS | P1 | Applicable | NON VERIFIE |
| 28 | Missing rate limits | P0 | Applicable | NON VERIFIE |
| 29 | Unprotected staging or test environments | P1 | Applicable | NON VERIFIE |
| 30 | Default credentials left unchanged | P1 | Applicable | NON VERIFIE |
| 31 | Webhook signatures not verified | P2 | Conditionnel | NON VERIFIE |
| 32 | Frontend-only payment checks | P2 | Conditionnel | NON VERIFIE |
| 33 | IDOR / BOLA | P0 | Applicable | NON VERIFIE |
| 34 | APIs trusting user-controlled roles or IDs | P0 | Applicable | NON VERIFIE |
| 35 | Sensitive data in logs | P1 | Applicable | NON VERIFIE |
| 36 | Sensitive source maps or build artifacts | P1 | Applicable | NON VERIFIE |
| 37 | Vulnerable or abandoned dependencies | P0 | Applicable | NON VERIFIE |
| 38 | Malicious or compromised packages | P1 | Applicable | NON VERIFIE |
| 39 | Prompt injection | P2 | Conditionnel | NON VERIFIE |
| 40 | AI tools bypassing user permissions | P2 | Conditionnel | NON VERIFIE |
| 41 | Excess database privileges | P0 | Applicable | NON VERIFIE |
| 42 | Missing audit logs | P0 | Applicable | NON VERIFIE |
| 43 | No security monitoring or alerts | P1 | Applicable | NON VERIFIE |
| 44 | No tested backup / restore plan | P0 | Applicable | NON VERIFIE |
| 45 | Public internal dashboards | P0 | Applicable | NON VERIFIE |
| 46 | Missing security headers | P1 | Applicable | NON VERIFIE |
| 47 | Unsafe cookie settings | P1 | Applicable | NON VERIFIE |
| 48 | Sensitive data unprotected in transit / at rest | P0 | Applicable | NON VERIFIE |
| 49 | Poor tenant isolation | P0 | Applicable | NON VERIFIE |
| 50 | Over-trusting AI-generated code | P1 | Applicable | NON VERIFIE |
| 51 | Mass assignment / over-posting | P0 | Applicable | NON VERIFIE |
| 52 | Command / OS injection | P1 | Applicable | NON VERIFIE |
| 53 | Unsafe deserialization | P1 | Applicable | NON VERIFIE |
| 54 | Misconfigured OAuth / OIDC / social login | P1 | Applicable | NON VERIFIE |
| 55 | No MFA on privileged accounts | P0 | Applicable | NON VERIFIE |
| 56 | Account enumeration | P1 | Applicable | NON VERIFIE |
| 57 | Business-logic abuse | P0 | Applicable | NON VERIFIE |
| 58 | Race conditions | P0 | Applicable | NON VERIFIE |
| 59 | Webhook replay / duplicate processing | P2 | Conditionnel | NON VERIFIE |
| 60 | Overpowered CI/CD credentials | P0 | Applicable | NON VERIFIE |
| 61 | Untrusted build actions or scripts | P1 | Applicable | NON VERIFIE |
| 62 | Unpinned build dependencies | P0 | Applicable | NON VERIFIE |
| 63 | Security checks fail open | P0 | Applicable | NON VERIFIE |
| 64 | Missing resource limits | P0 | Applicable | NON VERIFIE |
| 65 | AI sensitive-information disclosure | P2 | Conditionnel | NON VERIFIE |
| 66 | Unsafe use of AI output | P2 | Conditionnel | NON VERIFIE |
| 67 | AI agents have excessive agency | P2 | Conditionnel | NON VERIFIE |
| 68 | Sensitive browser storage | P1 | Applicable | NON VERIFIE |
| 69 | Open redirects | P1 | Applicable | NON VERIFIE |
| 70 | Unsecured GraphQL / WebSocket / realtime endpoints | P2 | Conditionnel | NON VERIFIE |

Initial totals: 70 controls; P0=35, P1=24, P2=11; original applicable=59, conditional=11; statuses all NON VERIFIE.
