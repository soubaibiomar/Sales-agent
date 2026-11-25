/* Selia — Factures: invoices with a computed payment status, and "Facturer une commande"
 * (POST /api/v1/invoices/from-order). */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const $ = (id) => document.getElementById(id);
  const VOID = ['CANCELLED', 'VOID', 'VOIDED', 'CREDITED'];
  function computed(i) {
    if (VOID.indexOf(String(i.status).toUpperCase()) !== -1) return 'CANCELLED';
    if (i.paid_at) return 'PAID';
    return new Date(i.due_date) < new Date() ? 'OVERDUE' : 'UNPAID';
  }
  function init() {
    const list = L.mount({
      url: '/api/v1/invoices', accountsUrl: false, lookups: { orders: '/api/v1/orders' }, cols: 6, dateField: 'issued_at', noun: 'factures',
      empty: 'Aucune facture. Facturez une commande confirmée pour commencer.',
      transform: (items) => items.map(i => Object.assign({}, i, { computed: computed(i) })),
      statusOf: (i) => i.computed,
      chips: [['all', 'Toutes', null], ['unpaid', 'À encaisser', ['UNPAID']], ['late', 'En retard', ['OVERDUE']], ['paid', 'Payées', ['PAID']], ['void', 'Annulées', ['CANCELLED']]],
      search: (i, n, ctx) => [i.invoice_number, (ctx.orderNo || {})[i.order_id]].join(' '),
      onLoaded: (ctx) => { ctx.orderNo = {}; ctx.orders.forEach(o => { ctx.orderNo[o.id] = o.order_number; }); },
      kpis: (rows) => {
        const live = rows.filter(i => i.computed !== 'CANCELLED');
        const sum = (f) => live.filter(f).reduce((n, i) => n + (i.grand_total_cents || 0), 0);
        return L.kpi('doc', '', 'Factures', live.length) +
          L.kpi('chart', 'sand', 'Montant facturé', V.esc(V.amount(sum(() => true))) + '<small>MAD</small>') +
          L.kpi('target', '', 'Encaissé', V.esc(V.amount(sum(i => i.computed === 'PAID'))) + '<small>MAD</small>') +
          L.kpi('calendar', 'terra', 'En retard', V.esc(V.amount(sum(i => i.computed === 'OVERDUE'))) + '<small>MAD</small>',
            live.filter(i => i.computed === 'OVERDUE').length + ' facture(s)');
      },
      row: (i, n, ctx) => '<tr><td data-label=""><strong>' + V.esc(i.invoice_number) + '</strong></td>' +
        '<td data-label="Commande">' + V.esc((ctx.orderNo || {})[i.order_id] || '—') + '</td>' +
        '<td data-label="Montant (MAD)" class="num">' + V.esc(V.money(i.grand_total_cents, '').trim()) + '</td>' +
        '<td data-label="Émise le">' + V.esc(V.date(i.issued_at)) + '</td><td data-label="Échéance">' + V.esc(V.date(i.due_date)) + '</td>' +
        '<td data-label="Statut">' + V.pill(i.computed) + '</td></tr>'
    });
    $('btnNew').addEventListener('click', async () => {
      const [orders, invoices] = await Promise.all([V.getJson('/api/v1/orders'), V.getJson('/api/v1/invoices')]);
      const invoiced = new Set((invoices.ok ? V.list(invoices.data) : []).map(i => i.order_id));
      const eligible = (orders.ok ? V.list(orders.data) : []).filter(o => o.status !== 'CANCELLED' && !invoiced.has(o.id));
      $('fOrder').innerHTML = '<option value="">' + (eligible.length ? 'Choisir une commande…' : 'Aucune commande à facturer') + '</option>' +
        eligible.map(o => '<option value="' + V.esc(o.id) + '">' + V.esc(o.order_number + ' — ' + V.money(o.grand_total_cents, o.currency)) + '</option>').join('');
      window.SalesAI.openModal('newModal');
    });
    $('newModalForm').addEventListener('submit', (e) => {
      e.preventDefault();
      if (!$('fOrder').value) { e.target.querySelector('.form-error').textContent = 'Choisissez une commande.'; return; }
      L.submitForm(e.target, '/api/v1/invoices/from-order',
        { order_id: $('fOrder').value, due_days: Number($('fDue').value || 30), notes: $('fNotes').value.trim() || null },
        'Facture créée.', () => list.reload());
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
