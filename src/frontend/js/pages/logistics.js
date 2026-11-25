/* Selia — Logistique: shipments with tracking and delivery status. */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const PREP = ['CREATED', 'PICKING', 'PACKED'], TRANSIT = ['SHIPPED', 'IN_TRANSIT', 'OUT_FOR_DELIVERY'];
  function init() {
    L.mount({
      url: '/api/v1/logistics/shipments', accountsUrl: false, lookups: { orders: '/api/v1/orders' }, cols: 6, dateField: 'created_at', noun: 'expéditions',
      empty: 'Aucune expédition.',
      onLoaded: (ctx) => { ctx.orderNo = {}; ctx.orders.forEach(o => { ctx.orderNo[o.id] = o.order_number; }); },
      chips: [['all', 'Toutes', null], ['prep', 'En préparation', PREP], ['transit', 'En transit', TRANSIT], ['done', 'Livrées', ['DELIVERED']], ['fail', 'Incidents', ['FAILED', 'RETURNED']]],
      search: (s, n, ctx) => [s.shipment_number, s.tracking_number, s.carrier_code, (ctx.orderNo || {})[s.order_id]].join(' '),
      kpis: (rows) => {
        const n = (st) => rows.filter(s => st.indexOf(s.status) !== -1).length;
        return L.kpi('cart', '', 'Expéditions', rows.length) + L.kpi('grid', 'sand', 'En préparation', n(PREP)) +
          L.kpi('arrow', 'terra', 'En transit', n(TRANSIT)) + L.kpi('target', '', 'Livrées', n(['DELIVERED']), n(['FAILED', 'RETURNED']) + ' incident(s)');
      },
      row: (s, n, ctx) => '<tr><td data-label=""><strong>' + V.esc(s.shipment_number) + '</strong></td>' +
        '<td data-label="Commande">' + V.esc((ctx.orderNo || {})[s.order_id] || '—') + '</td>' +
        '<td data-label="Transporteur">' + V.esc([s.carrier_code, s.carrier_service].filter(Boolean).join(' · ') || '—') + '</td>' +
        '<td data-label="Suivi">' + (s.tracking_number ? '<code>' + V.esc(s.tracking_number) + '</code>' : '—') + '</td>' +
        '<td data-label="Livraison estimée">' + V.esc(V.date(s.delivered_at || s.estimated_delivery_at)) + '</td>' +
        '<td data-label="Statut">' + V.pill(s.status) + '</td></tr>'
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
