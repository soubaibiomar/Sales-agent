# 08 — Frontend UI/UX Inspection

## Method
- **Two delivery modes captured** with headless Edge, 28 pages × 2 viewports × 2 modes = **112 PNGs**, 0 failures:
  - `served_8765/` — the real product: FastAPI `/app`, with its own CSP, running against PostgreSQL as `sales_app_user`.
  - `static_nocsp_8790/` — the same files from a plain static server, no CSP. This mode shows the design intent and is how Gemini's screenshots were most likely produced.
  - Location: `evidence/claude-inspection/screenshots/`.
  - Viewports: **1440×900** and **390×844**.
- **Interactive checks** in the built-in browser: console errors, script inventory, navigation links.
- **Page metrics:** `evidence/claude-inspection/static/frontend_page_metrics.csv`.
- **Reference images:** the three agreed preview images (Executive Dashboard, Omnichannel Inbox + AI Assistant, Quotation & Order workspace) were **not found** in the repository or on the Desktop, Downloads or Documents. This comparison therefore uses the written identity specification (AGENTS.md §4 and the brief) plus page purpose. Gemini's own screenshots in `evidence/frontend-ui-ux/` were not used as the reference.

## Is it a cohesive SaaS application?
**No.** It is a collection of 28 standalone HTML pages that share a CSS file:

- **Navigation:**
  - The sidebar comes in **6 different variants** (9, 10, 11, 13, 26 or 32 items).
  - The executive dashboard links only 13 destinations, `pipeline.html` twice; e.g. the voice pages are not linked.
  - Labels differ between pages ("CRM", "CRM & Pipeline", "Conversations", "Omnicanal").
- **Authentication:** there is no login page. The user ("Omar A. / Administrateur") and tenant ("Atlas Commerce") are hardcoded in `app_shell.js:11-20`.
- **Live data:**
  - **13 / 28 pages make zero API calls**, including the dashboard, inbox, quote builder, approvals, catalog and checkout.
  - The pages that do call the API send `X-Tenant-ID: tenant-acme-corp` and `Bearer mock-manager-token`, so they depend on the insecure header fallback (F-01).

## As served by the product (critical)
- **The backend's own CSP breaks most pages.** The backend sends `Content-Security-Policy: default-src 'self'`:
  - **26 / 28 pages** contain inline `<style>` blocks and **20** contain inline `<script>`; all of those are blocked.
  - Google Fonts are blocked too.
  - The dashboard alone logged 81 console violations.
- **Visible effects:**
  - **Inbox** collapses into a single unstyled column (`served_8765/inbox_1440x900.png`).
  - **Pipeline** shows KPI cards but an empty board.
  - Interactive behaviour that lives in inline scripts does not run.

## Visual fidelity (design intent, CSP-free mode)
| Aspect | Assessment |
|---|---|
| Identity | **Strong match** to the agreed direction: deep forest-green sidebar (#0A3A2A family), white/neutral workspace, emerald highlights, Inter typography, restrained shadows. |
| Executive dashboard | KPI cards with sparklines, pipeline stage strip, revenue line chart, donut, AI assistant panel, activity feed. Close to the "Executive Dashboard" brief. The right column is clipped at 1440 px. |
| Omnichannel inbox | Three panes (list / thread with AI analysis card / client & deal panel), suggested replies. Close to the brief. |
| Quotation workspace | Client picker, quote editor with line items and discounts, AI recommendations, approval workflow. Close to the brief; the right panel is clipped. |
| Tables & charts | Clean and consistent; the charts are hand-drawn SVG with static data. |
| Mobile (390 px) | Cards overflow horizontally (KPI grid cut off); the sidebar collapses to a hamburger. **Not truly responsive.** |
| Voice pages | A different sidebar (26 items, emoji icons), a separate dark header bar, an empty transcript area — visually inconsistent with the rest. |
| Accessibility | Not audited with a tool. Observed: icon-only buttons lack labels in places; contrast of green-on-dark navigation is acceptable. Status: NOT VERIFIED. |
| Loading / empty / error states | Largely absent; when data is static there is no loading state. Pipeline shows an empty board without a message when its script fails. |
| Gestelyo screenshots | Inspiration only. No copied branding observed. |

## Controls that look functional but are disconnected
- **Quote builder:** "Nouveau Devis", "Ajouter Article", the approval workflow, the discount fields and the "Appliquer" recommendation buttons have no API wiring (0 fetch calls).
- **Dashboard:** "Lancer une action IA", date-range picker, tenant selector (stores only a name in `localStorage`).
- **Inbox:** send box, suggested replies, "Créer un devis", "Convertir en opportunité".
- **Voice agent:** microphone button (starts a session only; no audio capture), OTP field (accepts `123456`).

## Score rationale
The visual design is credible and close to the agreed identity. As an *application*, the frontend is a high-fidelity mock-up: no auth, mostly static data, broken by its own server's CSP, inconsistent navigation.
