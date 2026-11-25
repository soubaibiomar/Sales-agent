/* Executive dashboard: live KPI cards (F-20).
 * KPI values come from /api/v1/analytics/overview, /api/v1/quotes and /api/v1/crm/accounts.
 * The former fixed numbers and invented "+14,8% vs mois précédent" trends are removed;
 * each card states what it measures. Widgets that are still illustrative are labelled. */
(function () {
  'use strict';
  var V = window.SalesViews;
  var OPEN_QUOTE = ['DRAFT', 'PRICED', 'PENDING_APPROVAL', 'APPROVED', 'ISSUED', 'SENT'];

  function card(title) {
    var cards = document.querySelectorAll('.kpi-card');
    for (var i = 0; i < cards.length; i++) {
      var t = cards[i].querySelector('.kpi-title');
      if (t && t.textContent.trim().toLowerCase().indexOf(title) === 0) { return cards[i]; }
    }
    return null;
  }

  function setCard(el, value, caption, state) {
    if (!el) { return; }
    var v = el.querySelector('.kpi-value');
    var trend = el.querySelector('.kpi-trend');
    var spark = el.querySelector('.kpi-sparkline');
    if (v) { v.textContent = value; v.classList.toggle('kpi-value--muted', state !== 'ok'); }
    if (trend) { trend.textContent = caption; trend.classList.add('kpi-caption'); }
    if (spark) { spark.remove(); } // decorative sparkline carried no real data
  }

  async function load() {
    var ca = card("chiffre"), orders = card('commandes'), quotes = card('devis'), clients = card('nouveaux clients') || card('clients');
    [ca, orders, quotes, clients].forEach(function (c) { setCard(c, '…', 'Chargement…', 'loading'); });

    var results = await Promise.all([
      V.getJson('/api/v1/analytics/overview?currency=MAD'),
      V.getJson('/api/v1/quotes?limit=500'),
      V.getJson('/api/v1/crm/accounts?limit=500')
    ]);
    var ov = results[0], qs = results[1], acc = results[2];

    if (ov.ok && ov.data) {
      setCard(ca, V.money(ov.data.net_revenue_cents, ov.data.currency), 'CA net réservé (commandes confirmées − remboursements), MAD', 'ok');
      setCard(orders, String(ov.data.confirmed_orders_count), 'Commandes confirmées / expédiées / livrées', 'ok');
    } else {
      setCard(ca, '—', V.errorText(ov), 'error');
      setCard(orders, '—', V.errorText(ov), 'error');
    }
    if (qs.ok && Array.isArray(qs.data)) {
      var open = qs.data.filter(function (q) { return OPEN_QUOTE.indexOf(q.status) !== -1; }).length;
      setCard(quotes, String(open), 'Devis ouverts (brouillon → envoyés)', 'ok');
    } else {
      setCard(quotes, '—', V.errorText(qs), 'error');
    }
    if (acc.ok && Array.isArray(acc.data)) {
      setCard(clients, String(acc.data.length), 'Comptes clients enregistrés', 'ok');
      var title = clients && clients.querySelector('.kpi-title');
      if (title) { title.textContent = 'Clients'; }
    } else {
      setCard(clients, '—', V.errorText(acc), 'error');
    }

  }

  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', load); } else { load(); }
})();
