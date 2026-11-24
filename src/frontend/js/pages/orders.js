/* Orders page: live sales orders (F-20). Replaces the hardcoded demo rows; values escaped. */
(function () {
  'use strict';
  var V = window.SalesViews;

  async function loadOrders() {
    var tbody = document.getElementById('orders-body');
    if (!tbody) { return; }
    V.rowState(tbody, 9, 'loading', 'Chargement des commandes…');
    var res = await V.getJson('/api/v1/orders');
    if (!res.ok) { V.rowState(tbody, 9, 'error', V.errorText(res)); return; }
    var rows = Array.isArray(res.data) ? res.data : [];
    if (!rows.length) { V.rowState(tbody, 9, 'empty', 'Aucune commande pour le moment.'); return; }
    tbody.innerHTML = rows.map(function (o) {
      return '<tr>' +
        '<td><strong>' + V.esc(o.order_number) + '</strong></td>' +
        '<td>' + V.esc(o.account_id || 'Client direct') + '</td>' +
        '<td><strong>' + V.esc(V.money(o.grand_total_cents, o.currency)) + '</strong></td>' +
        '<td><span class="badge badge-success">' + V.esc(o.status) + '</span></td>' +
        '<td><span class="badge badge-info">' + V.esc(o.payment_status) + '</span></td>' +
        '<td><span class="badge badge-purple">' + V.esc(o.fulfillment_status) + '</span></td>' +
        '<td><code>' + V.esc(String(o.terms_hash || '').slice(0, 8)) + '…</code></td>' +
        '<td>' + V.esc(V.date(o.created_at)) + '</td>' +
        '<td><a href="invoices.html?order_id=' + encodeURIComponent(o.id) + '" class="btn btn-outline">Facture</a></td>' +
        '</tr>';
    }).join('');
  }

  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', loadOrders); } else { loadOrders(); }
})();
