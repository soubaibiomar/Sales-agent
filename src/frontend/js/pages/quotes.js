/* Selia — Devis: live quotes with status chips, KPIs and conversion rate. */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const OPEN = ['DRAFT', 'PRICED', 'PENDING_APPROVAL', 'APPROVED', 'ISSUED', 'SENT'];
  const WAITING = ['PENDING_APPROVAL', 'ISSUED', 'SENT'];
  function init() {
    L.mount({
      url: '/api/v1/quotes?limit=500', cols: 6, dateField: 'created_at', noun: 'devis',
      chips: [['all', 'Tous', null], ['waiting', 'En attente', WAITING], ['accepted', 'Acceptés', ['ACCEPTED']],
              ['rejected', 'Refusés', ['REJECTED']], ['expired', 'Expirés', ['EXPIRED']]],
      search: (q, names) => [q.quote_number, names.get(q.account_id)].join(' '),
      kpis: (rows) => {
        const n = (st) => rows.filter(q => st.indexOf(q.status) !== -1).length;
        const decided = n(['ACCEPTED', 'REJECTED', 'EXPIRED']);
        const rate = decided ? Math.round(100 * n(['ACCEPTED']) / decided) + ' %' : '—';
        return L.kpi('doc', '', 'Devis actifs', n(OPEN)) + L.kpi('chat', 'terra', 'En attente', n(WAITING)) +
          L.kpi('target', '', 'Acceptés', n(['ACCEPTED'])) + L.kpi('chart', 'sand', 'Taux de conversion', rate, decided ? 'sur ' + decided + ' devis clôturés' : 'Aucun devis clôturé');
      },
      row: (q, names) => '<tr><td data-label=""><strong>' + V.esc(q.quote_number) + '</strong></td>' +
        '<td data-label="Client">' + V.esc(names.get(q.account_id) || '—') + '</td>' +
        '<td data-label="Montant (MAD)" class="num">' + V.esc(V.money(q.grand_total_cents, '').trim()) + '</td>' +
        '<td data-label="Date">' + V.esc(V.date(q.created_at)) + '</td><td data-label="Échéance">' + V.esc(V.date(q.valid_until)) + '</td>' +
        '<td data-label="Statut">' + V.pill(q.status) + '</td></tr>'
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
