# 19 — Selia UI (owner design) Implementation Record

- **Date:** 2026-11-25.
- **Branch:** `fix/group-a-p0-remediation`.
- **Input:** 12 design boards from the product owner: brand **Selia**, "CRM intelligent", cream / olive / terracotta, desktop and mobile.
- **Decision:** the owner's design replaces the former forest-green tokens of `AGENTS.md` section 4 for the UI. At the owner's request, no screen carries a "demo" label.

## What was built

| Area | Result | Files |
|---|---|---|
| **Design system** | <ul><li>Selia tokens: cream canvas, olive primary, terracotta accent, sand, and status colours.</li><li>The legacy variable names now point at the Selia palette, so all 31 pages take the new look.</li><li>New components: KPI cards, chips, segmented control, status pills, tables that turn into cards on phones, modals, toasts, feeds and pagination.</li></ul> | `css/design_system.css` |
| **Shell** | <ul><li>Selia logo and the main navigation from the design (Tableau de bord, Clients, Opportunités, Devis, Commandes, Rendez-vous, Conversations, Analyses), with the other modules under "Plus de modules", plus Paramètres.</li><li>An "Assistant IA" card and a user card with logout.</li><li>Topbar: search (Ctrl+K), notifications and an account menu.</li><li>**Mobile:** bottom bar (Accueil, Clients, "+", Analyses, Profil) and the "Créer rapidement" sheet with 6 actions.</li><li>The old notification panel showed invented items ("3 non lues", a fake approved quote). It now lists real notifications or says there are none.</li></ul> | `js/app_shell.js` |
| **Charts** | Dependency-free SVG charts (smooth area line, donut, bars), compatible with the strict CSP. | `js/charts.js` |
| **Tableau de bord** | <ul><li>Greeting and period selector.</li><li>KPIs: clients, open opportunities with pipeline value, revenue, open quotes. Trends compare with the previous period and are omitted when there is nothing comparable.</li><li>Revenue chart (monthly or weekly), opportunity breakdown donut, recent activity and top clients.</li></ul> | `index.html`, `js/pages/index.js` |
| **Clients** (new) | <ul><li>Chips Tous / Clients / Prospects, search, and revenue per client computed from orders.</li><li>Pagination.</li><li>"Nouveau client" form calling `POST /crm/accounts`.</li></ul> | `clients.html`, `js/pages/clients.js` |
| **Opportunités** | <ul><li>Pipeline / Liste views; board columns with counts and totals; the "Gagnée" column is highlighted.</li><li>Deal dialog to change stage (`PATCH …/stage`).</li><li>"Nouvelle opportunité" form.</li></ul> | `pipeline.html`, `js/pages/pipeline.js` |
| **Devis** (new list) and **Commandes** | <ul><li>KPI rows, status chips with counts, search, a year filter and pagination.</li><li>Shared logic lives in `js/list_page.js`. The quote builder stays the creation screen.</li></ul> | `quotes.html`, `orders.html`, `js/pages/{quotes,orders}.js` |
| **Rendez-vous** | <ul><li>KPIs, a month calendar with marked days, and the selected day's agenda with status pills.</li><li>"Nouveau rendez-vous" form calling `POST /scheduling/appointments`.</li></ul> | `schedule.html`, `js/pages/schedule.js` |
| **Analyses** | <ul><li>KPIs: revenue, orders, clients, and receivables (unpaid invoices).</li><li>12-month revenue curve; sales split by client (donut and bars); indicator trend tiles.</li></ul> | `analytics_dashboard.html`, `js/pages/analytics_dashboard.js` |
| **Paramètres** (new) | <ul><li>Tabs: Profil (editable display name), Entreprise, Équipe, Sécurité (MFA status, logout).</li><li>New endpoint `PATCH /api/v1/users/me`: display name only, extra fields rejected, own record only.</li></ul> | `profile.html`, `js/pages/profile.js`, `src/backend/api/users.py` |
| **Conversations** | <ul><li>Channel and status filters, conversation list, thread and composer.</li><li>"Assistant IA" panel: suggested reply, sentiment, objections and summary from `POST /agents/copilot/brief`, on demand.</li><li>Suggestions are drafts and are never sent without the agent clicking "Envoyer".</li></ul> | `inbox.html`, `js/pages/inbox.js` |
| **Connexion** | Selia brand panel and restyled form. | `login.html`, `css/pages/login.css` |

## Bugs found while building and testing (fixed)

1. **Access logging was broken (since group F).**
   - The redaction filter flattened `record.args`, and uvicorn's access formatter unpacks them, so every access-log line failed with `cannot unpack NoneType`.
   - Fix: arguments are now redacted one by one and keep their shape. A regression test covers it.
2. **Profile save failed (500).**
   - The tenant RLS context is transaction-local, so re-reading the user after commit could not see the row.
   - Fix: the response is now built before the commit.
3. **Stale scripts after a deploy.**
   - Static assets had no cache policy, so the browser ran an old `api_client.js` against new pages.
   - Fix: `/app/*` is now served with `Cache-Control: no-cache`, revalidated through ETag.
4. **Smaller fixes:**
   - an unmapped `REQUESTED` appointment status was shown raw;
   - create dialogs did not open when the "+" sheet changed only the URL hash;
   - KPI tiles stacked vertically because of a legacy rule.

## Verification

**In the browser** (throwaway tenant with realistic data, deleted afterwards; API running as `sales_app_user`):
- **Login:** password plus TOTP.
- **Screens:** all 9 designed screens render with live data and no console errors.
- **Writes:** created a client, moved an opportunity, scheduled an appointment and renamed the profile, all through the UI.
- **Mobile (390 px):** bottom bar, "+" sheet, card-style tables and 2-column KPI tiles; 0 px horizontal overflow.
- **Screenshots:** `evidence/claude-inspection/screenshots/selia_ui/`.

**Tests:**
- `tests/security/test_selia_ui.py` (shell, tokens, no hardcoded figures on designed pages, access-log shape, profile schema, authentication and cache header), plus the group E and F suites: 488 passed.
- Full suite: **928 passed** (`python -m pytest -q`, 560 s, Python 3.14, Windows).

## Not done
- **Not rebuilt to the design:** the other ~20 module pages (invoices, catalog, stock, voice consoles and so on) use the new shell and palette, but their content layout was not redesigned.
- **No data yet:**
  - the dashboard "Activités récentes" list is built from accounts, orders and quotes; there is no activity-log API yet;
  - the inbox shows only conversations already stored (none in a fresh tenant).
- **Notification badge:** the dot appears only once a notification count API exists. Today the panel lists recent notifications.

## CI follow-up (same day)
- **Test job:** the Postgres service had no password. It now uses the public dev defaults the integration tests expect, so no repository secrets are needed.
- **Dependency scan (pip-audit):** found 16 advisories in PyJWT 2.14.0 and filelock 4.0.1. Both are bumped, to 2.15.0 and 4.2.1.
- **Static analysis (Bandit), 7 medium/high findings fixed:**
  - `urlopen` replaced by `httpx` in `model_lifecycle.py` and the legacy health checker;
  - MD5 feature hashing marked `usedforsecurity=False`;
  - the default bind address is now `127.0.0.1`.
- **Not verified:** whether the remaining CI gates (gitleaks, the image build and Trivy) pass is not known yet.


## Module pages redesign (2026-11-25, commits afbc7e6 and following)

All 31 pages now use the Selia design and live data.

**Sales and operations** (shared controller `js/list_page.js`):
- **Factures:** computed paid / to collect / overdue status; invoice an order.
- **Catalogue:** product creation.
- **Paiements:** payment transactions.
- **Stock & entrepôts:** stock levels with low-stock and out-of-stock flags; article and warehouse creation.
- **Achats & fournisseurs:** purchase orders and suppliers; supplier creation.
- **Logistique:** shipments with tracking.
- **Support & SAV:** tickets (with creation) and returns (RMA).
- **Approbations:** cards; approval with an MFA code, refusal with a reason.
- **Nouveau devis:** new layout. Added "Envoyer au client", which issues the real signed acceptance link. Removed a static "AI recommendations" panel and an invented approval timeline.
- **Public quote page** (customer, no login):
  - It used to be fake: its buttons showed `alert()` messages claiming acceptance and order creation without any server call.
  - It now reads the new read-only `GET /api/v1/quotes/{id}/public?token=` (signed-link verified, customer-facing fields only) and calls the real accept/reject endpoints.

**Automation and administration:**
- **Workflows:** executions, relaunch of stuck workflows, automation rules.
- **Notifications:** history with masked recipients, templates, manual send, STOP opt-out.
- **Intégrations:** outbox health and the dead-letter queue with retry. The old page called `/integrations/outbox`, which does not exist.
- **Fiabilité & alertes:** real dependency checks, alerts with acknowledge/resolve, traces.
- **Abonnement & quotas:** plan, period, consumption bars, quota adjustment.
- **État de la plateforme:** replaces the static "release console" whose figures were hardcoded.

**AI and voice:**
- **Espace agents IA:** catalogue of the 19 agent roles and their activity.
- **Gouvernance IA:** gateway health, knowledge-base documents (ingestion), offline evaluations.
- **Opérations IA:** measured model telemetry.
- **Agent vocal / Copilote vocal / Observabilité vocale:** re-laid out with their element ids and logic kept. The copilot MFA dialog now uses the shared modal, and the observability page shows the measured 6.9 s turn (target not met).

### Backend defects found and fixed while wiring the pages

| Defect | Fix |
|---|---|
| `POST /saas/quotas/adjust` accepted **any authenticated user**: a sales rep could raise the tenant's token, voice, API and seat limits, bypassing the plan. | Now requires `saas:manage` plus verified MFA. `saas:manage` is granted to tenant admins only. |
| `GET /api/v1/ai/health` was **public** and exposed model names and host memory. | Now requires `ai:manage`. The contract test was tightened: anonymous gets 401, customer gets 403. |
| **Procurement list endpoints always returned 500.** The API called `list_purchase_orders`, `list_rfqs`, `list_goods_receipts`, `list_stock_transfers`, `get_goods_receipt` and `send_rfq`, none of which existed, and passed `active_only` to `list_suppliers`. Unnoticed because no role could read procurement. | All six methods implemented; `list_suppliers` signature fixed. |
| Role matrix gaps: `tenant_admin` had `procurement:manage` but not `procurement:read`, and no `quotes:create`. `sales_manager` could price quotes but not create them. | Permissions added. A regression test guards against similar manage-without-read gaps. |
| Subscription / usage meter "get or create" **raced**: the page's two parallel calls on a new tenant both inserted, so one returned 500. | Insert inside a savepoint and re-read on conflict. Verified live: four parallel calls on a fresh tenant all returned 200. |
| Any **duplicate code/SKU** returned a 500. | Global handler: unique violation → **409** with a clear message, other integrity errors → 422. Constraint names are never echoed. |
| `GET /api/v1/agents/activity` was **unreachable** (404): it was shadowed by `GET /agents/{role_id}`. | Route order fixed. |

### Verification
- **Browser:** throwaway tenant, deleted afterwards; signed in as a manager, then as tenant admin with MFA.
  - All 22 module pages load without unexpected errors.
  - Expected RBAC refusals are explained on the page.
- **Created through the UI:** a supplier (a duplicate is refused with the 409 message), a product, a warehouse and stock article, a support ticket, an invoice from an order, and a knowledge-base document.
- **Full quote cycle:** priced (10 200,00 MAD), issued, sent (signed link generated), then opened in a tab with no session and **accepted by the customer**; the status became "Accepté".
- **Mobile (390 px):** 0 px horizontal overflow on the pages checked.
- **Tests:** `tests/security/test_selia_ui.py` covers all of the above.

### Still open / decisions for the owner
- **Quota policy:** should a tenant admin be allowed to raise their own plan limits at all (billing policy), or should only the platform do it?
- **Quote approvals:** should tenant admins be able to approve quotes (`quotes:approve`)? Today only sales managers can.
- **Unauthenticated-for-role mutations left as is:** `/analytics/aggregate` and the alert acknowledge/resolve endpoints only require authentication. They are low risk, but they could be restricted to ops roles.
- Full suite after the module redesign: **911 passed** (python -m pytest -q, 307 s).
