/**
 * SALES AI MANAGEMENT PLATFORM — APP SHELL CONTROLLER (V2.0)
 * Handles global navigation, tenant switching, search shortcuts, responsive drawer,
 * notification panel, and unified state across all 28 views.
 */

(function () {
  'use strict';

  // 1. Initialize Global Tenant & Auth State
  const AppState = {
    currentTenant: localStorage.getItem('sales_ai_tenant') || 'Atlas Commerce',
    tenantId: localStorage.getItem('sales_ai_tenant_id') || 'tenant-atlas-commerce',
    currentUser: {
      name: 'Omar Soubaibi',
      initials: 'OS',
      email: 'omar@atlas-commerce.ma',
      role: 'Administrateur',
      activeAgents: 4
    }
  };

  // 2. Setup DOM Listeners once loaded
  document.addEventListener('DOMContentLoaded', () => {
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

  // Tenant Switcher Logic
  function setupTenantSelector() {
    const selectorPill = document.getElementById('tenantSelectorPill');
    if (!selectorPill) return;

    selectorPill.addEventListener('click', () => {
      const tenants = ['Atlas Commerce (Casablanca)', 'Acme Corp (Production)', 'Sahara Logistics (Agadir)', 'Nord Digital (Tanger)'];
      const nextIndex = (tenants.findIndex(t => t.includes(AppState.currentTenant)) + 1) % tenants.length;
      const newTenant = tenants[nextIndex].split(' ')[0] + ' ' + tenants[nextIndex].split(' ')[1];
      AppState.currentTenant = newTenant;
      localStorage.setItem('sales_ai_tenant', newTenant);
      
      const label = document.getElementById('currentTenantLabel');
      if (label) label.textContent = newTenant;
      
      showToast(`Contexte changé : ${newTenant}`);
    });
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
