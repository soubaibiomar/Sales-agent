/* Invoices page: live invoices (F-20). Values are escaped; loading/empty/error states shown. */
(function () {
  'use strict';
  var V = window.SalesViews;
  var BADGE = { PAID: 'badge-paid', ISSUED: 'badge-issued' };

  async function loadInvoices() {
    var tbody = document.getElementById('invoices-body');
    if (!tbody) { return; }
    V.rowState(tbody, 9, 'loading', 'Chargement des factures…');
    var res = await V.getJson('/api/v1/invoices');
    if (!res.ok) { V.rowState(tbody, 9, 'error', V.errorText(res)); return; }
    var rows = Array.isArray(res.data) ? res.data : [];
    if (!rows.length) { V.rowState(tbody, 9, 'empty', 'Aucune facture émise pour le moment.'); return; }
    tbody.innerHTML = rows.map(function (inv) {
      return '<tr>' +
        '<td><strong>' + V.esc(inv.invoice_number) + '</strong></td>' +
        '<td><span class="badge ' + (BADGE[inv.status] || 'badge-cancelled') + '">' + V.esc(inv.status) + '</span></td>' +
        '<td>' + V.esc(V.money(inv.subtotal_cents, inv.currency)) + '</td>' +
        '<td>' + V.esc(V.money(inv.tax_total_cents, inv.currency)) + '</td>' +
        '<td><strong>' + V.esc(V.money(inv.grand_total_cents, inv.currency)) + '</strong></td>' +
        '<td><code>' + V.esc(String(inv.invoice_hash || '').substring(0, 12)) + '…</code></td>' +
        '<td>' + V.esc(V.date(inv.issued_at)) + '</td>' +
        '<td>' + V.esc(V.date(inv.due_date)) + '</td>' +
        '<td><a class="btn btn-outline" href="/api/v1/invoices/' + encodeURIComponent(inv.id) + '">Détail</a></td>' +
        '</tr>';
    }).join('');
  }

  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', loadInvoices); } else { loadInvoices(); }
})();
