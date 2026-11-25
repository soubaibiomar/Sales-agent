/* Selia — Paiements: payment transactions (captures, refunds, failures). */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const TYPE = { CAPTURE: 'Encaissement', AUTHORIZATION: 'Autorisation', REFUND: 'Remboursement', VOID: 'Annulation' };
  const OK = ['SUCCEEDED', 'SUCCESS', 'COMPLETED', 'PROCESSED'];
  function init() {
    L.mount({
      url: '/api/v1/payments/transactions', accountsUrl: false, lookups: { orders: '/api/v1/orders' }, cols: 7, dateField: 'created_at', noun: 'transactions',
      empty: 'Aucune transaction de paiement.',
      onLoaded: (ctx) => { ctx.orderNo = {}; ctx.orders.forEach(o => { ctx.orderNo[o.id] = o.order_number; }); },
      chips: [['all', 'Toutes', null], ['ok', 'Réussies', OK], ['fail', 'Échecs', ['FAILED']], ['pending', 'En attente', ['PENDING', 'REQUIRES_PAYMENT_METHOD']]],
      search: (t, n, ctx) => [t.provider_transaction_id, t.id, (ctx.orderNo || {})[t.order_id]].join(' '),
      kpis: (rows) => {
        const sum = (type) => rows.filter(t => OK.indexOf(t.status) !== -1 && String(t.transaction_type).toUpperCase() === type)
          .reduce((n, t) => n + (t.amount_cents || 0), 0);
        return L.kpi('chart', '', 'Encaissé', V.esc(V.amount(sum('CAPTURE'))) + '<small>MAD</small>') +
          L.kpi('doc', 'sand', 'Remboursé', V.esc(V.amount(sum('REFUND'))) + '<small>MAD</small>') +
          L.kpi('cart', '', 'Transactions', rows.length) + L.kpi('target', 'terra', 'Échecs', rows.filter(t => t.status === 'FAILED').length);
      },
      row: (t, n, ctx) => '<tr><td data-label=""><code>' + V.esc(String(t.provider_transaction_id || t.id).slice(0, 18)) + '</code></td>' +
        '<td data-label="Commande">' + V.esc((ctx.orderNo || {})[t.order_id] || '—') + '</td>' +
        '<td data-label="Type">' + V.esc(TYPE[String(t.transaction_type).toUpperCase()] || t.transaction_type) + '</td>' +
        '<td data-label="Moyen">' + V.esc(t.payment_method_type || '—') + '</td>' +
        '<td data-label="Montant (MAD)" class="num">' + V.esc(V.money(t.amount_cents, '').trim()) + '</td>' +
        '<td data-label="Date">' + V.esc(V.date(t.created_at)) + '</td><td data-label="Statut">' + V.pill(t.status) + '</td></tr>'
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
