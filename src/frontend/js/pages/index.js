/* Selia — Tableau de bord. Every figure comes from the API; trends compare the selected
 * period with the previous one of equal length and are omitted when not computable. */
(function () {
  'use strict';
  const V = window.SalesViews, UI = window.SalesAI, Charts = window.SeliaCharts;
  const $ = (id) => document.getElementById(id);
  const DAY = 86400000;
  const OPEN_QUOTES = ['DRAFT', 'PRICED', 'PENDING_APPROVAL', 'APPROVED', 'ISSUED', 'SENT'];
  const OPEN_STAGES = ['DISCOVERY', 'QUALIFICATION', 'PROPOSAL', 'NEGOTIATION'];
  let data = null;

  function kpi(icon, tone, label, value, unit, delta, caption) {
    const d = delta ? '<span class="kpi-delta ' + (delta.up ? 'up' : 'down') + '">' + (delta.up ? '↑' : '↓') + ' ' + V.esc(delta.text) + '</span>'
      : (caption ? '<span class="kpi-delta">' + V.esc(caption) + '</span>' : '');
    return '<article class="kpi-card"><span class="kpi-icon' + (tone ? ' kpi-icon--' + tone : '') + '">' + UI.icon(icon, 22) + '</span>' +
      '<div class="kpi-body"><span class="kpi-label">' + V.esc(label) + '</span><span class="kpi-number">' + V.esc(value) +
      (unit ? '<small>' + V.esc(unit) + '</small>' : '') + '</span>' + d + '</div></article>';
  }

  function since(items, field, from, to) {
    return items.filter(i => { const t = new Date(i[field]).getTime(); return t >= from && t < to; });
  }

  function renderKpis() {
    const days = Number($('periodSelect').value), now = Date.now(), start = now - days * DAY, prevStart = start - days * DAY;
    const host = $('kpis');
    const cards = [];
    // Clients: total now vs total at the start of the period.
    if (data.accounts.ok) {
      const acc = data.accounts.list;
      const before = acc.filter(a => new Date(a.created_at).getTime() < start).length;
      cards.push(kpi('users', '', 'Clients', acc.length.toLocaleString('fr-FR'), '', V.delta(acc.length, before)));
    } else cards.push(kpi('users', '', 'Clients', '—', '', null, V.errorText(data.accounts)));
    // Open opportunities with pipeline value.
    if (data.pipeline.ok) {
      const st = data.pipeline.data.stages || {};
      const open = OPEN_STAGES.reduce((n, s) => n + ((st[s] || {}).count || 0), 0);
      const value = OPEN_STAGES.reduce((n, s) => n + ((st[s] || {}).total_cents || 0), 0);
      cards.push(kpi('target', 'terra', 'Opportunités', open.toLocaleString('fr-FR'), '', null, V.amount(value) + ' MAD en cours'));
    } else cards.push(kpi('target', 'terra', 'Opportunités', '—', '', null, V.errorText(data.pipeline)));
    // Revenue (net, booked) for the period vs the previous period.
    if (data.sales.ok) {
      const ts = data.sales.list;
      const sum = (from, to) => ts.filter(r => { const t = new Date(r.date).getTime(); return t >= from && t < to; })
        .reduce((n, r) => n + (r.net_revenue_cents || 0), 0);
      const cur = sum(start, now + DAY), prev = sum(prevStart, start);
      cards.push(kpi('chart', '', 'CA (MAD)', V.amount(cur), '', V.delta(cur, prev)));
    } else cards.push(kpi('chart', '', 'CA (MAD)', '—', '', null, V.errorText(data.sales)));
    // Open quotes.
    if (data.quotes.ok) {
      const q = data.quotes.list;
      const open = q.filter(x => OPEN_QUOTES.indexOf(x.status) !== -1).length;
      const created = since(q, 'created_at', start, now + DAY).length, prev = since(q, 'created_at', prevStart, start).length;
      cards.push(kpi('doc', 'sand', 'Devis en cours', open.toLocaleString('fr-FR'), '', V.delta(created, prev),
        created + ' créé' + (created > 1 ? 's' : '') + ' sur la période'));
    } else cards.push(kpi('doc', 'sand', 'Devis en cours', '—', '', null, V.errorText(data.quotes)));
    host.innerHTML = cards.join('');
  }

  function renderRevenue() {
    const host = $('revenueChart');
    if (!data.sales.ok) { host.innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(data.sales)) + '</p>'; return; }
    const byMonth = $('granularity').value === 'month';
    const buckets = new Map();
    const now = new Date();
    if (byMonth) {
      for (let i = 5; i >= 0; i--) {
        const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
        buckets.set(d.getFullYear() + '-' + d.getMonth(), { label: d.toLocaleDateString('fr-FR', { month: 'short' }).replace('.', ''), v: 0 });
      }
    } else {
      for (let i = 11; i >= 0; i--) {
        const d = new Date(now.getTime() - i * 7 * DAY);
        buckets.set('w' + i, { label: d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' }), v: 0, from: d.getTime() - 7 * DAY, to: d.getTime() });
      }
    }
    data.sales.list.forEach(r => {
      const d = new Date(r.date);
      if (byMonth) { const b = buckets.get(d.getFullYear() + '-' + d.getMonth()); if (b) b.v += r.net_revenue_cents || 0; }
      else buckets.forEach(b => { if (d.getTime() > b.from && d.getTime() <= b.to) b.v += r.net_revenue_cents || 0; });
    });
    const rows = Array.from(buckets.values());
    Charts.line(host, { labels: rows.map(r => r.label.charAt(0).toUpperCase() + r.label.slice(1)), values: rows.map(r => r.v / 100),
      ariaLabel: "Évolution du chiffre d'affaires", tooltip: v => Math.round(v).toLocaleString('fr-FR') + ' MAD' });
  }

  function renderDonut() {
    const host = $('oppDonut');
    if (!data.pipeline.ok) { host.innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(data.pipeline)) + '</p>'; return; }
    const st = data.pipeline.data.stages || {};
    const c = (s) => (st[s] || {}).count || 0;
    const open = OPEN_STAGES.reduce((n, s) => n + c(s), 0);
    Charts.donut(host, {
      center: String(open), sub: 'opportunités', emptyText: open ? '' : 'Aucune opportunité ouverte.',
      segments: [
        { label: 'Négociation', value: c('NEGOTIATION'), color: '#5D7A2D' },
        { label: 'Proposition', value: c('PROPOSAL'), color: '#CF6639' },
        { label: 'Qualification', value: c('QUALIFICATION'), color: '#EBCBAA' },
        { label: 'Prospection', value: c('DISCOVERY'), color: '#E9DCCD' }
      ]
    });
  }

  function renderActivity() {
    const host = $('activityFeed');
    const items = [];
    const names = new Map((data.accounts.list || []).map(a => [a.id, a.name]));
    if (data.accounts.ok) data.accounts.list.forEach(a => items.push({ t: a.created_at, icon: 'userPlus', tone: '', title: 'Nouveau client ajouté', sub: a.name, href: 'clients.html' }));
    if (data.orders.ok) data.orders.list.forEach(o => items.push({ t: o.created_at, icon: 'cart', tone: 'terra', title: 'Commande ' + V.statusLabel(o.status).toLowerCase(),
      sub: o.order_number + ' • ' + V.money(o.grand_total_cents, o.currency), href: 'orders.html' }));
    if (data.quotes.ok) data.quotes.list.forEach(q => items.push({ t: q.created_at, icon: 'doc', tone: '', title: 'Devis créé',
      sub: q.quote_number + ' • ' + (names.get(q.account_id) || '') + (q.grand_total_cents ? ' • ' + V.money(q.grand_total_cents, q.currency) : ''), href: 'quotes.html' }));
    items.sort((a, b) => new Date(b.t) - new Date(a.t));
    host.innerHTML = items.length ? items.slice(0, 5).map(i =>
      '<li><span class="feed-icon' + (i.tone ? ' feed-icon--' + i.tone : '') + '">' + UI.icon(i.icon, 18) + '</span>' +
      '<a class="feed-main" href="' + i.href + '"><strong>' + V.esc(i.title) + '</strong><span>' + V.esc(i.sub) + '</span></a>' +
      '<span class="feed-time">' + V.esc(V.ago(i.t)) + '</span></li>').join('')
      : '<li class="data-state">Aucune activité récente.</li>';
  }

  function renderTopClients() {
    const host = $('topClients');
    if (!data.orders.ok) { host.innerHTML = '<li class="data-state data-state--error" role="alert">' + V.esc(V.errorText(data.orders)) + '</li>'; return; }
    const names = new Map((data.accounts.list || []).map(a => [a.id, a.name]));
    const totals = new Map();
    data.orders.list.filter(o => o.status !== 'CANCELLED' && o.account_id).forEach(o => totals.set(o.account_id, (totals.get(o.account_id) || 0) + (o.grand_total_cents || 0)));
    const top = Array.from(totals.entries()).sort((a, b) => b[1] - a[1]).slice(0, 5);
    const max = top.length ? top[0][1] : 1;
    host.innerHTML = top.length ? top.map(([id, cents], i) =>
      '<li><span class="rank">' + (i + 1) + '</span><div class="feed-main"><span class="top-row"><strong>' + V.esc(names.get(id) || 'Client') +
      '</strong><span class="top-amount">' + V.esc(V.money(cents, 'MAD')) + '</span></span><span class="bar-track"><span class="bar-fill" style="width:' +
      Math.max(4, Math.round(100 * cents / max)) + '%"></span></span></div></li>').join('')
      : '<li class="data-state">Aucune commande enregistrée.</li>';
  }

  async function load() {
    const days = 400; // enough for 12 months of KPI comparison and the 6-month chart
    const [accounts, pipeline, quotes, orders, sales] = await Promise.all([
      V.getJson('/api/v1/crm/accounts?limit=500'), V.getJson('/api/v1/crm/pipeline'), V.getJson('/api/v1/quotes?limit=500'),
      V.getJson('/api/v1/orders'), V.getJson('/api/v1/analytics/sales?currency=MAD&days=365')
    ]);
    accounts.list = accounts.ok ? V.list(accounts.data) : [];
    quotes.list = quotes.ok ? V.list(quotes.data) : [];
    orders.list = orders.ok ? V.list(orders.data) : [];
    sales.list = sales.ok ? V.list(sales.data, 'revenue_trend') : [];
    data = { accounts, pipeline, quotes, orders, sales, days };
    renderKpis(); renderRevenue(); renderDonut(); renderActivity(); renderTopClients();
  }

  function init() {
    $('kpis').innerHTML = '<p class="data-state" role="status">Chargement des indicateurs…</p>';
    $('periodSelect').addEventListener('change', () => data && renderKpis());
    $('granularity').addEventListener('change', () => data && renderRevenue());
    load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
