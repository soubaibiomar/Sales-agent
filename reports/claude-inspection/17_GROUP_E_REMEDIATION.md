# 17 — Group E (Frontend) Remediation Record

- **Branch:** `fix/group-a-p0-remediation`, continuing after commit `8e831d2`.
- **Scope:** remediation group E of report 11: findings **F-20** (frontend was a static mock-up; CSP broke it), **F-32** (UI defects), and the browser half of **F-15** (microphone capture and playback).
- **Stack decision (report 11, E.1):** the static HTML pages are kept. All inline CSS and JS was moved into files so the backend can send a strict CSP with **no** `'unsafe-inline'` scripts and no nonces. A Next.js rewrite was not attempted.

## What changed

| Area | Fix | Main files |
|---|---|---|
| **Strict CSP (F-20)** | <ul><li>`scripts/frontend_csp_build.py` (idempotent) moved every inline `<style>` to `css/pages/<page>.css` and every inline `<script>` to `js/pages/<page>.js`. It also dropped 7 near-duplicate script blocks, including the duplicated voice block (F-32).</li><li>It converted 107 `on*="…"` handlers to `data-on-*` attributes bound by `js/pages/<page>.handlers.js`.</li><li>Google Fonts links and the `@import` in `design_system.css` are removed.</li><li>New header: `default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`, plus `Permissions-Policy: microphone=(self)`.</li><li>Only static `style=""` attributes remain tolerated (`style-src-attr`).</li></ul> | `src/backend/main.py`, `scripts/frontend_csp_build.py`, `src/frontend/css/pages/*`, `src/frontend/js/pages/*` |
| **Login and session** | <ul><li>New `login.html`: email/password, optional organisation ID, and a TOTP second step for privileged roles.</li><li>`js/api_client.js` (`SalesApi`):<ul><li>keeps tokens in `sessionStorage`;</li><li>adds the Bearer token to every call;</li><li>**strips** any `X-Tenant-ID` / `Authorization` header a page sets;</li><li>refreshes once on 401, otherwise returns to login;</li><li>guards every page except `login.html` and `quote_view.html`.</li></ul></li><li>The `next=` redirect is allowlisted to local `*.html` pages.</li><li>Logout calls `/auth/logout`.</li></ul> | `src/frontend/login.html`, `js/pages/login.js`, `js/api_client.js` |
| **One navigation and real identity** | <ul><li>Six navigation variants are replaced by one `NAV` definition rendered by `app_shell.js` into `<div data-app-nav>` on every app page.</li><li>The fake identity is removed: "Omar A." / "Administrateur" / "Atlas Commerce" / "Bonjour Omar", and the notification counters (12, 3).</li><li>Name, role, tenant and greeting now come from the signed-in session.</li><li>The two voice pages had a second legacy header and nav (and a nested `<main>`). Both are replaced by the standard page header.</li></ul> | `js/app_shell.js`, all `*.html` |
| **API wiring with loading, empty and error states** | **Live:**<ul><li>Dashboard KPIs: `analytics/overview`, `quotes`, `crm/accounts`.</li><li>Inbox: conversations, timeline and reply.</li><li>Approvals: pending list and MFA decision.</li><li>Orders, inventory, invoices, pipeline, workflow traces and alerts.</li><li>**Quote builder (new):** live customers and catalogue; `POST /quotes`, then `PUT /quotes/{id}/items`, then `POST /quotes/{id}/issue`.</li></ul>Quote builder rules:<ul><li>Every amount shown comes from the server's `QuoteResponse`. The page does **no price arithmetic** (invariant 2).</li><li>Editing a line clears the displayed totals until the quote is re-priced.</li></ul>Fabricated fallbacks are removed: the fake pipeline deals and the fake "BRF-09-VERIFIED" brief now show an error state instead. | `js/data_views.js`, `js/pages/{index.live,inbox,approvals.live,orders,inventory,invoices,pipeline,quote_builder,workflow_reliability_dashboard}.js` |
| **Honest demo labelling** | Widgets that are still illustrative carry a visible "Données d'exemple" chip. The 8 pages with no API calls yet carry `<body data-demo-page>`, which renders a banner saying the data are examples: catalog, checkout, logistics, procurement, quote_view, release_console, schedule, support. | `js/data_views.js` (`markDemo`, `markDemoPage`) |
| **XSS hardening** | <ul><li>`scripts/frontend_escape_templates.py` wrapped about 90 `${…}` interpolations in `SalesViews.esc()`.</li><li>New and rewritten scripts render user and model text with `textContent`.</li></ul> | `scripts/frontend_escape_templates.py`, `js/pages/*` |
| **Browser voice (F-15)** | `voice_agent.js` was rewritten:<ol><li>An authenticated session is created via `POST /voice/sessions`.</li><li>A WebSocket opens on `/voice/ws/{id}?token=<signed session token>`.</li><li>`getUserMedia` feeds an AudioWorklet (`js/audio/pcm-capture-worklet.js`) at 16 kHz, which sends 20 ms PCM16 frames.</li><li>`TURN_COMPLETED.audio_base64` WAV replies play through a Blob URL.</li></ol>Also:<ul><li>barge-in, caller OTP request and verify, and handoff run over the stream or REST;</li><li>a typed-turn fallback is available when the microphone is refused;</li><li>the seeded caller number `+212661234567` is removed.</li></ul>The manager copilot no longer sends a client tenant header, checks HTTP status, and uses `textContent`. | `js/pages/voice_agent.js`, `js/audio/pcm-capture-worklet.js`, `js/pages/voice_copilot.js` |
| **Responsive (F-32)** | <ul><li>`1fr` changed to `minmax(0,1fr)` in page grids.</li><li>Fixed-count KPI rows moved from inline styles to `.kpi-grid--4/--5`, which only apply at 1100 px and above.</li><li>Compact topbar below 600 px.</li><li>Wide tables and tab bars scroll inside their own box on phones.</li><li>Voice layouts use a single column below 900 px.</li><li>Fixed an earlier rewrite bug that produced invalid `minmax(220px, minmax(0, 1fr))` in 7 page stylesheets, which browsers silently dropped.</li></ul> | `css/design_system.css`, `css/pages/*` |

## Verification (executed, 2026-11-24)

**Live app**
- **Setup:** uvicorn on `127.0.0.1:8765`, connected as the least-privileged RLS role `sales_app_user`.
- **Test data:** a throwaway tenant and user created through the superuser, with one test account and one test product. All of it was deleted afterwards.
- **Browser:** the built-in browser pane.

**Login, MFA and authorisation**
- Unauthenticated `index.html` redirects to `login.html?next=index.html`.
- `sales_rep` login: dashboard KPIs load from the API (0,00 MAD, 0 orders, 3 open quotes, 1 client). The topbar shows the real name, role and tenant.
- With `sales_manager` added, login requires the TOTP step. The step was completed with a generated code; the session shows `mfaVerified: true` and returns to `next`.
- Approvals returned **403** for `sales_rep`. This is the only non-2xx response seen in the page sweep, and it is expected RBAC.

**Quote builder**
- As `sales_rep`: `POST /quotes` created draft `QT-202611-F0BED0`. Pricing (`PUT …/items`) was refused with 403, because `sales_rep` has `quotes:create` but not `quotes:write`. The UI reports this. The permission matrix was not changed.
- As `sales_manager`: 2 × 1 500,00 MAD was priced by the server to subtotal 3 000,00, VAT 600,00, total **3 600,00 MAD**, margin 40 %, status `PRICED`. Issuing moved it to `ISSUED`.

**Voice**
- A session was created and the WebSocket opened with the signed token. The mandatory AI/recording disclosure was received.
- A typed turn ("Bonjour, quels sont vos horaires ?") returned an agent reply over the stream.
- **Not verified:** microphone capture. The browser pane blocks microphone access. Real capture needs a manual check in a normal browser.

**CSP and layout**
- **CSP:** after the font `@import` was removed, all 29 pages loaded with **no CSP violations** in the console.
- **Layout:** horizontal overflow (`scrollWidth − clientWidth`) at 390 px is **0 px on all 28 app pages**. Before the fixes it was 24–141 px on index, approvals, catalog, procurement, quote_builder, release_console, support, voice_agent and voice_copilot.
- **Screenshots:** `evidence/claude-inspection/screenshots/group_e/`.

**Automated tests**
- `tests/security/test_group_e_regressions.py`: **325 passed**. It checks:
  - no inline scripts, styles, handlers or `javascript:` URLs;
  - no third-party resources;
  - `api_client.js` loads first on every page;
  - shared navigation and the auth guard;
  - no hardcoded tenant, token or identity strings;
  - no client tenant header;
  - template escaping;
  - real voice capture and a single voice script;
  - no client-side quote arithmetic;
  - an unwired page must carry the demo banner;
  - the served CSP header.
- Full suite: **765 passed** (`python -m pytest -q`, 624 s, Python 3.14, Windows; 440 before group E plus the 325 new checks).

## What is still open (not claimed as done)
- **Unwired pages:** 8 pages still show static example content. They are now **labelled** as such, not connected: catalog, checkout, logistics, procurement, quote_view, release_console, schedule, support. Several wired pages also keep labelled demo widgets: dashboard charts, the inbox context panel, and the quote builder AI panel.
- **Microphone capture:** implemented, but not verified end to end (see above).
- **Voice latency:** the 600 ms target is still not met (see report 16: median about 6.9 s).
- **Login method:** login is password + TOTP against the platform's own auth. There is **no OIDC/SSO** yet.
- **Tests (report 11, E.5):** no Playwright E2E, visual regression or axe accessibility suite yet. Verification here was a manual browser sweep plus static tests.
- **Product decision on permissions:** `sales_rep` can create quote drafts but cannot price them (`quotes:write`). Decide whether reps should price their own drafts.
- **Tenant switcher:** it only shows a notice. Switching organisation means signing in again with that organisation's ID.

## Update 2026-11-25 — owner decision
- UI work is **on hold**: the owner will provide the design.
- At the owner's request, the "Données d'exemple" chips and the demonstration-page banner were **removed**. The 8 unwired pages (catalog, checkout, logistics, procurement, quote_view, release_console, schedule, support) and the remaining static widgets still show static content, but are no longer labelled.
- The regression test now asserts that no demo labelling exists (`test_no_demo_labelling`).
