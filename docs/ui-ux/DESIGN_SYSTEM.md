# SALES AI MANAGEMENT — DESIGN SYSTEM SPECIFICATION (V2.0)

## 1. VISION & DESIGN PHILOSOPHY

The **Sales AI Management Platform** UI/UX design system establishes an ultra-premium, authoritative, and responsive visual standard for an enterprise multi-tenant SaaS application. It merges the rigor of European enterprise software with authentic Moroccan commercial context (MAD currency, ICE corporate identifiers, bilingual French/English workflows, Darija voice AI awareness).

### Primary Visual References
This design system is reverse-engineered from and strictly adheres to the visual targets:
- **Reference A (Executive Dashboard)**: Deep forest-green sidebar (`#082C22`), clean canvas (`#F8FAF9`), high-contrast KPI cards with emerald sparklines, 5-stage pipeline funnel (`Prospection` → `Qualification` → `Proposition` → `Négociation` → `Gagné`), monthly revenue line chart with gradient fill, revenue donut breakdown, synchronized quotes & orders tables, interactive AI Commercial Assistant card, and recent activity timeline.
- **Reference B (Omnichannel Inbox)**: 3-column unified communications workspace: filtered conversation threads with channel badges (WhatsApp, Email, Web, Phone), rich timeline with AI intent detection confidence badge (98%), bilingual customer/agent chat bubbles (dark green agent bubble `#0A3A2A`), AI quick response suggestion chips, and comprehensive right-side CRM customer/deal context sidebar with rapid action CTAs.
- **Reference C (Quotations & Orders Workspace)**: High-density commercial offer builder: top KPI row, sub-tabs (`Quotes`, `Orders`, `Approvals`, `Conversion`, `Analytics`), left customer & product catalog selector, central quotation editor with itemized lines, quantity controls, unit prices, discounts, subtotal, 20% TVA calculation, and final total in bold emerald text, plus right-side AI Sales Assistant recommendations and 3-stage visual approval status tracker.

---

## 2. COLOR PALETTE & DESIGN TOKENS

```css
:root {
  /* Brand Foundations */
  --brand-primary: #0A3A2A;          /* Deep Forest Green - Primary actions & dark surfaces */
  --brand-primary-hover: #064E3B;    /* Darker Forest Green on hover */
  --brand-sidebar: #082C22;          /* Deepest Forest Green - Sidebar background */
  --brand-sidebar-hover: #0E3E31;    /* Sidebar item hover background */
  --brand-sidebar-active: #10B981;   /* Active sidebar pill (Emerald Green) */
  --brand-sidebar-text: #E2ECE6;     /* Sidebar text muted */
  --brand-sidebar-text-active: #FFFFFF; /* Sidebar active text */

  /* Vibrant Accent */
  --accent-emerald: #10B981;         /* Emerald Green - Trends, active pills, badges, curves */
  --accent-emerald-light: #EAF7F0;   /* Ultra-soft emerald tint for card highlights & badges */
  --accent-emerald-border: #A7F3D0;  /* Subtle emerald border */

  /* Neutrals & Surfaces */
  --bg-app: #F8FAF9;                 /* Soft warm-gray page canvas */
  --bg-card: #FFFFFF;                /* Pristine white surface */
  --bg-card-hover: #FAFCFB;          /* Subtle hover elevation */
  --bg-input: #FFFFFF;               /* Clean input background */
  --bg-input-focus: #FFFFFF;
  --bg-muted: #F1F5F3;               /* Muted container background */

  /* Borders & Dividers */
  --border-subtle: #E4EBE6;          /* Standard card and table border */
  --border-medium: #CBD7CE;          /* Input border */
  --border-focus: #10B981;           /* Input focus border */

  /* Typography / Text Colors */
  --text-primary: #17251F;           /* High contrast slate-green-black (> 12:1 WCAG AAA) */
  --text-secondary: #66756D;         /* Secondary descriptive labels (> 5.5:1 WCAG AA) */
  --text-tertiary: #94A39B;          /* Tertiary / placeholder text */
  --text-white: #FFFFFF;             /* Pure white for dark containers */

  /* Semantic Status Colors */
  --status-success: #16A34A;         /* Approved / Confirmed / Paid */
  --status-success-bg: #DCFCE7;
  --status-warning: #D97706;         /* Pending / In Review / Due Soon */
  --status-warning-bg: #FEF3C7;
  --status-info: #2563EB;            /* Processing / Email / Note */
  --status-info-bg: #EFF6FF;
  --status-danger: #DC2626;          /* Rejected / Overdue / High Risk */
  --status-danger-bg: #FEE2E2;
  --status-purple: #7C3AED;          /* Dispatched / Shipped */
  --status-purple-bg: #F3E8FF;

  /* Elevation Shadows */
  --shadow-xs: 0 1px 2px rgba(10, 58, 42, 0.03);
  --shadow-sm: 0 1px 3px rgba(10, 58, 42, 0.05), 0 1px 2px rgba(10, 58, 42, 0.02);
  --shadow-md: 0 4px 6px -1px rgba(10, 58, 42, 0.06), 0 2px 4px -1px rgba(10, 58, 42, 0.03);
  --shadow-lg: 0 10px 15px -3px rgba(10, 58, 42, 0.08), 0 4px 6px -2px rgba(10, 58, 42, 0.04);

  /* Radius Tokens */
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-full: 9999px;
}
```

---

## 3. TYPOGRAPHY SCALE & FONT SYSTEM

The font stack uses **Inter**, with fallbacks to system fonts:
`font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;`

| Element | Size | Weight | Tracking | Color | Usage |
|---|---|---|---|---|---|
| **Display Title** | 24px (1.5rem) | 700 Bold | -0.02em | `--text-primary` | Main page greeting (`Bonjour Omar 👋`) & view titles |
| **Section Title** | 18px (1.125rem) | 600 Semi-Bold | -0.01em | `--text-primary` | Card group titles (`Pipeline commercial`, `Évolution du CA`) |
| **Card Header** | 15px (0.9375rem) | 600 Semi-Bold | 0.00em | `--text-primary` | Sub-card headers (`Select Customer`, `Build Quotation`) |
| **KPI Metric** | 24px–28px | 700 Bold | -0.02em | `--text-primary` | Key numeric metrics (`2 184 350,00 MAD`, `428`) |
| **KPI Subtext** | 12px (0.75rem) | 500 Medium | 0.00em | `--text-secondary` | Trend indicator (`+14,8% vs. mois précédent`) |
| **Body Primary** | 13px–14px | 500 Medium | 0.00em | `--text-primary` | Table row values, chat messages, input values |
| **Body Secondary** | 12px–13px | 400 Regular | 0.00em | `--text-secondary` | Descriptive subtitles, metadata, timestamps |
| **Badge / Tag** | 11px–12px | 600 Semi-Bold | 0.01em | Semantic | Status chips (`Approuvé`, `En validation`, `Draft`) |
| **Table Header** | 11px–12px | 600 Semi-Bold | 0.02em | `--text-secondary` | Column headers (`Référence`, `Client`, `Montant (MAD)`) |

---

## 4. MASTER APPLICATION SHELL

Every screen in the Sales AI Management Platform is rendered inside a **single unified application shell**:

### Left Sidebar (`width: 250px`, Fixed)
- **Brand Header**:
  - Logo icon: 3-bar stylized emerald chart icon.
  - Brand name: **Sales AI** (bold white) / **Management** (regular white).
- **Navigation Groups**:
  - `Tableau de bord` (Dashboard) — Home icon
  - `CRM` — User-check icon (expandable / sub-items)
  - `Ventes` (Sales Pipeline) — Trend-up icon
  - `Catalogue` (Products & Pricing) — Box icon
  - `Devis & Approbations` (Quotations & Approvals) — File-text icon
  - `Commandes` (Orders & Invoices) — Shopping cart icon
  - `Achats` (Procurement) — Bag icon
  - `Stock` (Inventory & Warehouses) — Building icon
  - `Finance` (Payments & Invoices) — Credit card / ledger icon
  - `Omnicanal` (Inbox & Channels) — Message bubble icon (with dynamic badge)
  - `IA & Automatisation` (Agent Ecosystem & Workflows) — Sparkle bot icon
  - `Rapports` (Analytics & Observability) — Bar chart icon
  - `Paramètres` (SaaS Admin, Quotas & Audit) — Sliders/gear icon
- **Bottom Sidebar Elements**:
  - **AI Status Pill**: Dark card with emerald sparkles:
    `IA Active — 4 agents opérationnels >` or `Assistant IA — Actif (Aide à la qualification, réponse et conversion)`.
  - **User Profile Pill**: Avatar circle (`OA` / `OS`), Name (`Omar A.` / `Omar Soubaibi`), Role (`Administrateur`), with switch/logout dropdown.

### Top Header Bar (`height: 64px`, Sticky)
- **Universal Search**: Input with magnifying glass `Rechercher un client, une opportunité, un devis...` + keyboard shortcut chip `Ctrl + K`.
- **Tenant Context Dropdown**: Building icon + Tenant name (e.g. `Atlas Commerce`, `tenant-acme-corp`) with chevron.
- **Date Range Filter**: Calendar icon + Date label (e.g. `01 nov. 2026 - 30 nov. 2026` / `01 Jan 2026 - 31 Dec 2026`) with dropdown chevron.
- **Notification Bell**: Notification bell icon with red unread counter badge (`12` or `3`).
- **Primary Header Action**: High-contrast Forest Green button: `+ Nouveau` or `+ New Quote`.
- **User Avatar Pill**: Emerald/Dark green circle with initials (`OA` / `OS`).

---

## 5. WORKSPACE COMPONENT SPECIFICATIONS

### A. Executive Dashboard Components
1. **Top KPI Metric Cards**:
   - Icon in soft-green circular or rounded square container.
   - Large bold value (MAD currency formatted with space separators).
   - Trend pill: Green up-arrow with percentage change (`+14,8% vs. mois précédent`).
   - SVG vector sparkline curve illustrating 30-day positive upward momentum.
2. **5-Stage Pipeline Funnel**:
   - Stages: `Prospection` → `Qualification` → `Proposition` → `Négociation` → `Gagné`.
   - Each card displays Stage icon, Stage title, Count of deals (bold 20px), and Total value in MAD.
   - Visual chevron `>` dividers between stages.
   - The final stage `Gagné` is highlighted with a rich Deep Forest Green background (`#0A3A2A`), white text, and golden trophy icon.
3. **Charts & Visualizations**:
   - **Revenue Evolution**: Monthly line/area chart with smooth spline interpolation, green stroke (`#10B981`), semi-transparent green gradient fill, interactive tooltips, and timeframe selector (`Mensuel`, `Trimestriel`, `Annuel`).
   - **Revenue Breakdown**: CSS/SVG donut chart showing revenue split by category (`Produits (42%)`, `Services (28%)`, `Maintenance (18%)`, `Formation (7%)`, `Autres (5%)`) with centered grand total.
4. **AI Commercial Assistant Widget**:
   - Header with sparkle icon and pulsating live status dot `En ligne`.
   - Conversational insight query container.
   - 3 actionable bullet items with checkmarks and direct monetary potential.
   - Full-width Dark Forest Green CTA button: `Lancer une action IA` with settings shortcut.
5. **Recent Quotes & Orders Dual Tables**:
   - Side-by-side data tables with reference, customer, formatted amount (MAD), status badges, and action triggers.
6. **Live Activity Stream**:
   - Event timeline with semantic action icons (Quote approved, Order created, Customer onboarded, Catalog updated, AI analysis complete) with relative timestamps.

### B. Omnichannel Inbox Components
1. **Left Thread List**:
   - Channel filters: `Toutes (42)`, `Non lues (8)`, `Mes conversations`, search & filter.
   - Thread item: Customer avatar initials, customer name, channel icon (WhatsApp, Email, Web, SMS), snippet text, timestamp, unread counter badge, and stage tag chips.
2. **Central Conversation Stream**:
   - Header with customer name, live online indicator, channel badge, tags, and quick call/video/actions.
   - AI Intent Detection Banner: Emerald badge card displaying `Analyse IA - Demande détectée`, confidence percentage (`Confiance : 98%`), and extracted entities (Intent, Product SKU, Quantity).
   - Inbound bubbles: White background, subtle border, left-aligned, timestamped.
   - Outbound bubbles: Rich deep forest green background (`#0A3A2A`), white text, right-aligned, delivered/read double-check ticks (`✓✓`).
   - AI Quick Suggestion Bar: Sparkle header with refresh trigger and 3 clickable suggestion cards that immediately populate the composer.
   - Rich Composer: Multi-line text area with paperclip attachment, emoji picker, document inserter, and circular paper-plane send button.
3. **Right Context Sidebar**:
   - Tabs: `Client & Deal`, `Historique`, `Fichiers`.
   - Full customer card: ICE, phone, email, address, company classification.
   - Active deal summary: Target object, estimated value in MAD, stage selector, win probability progress bar, due date, assigned sales rep.
   - Fast Action CTAs: `Créer un devis`, `Convertir en opportunité`, `Planifier un appel`, `Ajouter une tâche`.

### C. Quotations & Commercial Builder Components
1. **Top Metric Row**:
   - `Total Quotes`, `Approved` (with approval rate % badge), `Pending Approval`, `Orders Created`, `Quote Value (MAD)`.
2. **Sub-Navigation Tabs**:
   - `Quotes`, `Orders`, `Approvals`, `Conversion`, `Analytics`.
3. **3-Column Commercial Editor**:
   - **Column 1: Customer & Catalog Selection**:
     - Customer list with search, category tags, city, and active radio selector.
     - Product catalog table with SKU, thumbnail, description, price, and current stock level.
   - **Column 2: Quotation Builder**:
     - Quote reference (`Q-2026-0158`), status badge dropdown (`Draft`).
     - Selected customer overview banner with ICE and contact details.
     - Terms controls: Quote type, validity period, currency (`MAD`), payment terms.
     - Line items table: Product description, Quantity input, Unit Price (MAD), Discount %, Row Total (MAD), and deletion action.
     - Summary box: Subtotal, Total Discount, 20% Moroccan TVA, Total TTC in prominent bold green.
     - Commercial actions: `Save Draft`, `Recalculate`, `Send for Approval`, and `Create Order`.
   - **Column 3: AI Assistant & Approval Workflow**:
     - AI Sales Assistant with tabs `Recommendations` & `Insights` (discount suggestions, cross-sell opportunities, optimized payment terms).
     - 3-stage visual approval workflow tracker: Creator info, Commercial Manager approval (`In Progress`), and Sales Director threshold check (`≥ 150,000 MAD`).

---

## 6. RESPONSIVE BREAKPOINT BEHAVIOR

| Breakpoint | Width | Navigation | Layout Adaptation |
|---|---|---|---|
| **Large Desktop** | ≥ 1440px | Full sidebar (250px) | 3 or 4 columns (100% fidelity to reference screenshots) |
| **Standard Laptop** | 1024px – 1439px | Compact sidebar (220px) | 3 columns with proportional flex-shrink |
| **Tablet** | 768px – 1023px | Collapsible drawer / icon rail | 2 columns; right context sidebar slides out as overlay |
| **Mobile** | < 768px | Top bar + bottom tab bar / drawer | Single stacked column; cards stack vertically; tables scroll horizontally |

---

## 7. "ANTI-CLICHÉ" RULES & QUALITY STANDARDS

In accordance with `premium-design-loop`:
1. **No Purple-on-Dark or Neon Gradients**: The color story is rooted in organic, sophisticated deep Moroccan forest green (`#0A3A2A`, `#082C22`) and fresh emerald (`#10B981`).
2. **No Particle Meshes or Fake 3D Wireframes**: Background is a clean, subtle warm-gray canvas (`#F8FAF9`).
3. **No Decorative Fluff**: Every visual element serves a clear workflow purpose: status, financial figure, channel, or AI recommendation.
4. **Authentic Enterprise Content**: Realistic Moroccan business details (Casablanca, Rabat, ICE numbers, MAD currency, standard 20% TVA).
5. **High Typography Contrast**: Strict WCAG AAA compliance on all body text and KPI values.
