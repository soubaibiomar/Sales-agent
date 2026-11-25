/* Selia — Catalogue produits: /api/v1/catalog/products with creation. */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const $ = (id) => document.getElementById(id);
  function init() {
    const list = L.mount({
      url: '/api/v1/catalog/products?limit=500', accountsUrl: false, cols: 6, noun: 'produits', empty: 'Catalogue vide. Ajoutez votre premier produit.',
      statusOf: (p) => p.is_active ? 'ACTIVE' : 'INACTIVE',
      chips: [['all', 'Tous', null], ['on', 'Actifs', ['ACTIVE']], ['off', 'Inactifs', ['INACTIVE']]],
      search: (p) => [p.sku, p.name, p.category].join(' '),
      kpis: (rows) => {
        const cats = new Set(rows.map(p => p.category).filter(Boolean));
        const avg = rows.length ? rows.reduce((n, p) => n + (p.base_price_cents || 0), 0) / rows.length : 0;
        return L.kpi('grid', '', 'Produits', rows.length) + L.kpi('target', '', 'Actifs', rows.filter(p => p.is_active).length) +
          L.kpi('doc', 'sand', 'Catégories', cats.size) + L.kpi('chart', 'terra', 'Prix moyen HT', V.esc(V.amount(avg)) + '<small>MAD</small>');
      },
      row: (p) => '<tr><td data-label=""><code>' + V.esc(p.sku) + '</code></td><td data-label="Produit"><strong>' + V.esc(p.name) + '</strong>' +
        (p.product_type === 'SERVICE' ? '<span class="cell-sub">Service</span>' : '') + '</td>' +
        '<td data-label="Catégorie">' + V.esc(p.category || '—') + '</td>' +
        '<td data-label="Prix HT (MAD)" class="num">' + V.esc(V.money(p.base_price_cents, '').trim()) + '</td>' +
        '<td data-label="TVA">' + V.esc(Number(p.tax_rate_percent).toLocaleString('fr-FR')) + ' %</td>' +
        '<td data-label="Statut">' + V.pill(p.is_active ? 'ACTIVE' : 'INACTIVE') + '</td></tr>'
    });
    $('btnNew').addEventListener('click', () => window.SalesAI.openModal('newModal'));
    $('newModalForm').addEventListener('submit', (e) => {
      e.preventDefault();
      const err = e.target.querySelector('.form-error');
      if (!$('pSku').value.trim() || !$('pName').value.trim() || $('pPrice').value === '') { err.textContent = 'SKU, nom et prix sont obligatoires.'; return; }
      L.submitForm(e.target, '/api/v1/catalog/products', {
        sku: $('pSku').value.trim(), name: $('pName').value.trim(), category: $('pCategory').value.trim() || null, uom: $('pUom').value,
        product_type: $('pType').value, base_price_cents: Math.round(Number($('pPrice').value) * 100),
        cost_cents: Math.round(Number($('pCost').value || 0) * 100), tax_rate_percent: String($('pTax').value || '20'),
        description: $('pDesc').value.trim() || null, currency: 'MAD'
      }, 'Produit créé.', () => list.reload());
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
