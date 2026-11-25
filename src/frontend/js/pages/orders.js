/* Selia — Commandes: live sales orders with status chips and totals. */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const PREP = ['PROCESSING', 'IN_PREPARATION', 'PENDING_PAYMENT'], RUNNING = ['CONFIRMED', 'SHIPPED'], DONE = ['DELIVERED', 'COMPLETED'];
  const PAY = { PAID: ['Payée', 'ok'], CAPTURED: ['Payée', 'ok'], PENDING: ['En attente', 'warn'], UNPAID: ['Non payée', 'neutral'], REFUNDED: ['Remboursée', 'info'], FAILED: ['Échec', 'danger'] };
  function init() {
    L.mount({
      url: '/api/v1/orders', cols: 6, dateField: 'created_at', noun: 'commandes',
      chips: [['all', 'Toutes', null], ['prep', 'En préparation', PREP], ['run', 'En cours', RUNNING], ['done', 'Livrées', DONE], ['cancel', 'Annulées', ['CANCELLED']]],
      search: (o, names) => [o.order_number, names.get(o.account_id)].join(' '),
      kpis: (rows) => {
        const live = rows.filter(o => o.status !== 'CANCELLED');
        const total = live.reduce((n, o) => n + (o.grand_total_cents || 0), 0);
        const n = (st) => rows.filter(o => st.indexOf(o.status) !== -1).length;
        return L.kpi('cart', '', 'Total commandes', rows.length) +
          L.kpi('chart', 'sand', 'Montant total', V.esc(V.amount(total)) + '<small>MAD</small>') +
          L.kpi('cart', 'terra', 'En cours', n(PREP.concat(RUNNING))) + L.kpi('target', '', 'Livrées', n(DONE));
      },
      row: (o, names) => {
        const p = PAY[String(o.payment_status || '').toUpperCase()] || [o.payment_status || '—', 'neutral'];
        return '<tr><td data-label=""><strong>' + V.esc(o.order_number) + '</strong></td>' +
          '<td data-label="Client">' + V.esc(names.get(o.account_id) || '—') + '</td>' +
          '<td data-label="Montant (MAD)" class="num">' + V.esc(V.money(o.grand_total_cents, '').trim()) + '</td>' +
          '<td data-label="Date">' + V.esc(V.date(o.created_at)) + '</td>' +
          '<td data-label="Paiement">' + V.pill(p[0], p[1]) + '</td><td data-label="Statut">' + V.pill(o.status) + '</td></tr>';
      }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
