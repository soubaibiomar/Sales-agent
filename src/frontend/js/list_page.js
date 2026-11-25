/* Selia — shared controller for status-filtered list pages (Devis, Commandes).
 * SeliaList.mount({ url, accountsUrl, chips:[[key,label,statuses|null]], kpis(rows, names) -> html,
 *                   row(item, names) -> html, cols, search(item, names) -> string, dateField, noun }) */
(function () {
  'use strict';
  const V = window.SalesViews;
  const $ = (id) => document.getElementById(id);
  const PAGE = 8;

  function mount(cfg) {
    let items = [], names = new Map(), chip = cfg.chips[0][0], page = 1;

    function inYear(i) {
      if ($('yearSelect').value !== 'year') return true;
      return new Date(i[cfg.dateField]).getFullYear() === new Date().getFullYear();
    }
    function matches(i) {
      const def = cfg.chips.find(c => c[0] === chip);
      const q = ($('search').value || '').trim().toLowerCase();
      return inYear(i) && (!def[2] || def[2].indexOf(i.status) !== -1) && (!q || cfg.search(i, names).toLowerCase().indexOf(q) !== -1);
    }

    function render() {
      const scoped = items.filter(inYear);
      $('kpis').innerHTML = cfg.kpis(scoped, names);
      $('chips').innerHTML = cfg.chips.map(([key, label, statuses]) => {
        const n = scoped.filter(i => !statuses || statuses.indexOf(i.status) !== -1).length;
        return '<button type="button" class="chip" data-chip="' + key + '" aria-pressed="' + (key === chip) + '">' + V.esc(label) + ' (' + n + ')</button>';
      }).join('');
      const rows = items.filter(matches).sort((a, b) => new Date(b[cfg.dateField]) - new Date(a[cfg.dateField]));
      const pages = Math.max(1, Math.ceil(rows.length / PAGE));
      page = Math.min(page, pages);
      if (!rows.length) V.rowState($('rows'), cfg.cols, 'empty', items.length ? 'Aucun résultat pour ce filtre.' : 'Aucun élément pour le moment.');
      else $('rows').innerHTML = rows.slice((page - 1) * PAGE, page * PAGE).map(i => cfg.row(i, names)).join('');
      const from = rows.length ? (page - 1) * PAGE + 1 : 0, to = Math.min(rows.length, page * PAGE);
      let btns = '<button type="button" data-page="' + (page - 1) + '"' + (page <= 1 ? ' disabled' : '') + ' aria-label="Page précédente">‹</button>';
      for (let p = 1; p <= pages && p <= 9; p++) btns += '<button type="button" data-page="' + p + '"' + (p === page ? ' aria-current="page"' : '') + '>' + p + '</button>';
      btns += '<button type="button" data-page="' + (page + 1) + '"' + (page >= pages ? ' disabled' : '') + ' aria-label="Page suivante">›</button>';
      $('pager').innerHTML = '<span>Affichage ' + from + '–' + to + ' sur ' + rows.length + ' ' + cfg.noun + '</span><span class="pager-buttons">' + btns + '</span>';
    }

    async function load() {
      const [res, acc] = await Promise.all([V.getJson(cfg.url), V.getJson(cfg.accountsUrl || '/api/v1/crm/accounts?limit=500')]);
      if (!res.ok) { V.rowState($('rows'), cfg.cols, 'error', V.errorText(res)); $('kpis').innerHTML = ''; return; }
      items = V.list(res.data);
      names = new Map((acc.ok ? V.list(acc.data) : []).map(a => [a.id, a.name]));
      render();
    }

    $('chips').addEventListener('click', (e) => { const b = e.target.closest('[data-chip]'); if (b) { chip = b.getAttribute('data-chip'); page = 1; render(); } });
    $('pager').addEventListener('click', (e) => { const b = e.target.closest('[data-page]'); if (b && !b.disabled) { page = Number(b.getAttribute('data-page')); render(); } });
    $('search').addEventListener('input', () => { page = 1; render(); });
    $('yearSelect').addEventListener('change', () => { page = 1; render(); });
    load();
  }

  function kpi(icon, tone, label, value, extra) {
    return '<article class="kpi-card"><span class="kpi-icon' + (tone ? ' kpi-icon--' + tone : '') + '">' + window.SalesAI.icon(icon, 22) + '</span>' +
      '<div class="kpi-body"><span class="kpi-label">' + V.esc(label) + '</span><span class="kpi-number">' + value + '</span>' +
      (extra ? '<span class="kpi-delta">' + V.esc(extra) + '</span>' : '') + '</div></article>';
  }

  window.SeliaList = { mount: mount, kpi: kpi };
})();
