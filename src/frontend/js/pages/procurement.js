/* Selia — Achats & fournisseurs: purchase orders and suppliers, supplier creation. */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const $ = (id) => document.getElementById(id);
  const TERMS = { NET_30: '30 jours', NET_60: '60 jours', DUE_ON_RECEIPT: 'À réception' };

  function renderSuppliers(suppliers, ok) {
    const tbody = $('supplierRows');
    if (!ok) { V.rowState(tbody, 5, 'error', 'Fournisseurs indisponibles.'); return; }
    tbody.innerHTML = suppliers.length ? suppliers.map(s => '<tr><td data-label=""><span class="cell-entity"><span class="avatar-initials ' + V.tone(s.id) + '">' +
      V.esc(V.initials(s.name)) + '</span><span><strong>' + V.esc(s.name) + '</strong><span class="cell-sub">' + V.esc(s.supplier_code) + '</span></span></span></td>' +
      '<td data-label="Contact">' + V.esc(s.contact_name || '—') + '</td><td data-label="E-mail">' + V.esc(s.email || '—') + '</td>' +
      '<td data-label="Téléphone">' + V.esc(s.phone || '—') + '</td><td data-label="Conditions">' + V.esc(TERMS[s.payment_terms] || s.payment_terms || '—') + '</td></tr>').join('')
      : '<tr><td colspan="5" class="data-state">Aucun fournisseur. Ajoutez votre premier fournisseur.</td></tr>';
  }

  function init() {
    let suppliers = [];
    const list = L.mount({
      url: '/api/v1/procurement/purchase-orders', accountsUrl: false, lookups: { suppliers: '/api/v1/procurement/suppliers' },
      cols: 6, dateField: 'created_at', noun: 'bons de commande', empty: 'Aucun bon de commande.',
      onLoaded: (ctx) => { suppliers = ctx.suppliers; ctx.sup = {}; ctx.suppliers.forEach(s => { ctx.sup[s.id] = s.name; }); renderSuppliers(ctx.suppliers, ctx.suppliersOk); },
      chips: [['all', 'Tous', null], ['draft', 'Brouillons', ['DRAFT']], ['approval', 'À approuver', ['PENDING_APPROVAL', 'REQUESTED']],
              ['issued', 'Émis', ['APPROVED', 'ISSUED', 'IN_TRANSIT']], ['received', 'Reçus', ['RECEIVED', 'PARTIALLY_RECEIVED']]],
      search: (p, n, ctx) => [p.po_number, (ctx.sup || {})[p.supplier_id]].join(' '),
      kpis: (rows) => L.kpi('users', '', 'Fournisseurs', suppliers.length) + L.kpi('doc', 'sand', 'Bons de commande', rows.length) +
        L.kpi('target', 'terra', 'À approuver', rows.filter(p => ['DRAFT', 'PENDING_APPROVAL', 'REQUESTED'].indexOf(p.status) !== -1).length) +
        L.kpi('chart', '', 'Montant engagé', V.esc(V.amount(rows.filter(p => p.status !== 'CANCELLED').reduce((n, p) => n + (p.grand_total_cents || 0), 0))) + '<small>MAD</small>'),
      row: (p, n, ctx) => '<tr><td data-label=""><strong>' + V.esc(p.po_number) + '</strong></td>' +
        '<td data-label="Fournisseur">' + V.esc((ctx.sup || {})[p.supplier_id] || '—') + '</td>' +
        '<td data-label="Montant (MAD)" class="num">' + V.esc(V.money(p.grand_total_cents, '').trim()) + '</td>' +
        '<td data-label="Créé le">' + V.esc(V.date(p.created_at)) + '</td><td data-label="Livraison prévue">' + V.esc(V.date(p.expected_delivery_date)) + '</td>' +
        '<td data-label="Statut">' + V.pill(p.status) + '</td></tr>'
    });
    $('btnNew').addEventListener('click', () => window.SalesAI.openModal('newModal'));
    $('newModalForm').addEventListener('submit', (e) => {
      e.preventDefault();
      if (!$('sCode').value.trim() || !$('sName').value.trim()) { e.target.querySelector('.form-error').textContent = 'Code et raison sociale sont obligatoires.'; return; }
      L.submitForm(e.target, '/api/v1/procurement/suppliers', {
        supplier_code: $('sCode').value.trim(), name: $('sName').value.trim(), contact_name: $('sContact').value.trim() || null,
        email: $('sEmail').value.trim() || null, phone: $('sPhone').value.trim() || null, payment_terms: $('sTerms').value, currency: 'MAD'
      }, 'Fournisseur créé.', () => list.reload());
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
