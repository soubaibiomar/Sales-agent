/* Selia — Stock & entrepôts: inventory items per warehouse, article and warehouse creation. */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const $ = (id) => document.getElementById(id);
  const LOW = 5;
  const level = (i) => i.available_to_promise <= 0 ? 'OUT' : (i.available_to_promise <= LOW ? 'LOW' : 'OK');
  const PILL = { OK: ['En stock', 'ok'], LOW: ['Stock bas', 'warn'], OUT: ['Rupture', 'danger'] };
  function init() {
    let warehouses = [];
    const list = L.mount({
      url: '/api/v1/inventory/items', accountsUrl: false, lookups: { wh: '/api/v1/inventory/warehouses' }, cols: 6, noun: 'articles',
      empty: 'Aucun article en stock.',
      onLoaded: (ctx) => {
        warehouses = ctx.wh; ctx.whName = {}; ctx.wh.forEach(w => { ctx.whName[w.id] = w.name; });
        $('iWh').innerHTML = '<option value="">' + (ctx.wh.length ? 'Choisir un entrepôt…' : "Créez d'abord un entrepôt") + '</option>' +
          ctx.wh.map(w => '<option value="' + V.esc(w.id) + '">' + V.esc(w.name + ' (' + w.code + ')') + '</option>').join('');
      },
      statusOf: level,
      chips: [['all', 'Tous', null], ['ok', 'En stock', ['OK']], ['low', 'Stock bas', ['LOW']], ['out', 'Rupture', ['OUT']]],
      search: (i, n, ctx) => [i.sku, (ctx.whName || {})[i.warehouse_id]].join(' '),
      kpis: (rows) => L.kpi('grid', '', 'Articles', rows.length) +
        L.kpi('cart', 'sand', 'Unités disponibles', rows.reduce((n, i) => n + Math.max(0, i.available_to_promise || 0), 0).toLocaleString('fr-FR')) +
        L.kpi('target', 'terra', 'Ruptures', rows.filter(i => level(i) === 'OUT').length, rows.filter(i => level(i) === 'LOW').length + ' en stock bas') +
        L.kpi('home', '', 'Entrepôts', warehouses.length),
      row: (i, n, ctx) => {
        const p = PILL[level(i)];
        return '<tr><td data-label=""><code>' + V.esc(i.sku) + '</code></td><td data-label="Entrepôt">' + V.esc((ctx.whName || {})[i.warehouse_id] || '—') + '</td>' +
          '<td data-label="En stock" class="num">' + V.esc(i.on_hand_quantity) + '</td>' +
          '<td data-label="Réservé" class="num">' + V.esc((i.reserved_quantity || 0) + (i.allocated_quantity || 0)) + '</td>' +
          '<td data-label="Disponible" class="num"><strong>' + V.esc(i.available_to_promise) + '</strong></td><td data-label="Statut">' + V.pill(p[0], p[1]) + '</td></tr>';
      }
    });
    $('btnNew').addEventListener('click', () => window.SalesAI.openModal('newModal'));
    $('btnNewWh').addEventListener('click', () => window.SalesAI.openModal('whModal'));
    $('newModalForm').addEventListener('submit', (e) => {
      e.preventDefault();
      if (!$('iWh').value || !$('iSku').value.trim()) { e.target.querySelector('.form-error').textContent = 'Entrepôt et SKU sont obligatoires.'; return; }
      L.submitForm(e.target, '/api/v1/inventory/items',
        { warehouse_id: $('iWh').value, sku: $('iSku').value.trim(), initial_on_hand: Math.max(0, Number($('iQty').value || 0)) },
        'Article créé.', () => list.reload());
    });
    $('whModalForm').addEventListener('submit', (e) => {
      e.preventDefault();
      if (!$('wCode').value.trim() || !$('wName').value.trim()) { e.target.querySelector('.form-error').textContent = 'Code et nom sont obligatoires.'; return; }
      L.submitForm(e.target, '/api/v1/inventory/warehouses',
        { code: $('wCode').value.trim(), name: $('wName').value.trim(), address_json: JSON.stringify({ city: $('wCity').value.trim() }) },
        'Entrepôt créé.', () => list.reload());
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
