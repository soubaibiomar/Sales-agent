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
