/**
 * SELIA — application shell (design delivered by the product owner, 2026-11-25).
 * Renders, on every authenticated page:
 *   - the sidebar (logo, main navigation, "Plus de modules", Assistant IA card, user card);
 *   - the topbar (search, notifications, account menu);
 *   - on phones: the bottom bar (Accueil, Clients, +, Analyses, Profil) and the
 *     "Créer rapidement" sheet.
 * Identity comes from the authenticated session (F-20) - never hardcoded. No inline
 * handlers or styles (strict CSP); all text is escaped.
 */
(function () {
  'use strict';

  const sessionUser = (window.SalesApi && window.SalesApi.user()) || null;
  const ROLE_LABELS = {
    super_admin: 'Super administrateur', tenant_admin: 'Administrateur', sales_manager: 'Responsable commercial',
    sales_rep: 'Commercial', sales_representative: 'Commercial', inventory_manager: 'Gestionnaire stock',
    support_agent: 'Agent support', customer: 'Client'
  };
  const fullName = sessionUser ? (sessionUser.fullName || sessionUser.email || '') : '';
  const words = fullName.split(/[\s@.]+/).filter(Boolean);
  const AppState = {
    tenantId: sessionUser ? sessionUser.tenantId : '',
    currentUser: {
      name: fullName,
      firstName: words[0] || '',
      shortName: words.length > 1 ? words[0] + ' ' + words[1][0].toUpperCase() + '.' : (words[0] || ''),
      initials: words.slice(0, 2).map(w => w[0].toUpperCase()).join(''),
      email: sessionUser ? sessionUser.email : '',
      role: sessionUser ? (ROLE_LABELS[(sessionUser.roles || [])[0]] || (sessionUser.roles || [])[0] || '') : ''
    }
  };

  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ICON = (d, size) => '<svg width="' + (size || 18) + '" height="' + (size || 18) + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
  const I = {
    home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.4 3.3-5.5 6.5-5.5s5.9 2.1 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.8c1.9.7 3.2 2.5 3.5 5.2"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12l7-7M16 5h3v3"/>',
    doc: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    cart: '<circle cx="9" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/><path d="M2 3h3l2.4 11.2a2 2 0 0 0 2 1.6h8.2a2 2 0 0 0 2-1.5L21 7H6"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2.5"/><path d="M8 3v4M16 3v4M3 10h18"/>',
    chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.6A8 8 0 1 1 21 12z"/>',
    chart: '<path d="M6 20V12M12 20V6M18 20v-9"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>',
    bell: '<path d="M18 9a6 6 0 0 0-12 0c0 7-3 8.5-3 8.5h18S18 16 18 9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    chevron: '<path d="m6 9 6 6 6-6"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c.8-4 4-6 8-6s7.2 2 8 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    userPlus: '<circle cx="9" cy="8" r="4"/><path d="M2 21c.7-4 3.6-6 7-6 1.6 0 3 .4 4.2 1.2M19 14v6M16 17h6"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4"/>'
  };

  // Main navigation (design) + the platform's other modules, folded under "Plus".
  const MAIN_NAV = [
    ['index.html', 'Tableau de bord', I.home],
    ['clients.html', 'Clients', I.users],
    ['pipeline.html', 'Opportunités', I.target],
    ['quotes.html', 'Devis', I.doc],
    ['orders.html', 'Commandes', I.cart],
    ['schedule.html', 'Rendez-vous', I.calendar],
    ['inbox.html', 'Conversations', I.chat],
    ['analytics_dashboard.html', 'Analyses', I.chart]
  ];
  const MORE_NAV = [
    ['invoices.html', 'Factures'], ['catalog.html', 'Catalogue produits'], ['approvals.html', 'Approbations'],
    ['checkout.html', 'Paiements'], ['inventory.html', 'Stock & entrepôts'], ['procurement.html', 'Achats & fournisseurs'],
    ['logistics.html', 'Logistique'], ['support.html', 'Support & SAV'], ['agent_workspace.html', 'Espace agents IA'],
    ['voice_agent.html', 'Agent vocal client'], ['voice_copilot.html', 'Copilote vocal'], ['ai_governance.html', 'Gouvernance IA'],
    ['ai_operations_dashboard.html', 'Opérations IA'], ['voice_observability.html', 'Observabilité vocale'],
    ['workflows.html', 'Workflows'], ['workflow_reliability_dashboard.html', 'Fiabilité & alertes'],
    ['notifications.html', 'Notifications'], ['integrations.html', 'Intégrations'],
    ['saas_admin_dashboard.html', 'Abonnement & quotas'], ['release_console.html', 'État de la plateforme']
  ];
  // Pages that belong to a main entry for highlighting purposes.
  const ALIASES = { 'quote_builder.html': 'quotes.html', 'quote_view.html': 'quotes.html' };

  const QUICK_CREATE = [
    ['clients.html#nouveau', 'Client', I.userPlus],
    ['pipeline.html#nouveau', 'Opportunité', I.target],
    ['quote_builder.html', 'Devis', I.doc],
    ['orders.html', 'Commande', I.cart],
    ['schedule.html#nouveau', 'Rendez-vous', I.calendar],
    ['agent_workspace.html', 'Assistant IA', I.sparkle]
  ];

  const currentPage = () => {
    const p = window.location.pathname.split('/').pop() || 'index.html';
    return ALIASES[p] || p;
  };

  function logoMarkup(size) {
    const s = size || 30;
    return '<span class="selia-logo"><svg width="' + s + '" height="' + s + '" viewBox="0 0 32 32" aria-hidden="true">' +
      '<path d="M25 9.5C22.5 6 17.5 5 13 6.2 8.8 7.3 7.3 10.6 9 13c1.4 2 4.6 2.6 8 3" fill="none" stroke="#D0673A" stroke-width="5.2" stroke-linecap="round"/>' +
      '<path d="M15 16c3.4.4 7 1.6 7.6 4.4.6 2.9-2.8 5.4-8 5.6-3.6.2-6.6-.8-8.2-2.4" fill="none" stroke="#5F7A2E" stroke-width="5.2" stroke-linecap="round"/>' +
      '<path d="M13.2 15.4c1-.2 1.4-.2 1.8.6" fill="none" stroke="#EBC9A8" stroke-width="2.4" stroke-linecap="round"/>' +
      '</svg><span class="selia-wordmark">Selia</span></span>';
  }

  function renderNav() {
    const host = document.querySelector('[data-app-nav]');
    if (!host) return;
    const cur = currentPage();
    const link = ([href, label, icon]) => {
      const active = href === cur;
      return '<li><a href="' + href + '" class="nav-item' + (active ? ' active' : '') + '"' + (active ? ' aria-current="page"' : '') +
        '><span class="icon">' + ICON(icon || I.grid) + '</span><span class="label">' + esc(label) + '</span></a></li>';
    };
    const moreOpen = MORE_NAV.some(([h]) => h === cur);
    host.innerHTML =
      '<a class="brand-header" href="index.html" aria-label="Selia — accueil">' + logoMarkup(30) + '</a>' +
      '<nav class="selia-nav" aria-label="Navigation principale"><ul class="nav-list">' + MAIN_NAV.map(link).join('') + '</ul>' +
      '<details class="nav-more"' + (moreOpen ? ' open' : '') + '><summary class="nav-item"><span class="icon">' + ICON(I.grid) +
      '</span><span class="label">Plus de modules</span><span class="nav-more-chevron">' + ICON(I.chevron, 14) + '</span></summary>' +
      '<ul class="nav-list nav-list--sub">' + MORE_NAV.map(([h, l]) => link([h, l, null])).join('') + '</ul></details>' +
      '<div class="nav-divider"></div><ul class="nav-list">' + link(['profile.html', 'Paramètres', I.settings]) + '</ul></nav>' +
      '<div class="sidebar-footer">' +
        '<div class="ai-promo"><span class="ai-promo-icon">' + ICON(I.sparkle, 20) + '</span><strong>Assistant IA</strong>' +
        '<p>Gagnez du temps sur vos tâches commerciales.</p><a class="btn btn-primary btn-sm" href="agent_workspace.html">Essayer ' + ICON(I.arrow, 14) + '</a></div>' +
        '<div class="user-profile-card"><span class="user-avatar">' + esc(AppState.currentUser.initials) + '</span>' +
        '<span class="user-details"><span class="name">' + esc(AppState.currentUser.name) + '</span><span class="role">' + esc(AppState.currentUser.role) + '</span></span>' +
        '<button type="button" class="btn-logout" data-shell-logout aria-label="Se déconnecter" title="Se déconnecter">' + ICON(I.logout, 16) + '</button></div>' +
      '</div>';
  }

  function renderTopbar() {
    const bar = document.querySelector('header.topbar');
    if (!bar) return;
    bar.innerHTML =
      '<button type="button" class="mobile-menu-btn" id="mobileMenuToggle" aria-label="Ouvrir le menu">' + ICON('<path d="M4 6h16M4 12h16M4 18h16"/>', 20) + '</button>' +
      '<a class="topbar-brand" href="index.html" aria-label="Selia — accueil">' + logoMarkup(26) + '</a>' +
      '<form class="search-container" role="search" data-shell-search><span class="search-icon">' + ICON(I.search, 17) + '</span>' +
      '<input type="search" class="search-input" id="globalSearchInput" placeholder="Rechercher un client, une opportunité, un devis…" aria-label="Rechercher"></form>' +
      '<div class="topbar-actions">' +
        '<button type="button" class="icon-btn" id="notifBtn" aria-label="Notifications" aria-haspopup="true">' + ICON(I.bell, 19) + '<span class="notif-dot" hidden></span></button>' +
        '<button type="button" class="user-topbar-pill" id="accountBtn" aria-haspopup="true" aria-expanded="false"><span class="user-avatar">' + esc(AppState.currentUser.initials) +
        '</span><span class="user-short">' + esc(AppState.currentUser.shortName) + '</span>' + ICON(I.chevron, 15) + '</button>' +
      '</div>';
  }

  function renderMobileChrome() {
    if (!document.querySelector('.app-container') || document.querySelector('.bottom-nav')) return;
    const cur = currentPage();
    const tab = (href, label, icon) => '<a href="' + href + '" class="bottom-nav-item' + (href === cur ? ' active' : '') + '"' +
      (href === cur ? ' aria-current="page"' : '') + '>' + ICON(icon, 22) + '<span>' + esc(label) + '</span></a>';
    const nav = document.createElement('nav');
    nav.className = 'bottom-nav';
    nav.setAttribute('aria-label', 'Navigation mobile');
    nav.innerHTML = tab('index.html', 'Accueil', I.home) + tab('clients.html', 'Clients', I.users) +
      '<button type="button" class="fab" id="fabCreate" aria-label="Créer rapidement" aria-haspopup="dialog">' + ICON(I.plus, 26) + '</button>' +
      tab('analytics_dashboard.html', 'Analyses', I.chart) + tab('profile.html', 'Profil', I.user);
    document.body.appendChild(nav);

    const sheet = document.createElement('div');
    sheet.className = 'sheet-backdrop';
    sheet.hidden = true;
    sheet.innerHTML = '<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sheetTitle"><span class="sheet-handle"></span>' +
      '<h2 id="sheetTitle">Créer rapidement</h2><div class="sheet-grid">' +
      QUICK_CREATE.map(([href, label, icon]) => '<a href="' + href + '" class="sheet-action"><span class="sheet-icon">' + ICON(icon, 24) + '</span>' + esc(label) + '</a>').join('') +
      '</div></div>';
    document.body.appendChild(sheet);
    const open = () => { sheet.hidden = false; document.body.classList.add('sheet-open'); sheet.querySelector('.sheet-action').focus(); };
    const close = () => { sheet.hidden = true; document.body.classList.remove('sheet-open'); };
    document.getElementById('fabCreate').addEventListener('click', open);
    sheet.addEventListener('click', (e) => { if (e.target === sheet) close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !sheet.hidden) close(); });
  }

  function popover(anchor, id, buildHtml) {
    let panel = document.getElementById(id);
    const isOpen = panel && !panel.hidden;
    document.querySelectorAll('.shell-popover').forEach(p => { p.hidden = true; });
    if (isOpen) return null;
    if (!panel) {
      panel = document.createElement('div');
      panel.id = id;
      panel.className = 'shell-popover';
      document.body.appendChild(panel);
    }
    panel.innerHTML = buildHtml();
    const r = anchor.getBoundingClientRect();
    panel.style.top = (r.bottom + window.scrollY + 8) + 'px';
    panel.style.right = Math.max(12, document.documentElement.clientWidth - r.right) + 'px';
    panel.hidden = false;
    return panel;
  }

  function setupMenus() {
    const notifBtn = document.getElementById('notifBtn');
    if (notifBtn) {
      notifBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const panel = popover(notifBtn, 'notifPanel', () =>
          '<div class="popover-head"><strong>Notifications</strong></div><div class="popover-body" data-notif-body><p class="popover-empty">Chargement…</p></div>');
        if (!panel || !window.SalesViews) return;
        const res = await window.SalesViews.getJson('/api/v1/notifications/history?limit=8');
        const body = panel.querySelector('[data-notif-body]');
        const items = res.ok ? (Array.isArray(res.data) ? res.data : (res.data && res.data.items) || []) : [];
        body.innerHTML = items.length
          ? items.slice(0, 8).map(n => '<div class="popover-item"><strong>' + esc(n.subject || n.template_key || n.channel || 'Notification') +
            '</strong><span>' + esc(window.SalesViews.date(n.created_at || n.sent_at)) + '</span></div>').join('')
          : '<p class="popover-empty">' + (res.ok ? 'Aucune notification.' : 'Notifications indisponibles.') + '</p>';
      });
    }
    const accountBtn = document.getElementById('accountBtn');
    if (accountBtn) {
      accountBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const panel = popover(accountBtn, 'accountPanel', () =>
          '<div class="popover-head"><strong>' + esc(AppState.currentUser.name) + '</strong><span>' + esc(AppState.currentUser.email) + '</span></div>' +
          '<a class="popover-link" href="profile.html">' + ICON(I.user, 16) + 'Mon profil</a>' +
          '<a class="popover-link" href="profile.html#securite">' + ICON(I.settings, 16) + 'Paramètres</a>' +
          '<button type="button" class="popover-link popover-link--danger" data-shell-logout>' + ICON(I.logout, 16) + 'Se déconnecter</button>');
        accountBtn.setAttribute('aria-expanded', panel ? 'true' : 'false');
      });
    }
    document.addEventListener('click', (e) => {
      if (e.target.closest('[data-shell-logout]')) { window.SalesApi && window.SalesApi.logout(); return; }
      if (!e.target.closest('.shell-popover')) document.querySelectorAll('.shell-popover').forEach(p => { p.hidden = true; });
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') document.querySelectorAll('.shell-popover').forEach(p => { p.hidden = true; });
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        const s = document.getElementById('globalSearchInput');
        if (s) { e.preventDefault(); s.focus(); }
      }
    });
    const search = document.querySelector('[data-shell-search]');
    if (search) {
      search.addEventListener('submit', (e) => {
        e.preventDefault();
        const q = document.getElementById('globalSearchInput').value.trim();
        if (q) window.location.href = 'clients.html?q=' + encodeURIComponent(q);
      });
    }
  }

  function setupMobileSidebar() {
    const toggle = document.getElementById('mobileMenuToggle');
    const sidebar = document.querySelector('.sidebar');
    if (!toggle || !sidebar) return;
    toggle.addEventListener('click', (e) => { e.stopPropagation(); sidebar.classList.toggle('mobile-open'); });
    document.addEventListener('click', (e) => {
      if (sidebar.classList.contains('mobile-open') && !sidebar.contains(e.target)) sidebar.classList.remove('mobile-open');
    });
  }

  function renderIdentity() {
    const greeting = document.getElementById('greetingTitle');
    if (greeting) greeting.textContent = AppState.currentUser.firstName ? 'Bonjour ' + AppState.currentUser.firstName : 'Bonjour';
  }

  // Declarative icons (<button data-icon="plus">) and modal dismissal for every page.
  function setupDeclarativeUi() {
    document.querySelectorAll('[data-icon]').forEach(el => {
      if (el.querySelector('svg')) return;
      el.insertAdjacentHTML('afterbegin', ICON(I[el.getAttribute('data-icon')] || I.plus, 16));
    });
    document.addEventListener('click', (e) => {
      const closer = e.target.closest('[data-close-modal]');
      if (closer) { closer.closest('.modal-backdrop').hidden = true; return; }
      if (e.target.classList && e.target.classList.contains('modal-backdrop')) e.target.hidden = true;
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') document.querySelectorAll('.modal-backdrop').forEach(m => { m.hidden = true; });
    });
  }

  function showToast(message) {
    let toast = document.getElementById('salesAiToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'salesAiToast';
      toast.className = 'toast';
      toast.setAttribute('role', 'status');
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('toast--visible');
    clearTimeout(showToast.t);
    showToast.t = setTimeout(() => toast.classList.remove('toast--visible'), 3200);
  }

  document.addEventListener('DOMContentLoaded', () => {
    renderNav();
    renderTopbar();
    renderMobileChrome();
    renderIdentity();
    setupMenus();
    setupMobileSidebar();
    setupDeclarativeUi();
  });

  window.SalesAI = { state: AppState, showToast: showToast, openModal: (id) => { const m = document.getElementById(id); if (m) { m.hidden = false; const f = m.querySelector('input,select,textarea,button'); if (f) f.focus(); } }, icon: (name, size) => ICON(I[name] || I.grid, size), logo: logoMarkup };
})();
