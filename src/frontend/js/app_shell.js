/**
 * SALES AI MANAGEMENT PLATFORM — APP SHELL CONTROLLER (V2.0)
 * Handles global navigation, tenant switching, search shortcuts, responsive drawer,
 * notification panel, and unified state across all 28 views.
 */

(function () {
  'use strict';

  // 1. Identity comes from the authenticated session (F-20) - never hardcoded.
  const sessionUser = (window.SalesApi && window.SalesApi.user()) || null;
  const ROLE_LABELS = {
    super_admin: 'Super administrateur', tenant_admin: 'Administrateur', sales_manager: 'Responsable commercial',
    sales_rep: 'Commercial', sales_representative: 'Commercial', inventory_manager: 'Gestionnaire stock',
    support_agent: 'Agent support', customer: 'Client'
  };
  const AppState = {
    tenantId: sessionUser ? sessionUser.tenantId : '',
    currentUser: {
      name: sessionUser ? (sessionUser.fullName || sessionUser.email || '') : '',
      initials: sessionUser ? (sessionUser.fullName || sessionUser.email || '?').split(/[\s@.]+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') : '',
      email: sessionUser ? sessionUser.email : '',
      role: sessionUser ? (ROLE_LABELS[(sessionUser.roles || [])[0]] || (sessionUser.roles || [])[0] || '') : ''
    }
  };

  // Single navigation definition for every page (replaces 6 inconsistent sidebars).
  const ICON = (d) => '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' + d + '</svg>';
  const NAV = [
    { title: 'Pilotage', items: [
      ['index.html', 'Tableau de bord', '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'],
      ['analytics_dashboard.html', 'Analytique', '<path d="M18 20V10M12 20V4M6 20v-6"/>']
    ]},
    { title: 'Ventes', items: [
      ['pipeline.html', 'CRM & Pipeline', '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/>'],
      ['inbox.html', 'Boîte de réception', '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'],
      ['catalog.html', 'Catalogue', '<path d="M21 16V8l-9-5-9 5v8l9 5 9-5z"/>'],
      ['quote_builder.html', 'Devis', '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>'],
      ['approvals.html', 'Approbations', '<polyline points="20 6 9 17 4 12"/>'],
      ['orders.html', 'Commandes', '<circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6"/>'],
      ['checkout.html', 'Paiements', '<rect x="1" y="4" width="22" height="16" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/>'],
      ['invoices.html', 'Factures', '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>']
    ]},
    { title: 'Opérations', items: [
      ['inventory.html', 'Stock & entrepôts', '<rect x="3" y="3" width="18" height="18" rx="2"/>'],
      ['procurement.html', 'Achats & fournisseurs', '<path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/>'],
      ['logistics.html', 'Logistique', '<rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/>'],
      ['support.html', 'Support & SAV', '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/>'],
      ['schedule.html', 'Rendez-vous', '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/>']
    ]},
    { title: 'IA & voix', items: [
      ['agent_workspace.html', 'Espace agents IA', '<polygon points="12 2 15 9 22 9 16.5 13.5 18.5 21 12 16.5 5.5 21 7.5 13.5 2 9 9 9 12 2"/>'],
      ['voice_agent.html', 'Agent vocal client', '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/>'],
      ['voice_copilot.html', 'Copilote vocal manager', '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>'],
      ['ai_governance.html', 'Gouvernance IA', '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'],
      ['ai_operations_dashboard.html', 'Opérations IA', '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>'],
      ['voice_observability.html', 'Observabilité vocale', '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>']
    ]},
    { title: 'Automatisation', items: [
      ['workflows.html', 'Workflows', '<polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/>'],
      ['workflow_reliability_dashboard.html', 'Fiabilité & DLQ', '<path d="M22 11.1V12a10 10 0 1 1-5.9-9.1"/>'],
      ['notifications.html', 'Notifications', '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>'],
      ['integrations.html', 'Intégrations', '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/>']
    ]},
    { title: 'Administration', items: [
      ['saas_admin_dashboard.html', 'Abonnement & quotas', '<circle cx="12" cy="12" r="3"/>'],
      ['release_console.html', 'Console de release', '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>']
    ]}
  ];

  function escapeHtml(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function renderNav() {
    const host = document.querySelector('[data-app-nav]');
    if (!host) return;
    const current = window.location.pathname.split('/').pop() || 'index.html';
    let html = '<div class="brand-header"><div class="brand-logo-icon">' + ICON('<path d="M18 20V10M12 20V4M6 20v-6"/>') +
      '</div><div class="brand-text"><span class="title">Sales AI</span><span class="subtitle">Management</span></div></div>';
    NAV.forEach(group => {
      html += '<div class="nav-group"><div class="nav-group-title">' + escapeHtml(group.title) + '</div><ul class="nav-list">';
      group.items.forEach(([href, label, icon]) => {
        const active = href === current ? ' active' : '';
        html += '<li><a href="' + href + '" class="nav-item' + active + '"' + (active ? ' aria-current="page"' : '') +
          '><span class="icon">' + ICON(icon) + '</span><span class="label">' + escapeHtml(label) + '</span></a></li>';
      });
      html += '</ul></div>';
    });
    html += '<div class="sidebar-footer"><div class="user-profile-card"><div class="user-avatar">' + escapeHtml(AppState.currentUser.initials) +
      '</div><div class="user-details"><span class="name">' + escapeHtml(AppState.currentUser.name) + '</span><span class="role">' +
      escapeHtml(AppState.currentUser.role) + '</span></div><button type="button" class="btn-logout" id="btnLogout" aria-label="Se déconnecter" title="Se déconnecter">' +
      ICON('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>') + '</button></div></div>';
    host.innerHTML = html;
    const logout = document.getElementById('btnLogout');
    if (logout) logout.addEventListener('click', () => window.SalesApi && window.SalesApi.logout());
  }

  function renderIdentity() {
    document.querySelectorAll('.user-topbar-pill').forEach(pill => {
      const avatar = pill.querySelector('.user-avatar');
      const spans = pill.querySelectorAll('span');
      if (avatar) avatar.textContent = AppState.currentUser.initials;
      if (spans[0]) spans[0].textContent = AppState.currentUser.name;
      if (spans[1]) spans[1].textContent = AppState.currentUser.role;
    });
    const tenantLabel = document.getElementById('currentTenantLabel');
    if (tenantLabel) tenantLabel.textContent = AppState.tenantId || '';
    const greeting = document.getElementById('greetingTitle');
    if (greeting) {
      const first = String(AppState.currentUser.name || '').split(/\s+/)[0];
      greeting.textContent = first ? 'Bonjour ' + first : 'Bonjour';
    }
  }

  // 2. Setup DOM Listeners once loaded
  document.addEventListener('DOMContentLoaded', () => {
    renderNav();
    renderIdentity();
    highlightActiveNavLink();
    setupGlobalKeyboardShortcuts();
    setupTenantSelector();
    setupMobileSidebar();
    setupNotificationDropdown();
    setupNewActionModal();
  });

  // Highlight the current page in the sidebar
  function highlightActiveNavLink() {
    const currentPath = window.location.pathname.split('/').pop() || 'index.html';
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
      const href = item.getAttribute('href');
      if (href && (href === currentPath || (currentPath === '' && href === 'index.html'))) {
        item.classList.add('active');
      } else if (href && href !== currentPath) {
        item.classList.remove('active');
      }
    });
  }

  // Ctrl + K Global Hotkey for Search
  function setupGlobalKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const searchInput = document.getElementById('globalSearchInput') || document.querySelector('.search-input');
        if (searchInput) {
          searchInput.focus();
          searchInput.select();
        }
      }
      if (e.key === 'Escape') {
        closeAllModals();
      }
    });
  }

  // Tenant context is fixed by the verified session; switching requires a new login
  // (the former selector cycled through invented company names locally).
  function setupTenantSelector() {
    const selectorPill = document.getElementById('tenantSelectorPill');
    if (!selectorPill) return;
    selectorPill.setAttribute('title', 'Tenant de la session authentifiée');
    selectorPill.addEventListener('click', () => showToast('Tenant actif : ' + (AppState.tenantId || '—') + '. Changer de tenant nécessite une nouvelle connexion.'));
  }

  // Responsive Mobile Sidebar Toggle
  function setupMobileSidebar() {
    const toggleBtn = document.getElementById('mobileMenuToggle');
    const sidebar = document.querySelector('.sidebar');
    if (toggleBtn && sidebar) {
      toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        sidebar.classList.toggle('open');
      });

      document.addEventListener('click', (e) => {
        if (!sidebar.contains(e.target) && !toggleBtn.contains(e.target)) {
          sidebar.classList.remove('open');
        }
      });
    }
  }

  // Notification Panel Dropdown
  function setupNotificationDropdown() {
    const notifBtn = document.getElementById('notifBtn');
    if (!notifBtn) return;

    notifBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      let panel = document.getElementById('notifPanel');
      if (!panel) {
        panel = document.createElement('div');
        panel.id = 'notifPanel';
        panel.style.cssText = `
          position: absolute;
          top: 60px;
          right: 80px;
          width: 320px;
          background: #FFFFFF;
          border: 1px solid #E4EBE6;
          border-radius: 12px;
          box-shadow: 0 10px 25px rgba(10, 58, 42, 0.12);
          z-index: 1000;
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        `;
        panel.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #E4EBE6; padding-bottom:8px;">
            <strong style="color:#17251F; font-size:14px;">Notifications récentes</strong>
            <span style="font-size:11px; background:#DCFCE7; color:#16A34A; padding:2px 8px; border-radius:999px; font-weight:600;">3 non lues</span>
          </div>
          <div style="font-size:12px; color:#17251F; line-height:1.4;">
            <div style="padding:6px 0; border-bottom:1px solid #F1F5F3;">
              <span style="color:#16A34A; font-weight:600;">✓ Devis approuvé</span> : DEV-2026-0933 validé par Sara A.
              <div style="font-size:10px; color:#66756D;">Il y a 10 minutes</div>
            </div>
            <div style="padding:6px 0; border-bottom:1px solid #F1F5F3;">
              <span style="color:#2563EB; font-weight:600;">🛒 Nouvelle commande</span> : CMD-2026-0781 créée pour Atlas Services.
              <div style="font-size:10px; color:#66756D;">Il y a 27 minutes</div>
            </div>
            <div style="padding:6px 0;">
              <span style="color:#D97706; font-weight:600;">⚠️ Stock bas</span> : 5 unités restantes sur Écran 27" 4K.
              <div style="font-size:10px; color:#66756D;">Il y a 1 heure</div>
            </div>
          </div>
        `;
        document.body.appendChild(panel);
      } else {
        panel.style.display = panel.style.display === 'none' ? 'flex' : 'none';
      }
    });

    document.addEventListener('click', () => {
      const panel = document.getElementById('notifPanel');
      if (panel) panel.style.display = 'none';
    });
  }

  // Quick Action Modal ("+ Nouveau")
  function setupNewActionModal() {
    const newBtn = document.getElementById('btnQuickNew');
    if (!newBtn) return;

    newBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      let modal = document.getElementById('quickNewMenu');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'quickNewMenu';
        modal.style.cssText = `
          position: absolute;
          top: 60px;
          right: 24px;
          width: 220px;
          background: #FFFFFF;
          border: 1px solid #E4EBE6;
          border-radius: 10px;
          box-shadow: 0 10px 25px rgba(10, 58, 42, 0.12);
          z-index: 1000;
          padding: 8px 0;
          display: flex;
          flex-direction: column;
        `;
        modal.innerHTML = `
          <a href="quote_builder.html" style="padding:10px 16px; color:#17251F; font-size:13px; text-decoration:none; display:flex; align-items:center; gap:8px;">
            <span>📝</span> Nouveau devis
          </a>
          <a href="orders.html" style="padding:10px 16px; color:#17251F; font-size:13px; text-decoration:none; display:flex; align-items:center; gap:8px;">
            <span>🛒</span> Nouvelle commande
          </a>
          <a href="inbox.html" style="padding:10px 16px; color:#17251F; font-size:13px; text-decoration:none; display:flex; align-items:center; gap:8px;">
            <span>💬</span> Nouvelle conversation
          </a>
          <a href="schedule.html" style="padding:10px 16px; color:#17251F; font-size:13px; text-decoration:none; display:flex; align-items:center; gap:8px;">
            <span>📅</span> Planifier un appel
          </a>
        `;
        document.body.appendChild(modal);
      } else {
        modal.style.display = modal.style.display === 'none' ? 'flex' : 'none';
      }
    });

    document.addEventListener('click', () => {
      const modal = document.getElementById('quickNewMenu');
      if (modal) modal.style.display = 'none';
    });
  }

  function closeAllModals() {
    const notifPanel = document.getElementById('notifPanel');
    if (notifPanel) notifPanel.style.display = 'none';
    const quickMenu = document.getElementById('quickNewMenu');
    if (quickMenu) quickMenu.style.display = 'none';
  }

  // Toast Notification Helper
  function showToast(message) {
    let toast = document.getElementById('salesAiToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'salesAiToast';
      toast.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        background: #0A3A2A;
        color: #FFFFFF;
        padding: 12px 20px;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 500;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 9999;
        transition: opacity 0.2s, transform 0.2s;
        opacity: 0;
        transform: translateY(10px);
      `;
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.style.opacity = '1';
    toast.style.transform = 'translateY(0)';
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
    }, 2800);
  }

  // Expose global helper
  window.SalesAI = {
    state: AppState,
    showToast: showToast
  };

})();
