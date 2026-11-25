/* Selia — Analyses: revenue (daily sales read-model), orders, clients and receivables
 * (unpaid invoices). Trends compare the chosen range with the previous one. */
(function () {
  'use strict';
  const V = window.SalesViews, UI = window.SalesAI, Charts = window.SeliaCharts;
  const $ = (id) => document.getElementById(id);
  const DAY = 86400000;
  let d = null;

  function range() {
    const v = $('rangeSelect').value, now = Date.now();
    if (v === 'year') { const s = new Date(new Date().getFullYear(), 0, 1).getTime(); return [s, now + DAY, s - (now - s)]; }
    const n = Number(v) * DAY; return [now - n, now + DAY, now - 2 * n];
  }
  const within = (t, a, b) => { const x = new Date(t).getTime(); return x >= a && x < b; };

  function kpi(icon, tone, label, value, unit, delta) {
    return '<article class="kpi-card"><span class="kpi-icon' + (tone ? ' kpi-icon--' + tone : '') + '">' + UI.icon(icon, 22) + '</span><div class="kpi-body">' +
      '<span class="kpi-label">' + V.esc(label) + '</span><span class="kpi-number">' + V.esc(value) + (unit ? '<small>' + V.esc(unit) + '</small>' : '') + '</span>' +
      (delta ? '<span class="kpi-delta ' + (delta.up ? 'up' : 'down') + '">' + (delta.up ? '↑ ' : '↓ ') + V.esc(delta.text) + '</span>' : '') + '</div></article>';
  }

  function render() {
    const [a, b, p] = range();
    const rev = (x, y) => d.sales.filter(r => within(r.date, x, y)).reduce((n, r) => n + (r.net_revenue_cents || 0), 0);
    const live = d.orders.filter(o => o.status !== 'CANCELLED');
    const ord = (x, y) => live.filter(o => within(o.created_at, x, y)).length;
    const cli = (t) => d.accounts.filter(c => new Date(c.created_at).getTime() < t).length;
    const unpaid = d.invoices.filter(i => !i.paid_at && ['CANCELLED', 'VOID', 'VOIDED', 'CREDITED', 'DRAFT'].indexOf(String(i.status).toUpperCase()) === -1)
      .reduce((n, i) => n + (i.grand_total_cents || 0), 0);
    const dr = V.delta(rev(a, b), rev(p, a)), dord = V.delta(ord(a, b), ord(p, a)), dcli = V.delta(cli(b), cli(a));
    $('kpis').innerHTML = (d.salesOk ? kpi('chart', '', "Chiffre d'affaires", V.amount(rev(a, b)), 'MAD', dr) : kpi('chart', '', "Chiffre d'affaires", '—', '', null)) +
      kpi('cart', 'terra', 'Commandes', ord(a, b).toLocaleString('fr-FR'), '', dord) +
      kpi('users', '', 'Clients', d.accounts.length.toLocaleString('fr-FR'), '', dcli) +
      (d.invoicesOk ? kpi('doc', 'sand', 'Créances', V.amount(unpaid), 'MAD', null) : kpi('doc', 'sand', 'Créances', '—', '', null));
    const tile = (dl, label) => '<div class="trend-tile"><strong class="' + (dl ? (dl.up ? 'up' : 'down') : '') + '">' + (dl ? (dl.up ? '↑ ' : '↓ ') + V.esc(dl.text) : '—') + '</strong><span>' + label + '</span></div>';
    $('trends').innerHTML = tile(dr, 'CA') + tile(dord, 'Commandes') + tile(dcli, 'Clients');
    $('trendCaption').textContent = 'vs période précédente';

    // 12 monthly points ending this month.
    const now = new Date(), months = [];
    for (let i = 11; i >= 0; i--) { const m = new Date(now.getFullYear(), now.getMonth() - i, 1); months.push({ y: m.getFullYear(), m: m.getMonth(), v: 0, label: m.toLocaleDateString('fr-FR', { month: 'short' }).replace('.', '') }); }
    d.sales.forEach(r => { const t = new Date(r.date); const b = months.find(x => x.y === t.getFullYear() && x.m === t.getMonth()); if (b) b.v += r.net_revenue_cents || 0; });
    if (d.salesOk) Charts.line($('revenueChart'), { labels: months.map(x => x.label.charAt(0).toUpperCase() + x.label.slice(1)), values: months.map(x => x.v / 100),
      tooltip: v => Math.round(v).toLocaleString('fr-FR') + ' MAD', ariaLabel: "Chiffre d'affaires mensuel" });
    else $('revenueChart').innerHTML = '<p class="data-state data-state--error">' + V.esc(V.errorText(d.salesRes)) + '</p>';

    // Split by client over the selected range (orders).
    const byClient = new Map();
    live.filter(o => within(o.created_at, a, b)).forEach(o => byClient.set(o.account_id || '?', (byClient.get(o.account_id || '?') || 0) + (o.grand_total_cents || 0)));
    const sorted = Array.from(byClient.entries()).sort((x, y) => y[1] - x[1]);
    const total = sorted.reduce((n, x) => n + x[1], 0);
    const top = sorted.slice(0, 3), rest = sorted.slice(3).reduce((n, x) => n + x[1], 0);
    const segs = top.map(([id, v], i) => ({ label: d.names.get(id) || 'Client', value: v, color: ['#5D7A2D', '#CF6639', '#EBCBAA'][i] }));
    if (rest) segs.push({ label: 'Autres', value: rest, color: '#E9DCCD' });
    Charts.donut($('salesDonut'), { segments: segs, center: total ? V.amount(total) : '0', sub: 'MAD', centerSize: 17, emptyText: total ? '' : 'Aucune vente sur la période.' });
    $('clientBars').innerHTML = sorted.length ? sorted.slice(0, 5).map(([id, v], i) =>
      '<li><span class="name">' + V.esc(d.names.get(id) || 'Client') + '</span><span class="bar-track"><span class="bar-fill t' + (i % 3) + '" style="width:' +
      Math.max(3, Math.round(100 * v / sorted[0][1])) + '%"></span></span><span class="amt">' + V.esc(V.money(v, 'MAD')) + '</span></li>').join('')
      : '<li class="data-state">Aucune vente sur la période.</li>';
  }

  async function load() {
    const [sales, orders, accounts, invoices] = await Promise.all([
      V.getJson('/api/v1/analytics/sales?currency=MAD&days=365'), V.getJson('/api/v1/orders'),
      V.getJson('/api/v1/crm/accounts?limit=500'), V.getJson('/api/v1/invoices')]);
    const acc = accounts.ok ? V.list(accounts.data) : [];
    d = { sales: sales.ok ? V.list(sales.data, 'revenue_trend') : [], salesOk: sales.ok, salesRes: sales,
      orders: orders.ok ? V.list(orders.data) : [], accounts: acc, names: new Map(acc.map(x => [x.id, x.name])),
      invoices: invoices.ok ? V.list(invoices.data) : [], invoicesOk: invoices.ok };
    render();
  }

  function init() { $('rangeSelect').addEventListener('change', () => d && render()); load(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
