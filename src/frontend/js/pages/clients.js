/* Selia — Clients: live accounts, revenue per client from orders, filters, search,
 * pagination, and account creation through POST /api/v1/crm/accounts. */
(function () {
  'use strict';
  const V = window.SalesViews;
  const $ = (id) => document.getElementById(id);
  const PAGE = 8;
  let accounts = [], revenue = new Map(), filter = 'all', page = 1;

  function filtered() {
    const q = ($('clientSearch').value || '').trim().toLowerCase();
    return accounts.filter(a => (filter === 'all' || a.account_type === filter) &&
      (!q || [a.name, a.industry, a.billing_address].some(v => String(v || '').toLowerCase().indexOf(q) !== -1)));
  }

  function statusPill(a) {
    if (!a.is_active) return V.pill('INACTIVE');
    return a.account_type === 'PROSPECT' ? V.pill('Prospect', 'warn') : V.pill('Client', 'ok');
  }

  function render() {
    const rows = filtered();
    const pages = Math.max(1, Math.ceil(rows.length / PAGE));
    page = Math.min(page, pages);
    const slice = rows.slice((page - 1) * PAGE, page * PAGE);
    const tbody = $('clientRows');
    if (!rows.length) {
      V.rowState(tbody, 6, 'empty', accounts.length ? 'Aucun client ne correspond à votre recherche.' : 'Aucun client pour le moment. Créez votre premier client.');
    } else {
      tbody.innerHTML = slice.map(a =>
        '<tr><td data-label=""><span class="cell-entity"><span class="avatar-initials ' + V.tone(a.id) + '">' + V.esc(V.initials(a.name)) +
        '</span><span><strong>' + V.esc(a.name) + '</strong>' + (a.phone ? '<span class="cell-sub">' + V.esc(a.phone) + '</span>' : '') + '</span></span></td>' +
        '<td data-label="Secteur">' + V.esc(a.industry || '—') + '</td>' +
        '<td data-label="Ville">' + V.esc(a.billing_address || '—') + '</td>' +
        '<td data-label="CA (MAD)" class="num">' + V.esc(revenue.has(a.id) ? V.money(revenue.get(a.id), '').trim() : '—') + '</td>' +
        '<td data-label="Statut">' + statusPill(a) + '</td>' +
        '<td data-label="Dernière activité">' + V.esc(V.ago(a.updated_at || a.created_at)) + '</td></tr>').join('');
    }
    const counts = { all: accounts.length, CUSTOMER: accounts.filter(a => a.account_type === 'CUSTOMER').length, PROSPECT: accounts.filter(a => a.account_type === 'PROSPECT').length };
    document.querySelectorAll('[data-filter]').forEach(b => {
      const k = b.getAttribute('data-filter');
      b.textContent = { all: 'Tous', CUSTOMER: 'Clients', PROSPECT: 'Prospects' }[k] + ' (' + counts[k] + ')';
    });
    $('clientCount').textContent = '(' + accounts.length.toLocaleString('fr-FR') + ')';
    renderPager(rows.length, pages);
  }

  function renderPager(total, pages) {
    const from = total ? (page - 1) * PAGE + 1 : 0, to = Math.min(total, page * PAGE);
    let btns = '<button type="button" data-page="' + (page - 1) + '"' + (page <= 1 ? ' disabled' : '') + ' aria-label="Page précédente">‹</button>';
    for (let p = 1; p <= pages; p++) {
      if (pages > 7 && p > 2 && p < pages - 1 && Math.abs(p - page) > 1) { if (p === 3 || p === pages - 2) btns += '<button type="button" disabled>…</button>'; continue; }
      btns += '<button type="button" data-page="' + p + '"' + (p === page ? ' aria-current="page"' : '') + '>' + p + '</button>';
    }
    btns += '<button type="button" data-page="' + (page + 1) + '"' + (page >= pages ? ' disabled' : '') + ' aria-label="Page suivante">›</button>';
    $('pager').innerHTML = '<span>Affichage ' + from + '–' + to + ' sur ' + total + ' client' + (total > 1 ? 's' : '') + '</span><span class="pager-buttons">' + btns + '</span>';
  }

  async function load() {
    const [acc, ord] = await Promise.all([V.getJson('/api/v1/crm/accounts?limit=500'), V.getJson('/api/v1/orders')]);
    if (!acc.ok) { V.rowState($('clientRows'), 6, 'error', V.errorText(acc)); return; }
    accounts = V.list(acc.data).sort((a, b) => String(a.name).localeCompare(String(b.name), 'fr'));
    revenue = new Map();
    if (ord.ok) V.list(ord.data).filter(o => o.status !== 'CANCELLED' && o.account_id)
      .forEach(o => revenue.set(o.account_id, (revenue.get(o.account_id) || 0) + (o.grand_total_cents || 0)));
    render();
  }

  async function create(e) {
    e.preventDefault();
    const err = $('clientFormError');
    const name = $('cName').value.trim();
    if (!name) { err.textContent = 'Le nom du client est obligatoire.'; $('cName').focus(); return; }
    const submit = e.target.querySelector('[type=submit]');
    submit.disabled = true; err.textContent = '';
    const res = await V.getJson('/api/v1/crm/accounts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, account_type: $('cType').value, industry: $('cIndustry').value.trim() || null,
        phone: $('cPhone').value.trim() || null, tax_identifier: $('cTax').value.trim() || null, billing_address: $('cCity').value.trim() || null })
    });
    submit.disabled = false;
    if (!res.ok) { err.textContent = res.status === 403 ? "Votre rôle ne permet pas de créer un client." : 'Création impossible : ' + V.errorText(res); return; }
    $('clientModal').hidden = true; e.target.reset();
    window.SalesAI.showToast('Client « ' + name + ' » créé.');
    load();
  }

  function init() {
    const q = new URLSearchParams(location.search).get('q');
    if (q) $('clientSearch').value = q;
    $('clientSearch').addEventListener('input', () => { page = 1; render(); });
    document.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => {
      filter = b.getAttribute('data-filter'); page = 1;
      document.querySelectorAll('[data-filter]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      render();
    }));
    $('pager').addEventListener('click', (e) => { const b = e.target.closest('[data-page]'); if (b && !b.disabled) { page = Number(b.getAttribute('data-page')); render(); } });
    $('btnNewClient').addEventListener('click', () => window.SalesAI.openModal('clientModal'));
    $('clientForm').addEventListener('submit', create);
    if (location.hash === '#nouveau') window.SalesAI.openModal('clientModal');
    window.addEventListener('hashchange', () => { if (location.hash === '#nouveau') { window.SalesAI.openModal('clientModal'); } });
    load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
