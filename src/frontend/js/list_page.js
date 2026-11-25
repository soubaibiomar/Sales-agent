/* Selia — shared controller for status-filtered list pages.
 * SeliaList.mount({
 *   url,                         list endpoint
 *   accountsUrl,                 (optional) names lookup, default CRM accounts; false to skip
 *   lookups: {key: url},         (optional) extra lists, passed to callbacks as ctx[key]
 *   listKey,                     (optional) key when the endpoint wraps the array
 *   transform(items, ctx),       (optional) enrich items (e.g. computed status)
 *   statusOf(item),              (optional) status used by chips, default item.status
 *   chips: [[key, label, statuses|null]],
 *   kpis(rows, names, ctx) -> html, row(item, names, ctx) -> html, cols,
 *   search(item, names, ctx) -> string, dateField, noun, empty, onLoaded(ctx)
 * })
 * Page markup ids: kpis, chips, search, yearSelect (optional), rows, pager. */
(function () {
  'use strict';
  const V = window.SalesViews;
  const $ = (id) => document.getElementById(id);
  const PAGE = 8;

  function mount(cfg) {
    let items = [], names = new Map(), ctx = {}, chip = cfg.chips[0][0], page = 1;
    const statusOf = cfg.statusOf || (i => i.status);
    const year = $('yearSelect');

    function inYear(i) {
      if (!year || year.value !== 'year' || !cfg.dateField) return true;
      return new Date(i[cfg.dateField]).getFullYear() === new Date().getFullYear();
    }
    function matches(i) {
      const def = cfg.chips.find(c => c[0] === chip);
      const q = (($('search') || {}).value || '').trim().toLowerCase();
      return inYear(i) && (!def[2] || def[2].indexOf(statusOf(i)) !== -1) &&
        (!q || String(cfg.search ? cfg.search(i, names, ctx) : '').toLowerCase().indexOf(q) !== -1);
    }

    function render() {
      const scoped = items.filter(inYear);
      if ($('kpis') && cfg.kpis) $('kpis').innerHTML = cfg.kpis(scoped, names, ctx);
      $('chips').innerHTML = cfg.chips.map(([key, label, statuses]) => {
        const n = scoped.filter(i => !statuses || statuses.indexOf(statusOf(i)) !== -1).length;
        return '<button type="button" class="chip" data-chip="' + key + '" aria-pressed="' + (key === chip) + '">' + V.esc(label) + ' (' + n + ')</button>';
      }).join('');
      const rows = items.filter(matches);
      if (cfg.dateField) rows.sort((a, b) => new Date(b[cfg.dateField]) - new Date(a[cfg.dateField]));
      const pages = Math.max(1, Math.ceil(rows.length / PAGE));
      page = Math.min(page, pages);
      if (!rows.length) V.rowState($('rows'), cfg.cols, 'empty', items.length ? 'Aucun résultat pour ce filtre.' : (cfg.empty || 'Aucun élément pour le moment.'));
      else $('rows').innerHTML = rows.slice((page - 1) * PAGE, page * PAGE).map(i => cfg.row(i, names, ctx)).join('');
      const from = rows.length ? (page - 1) * PAGE + 1 : 0, to = Math.min(rows.length, page * PAGE);
      let btns = '<button type="button" data-page="' + (page - 1) + '"' + (page <= 1 ? ' disabled' : '') + ' aria-label="Page précédente">‹</button>';
      for (let p = 1; p <= pages && p <= 9; p++) btns += '<button type="button" data-page="' + p + '"' + (p === page ? ' aria-current="page"' : '') + '>' + p + '</button>';
      btns += '<button type="button" data-page="' + (page + 1) + '"' + (page >= pages ? ' disabled' : '') + ' aria-label="Page suivante">›</button>';
      $('pager').innerHTML = '<span>Affichage ' + from + '–' + to + ' sur ' + rows.length + ' ' + cfg.noun + '</span><span class="pager-buttons">' + btns + '</span>';
    }

    async function load() {
      const lookupKeys = Object.keys(cfg.lookups || {});
      const calls = [V.getJson(cfg.url), cfg.accountsUrl === false ? Promise.resolve({ ok: false }) : V.getJson(cfg.accountsUrl || '/api/v1/crm/accounts?limit=500')]
        .concat(lookupKeys.map(k => V.getJson(cfg.lookups[k])));
      const [res, acc, ...extra] = await Promise.all(calls);
      if (!res.ok) { V.rowState($('rows'), cfg.cols, 'error', V.errorText(res)); if ($('kpis')) $('kpis').innerHTML = ''; return; }
      names = new Map((acc.ok ? V.list(acc.data) : []).map(a => [a.id, a.name]));
      ctx = { names: names };
      lookupKeys.forEach((k, i) => { ctx[k] = extra[i].ok ? V.list(extra[i].data) : []; ctx[k + 'Ok'] = extra[i].ok; });
      items = V.list(res.data, cfg.listKey);
      if (cfg.transform) items = cfg.transform(items, ctx) || items;
      if (cfg.onLoaded) cfg.onLoaded(ctx, items);
      render();
    }

    $('chips').addEventListener('click', (e) => { const b = e.target.closest('[data-chip]'); if (b) { chip = b.getAttribute('data-chip'); page = 1; render(); } });
    $('pager').addEventListener('click', (e) => { const b = e.target.closest('[data-page]'); if (b && !b.disabled) { page = Number(b.getAttribute('data-page')); render(); } });
    if ($('search')) $('search').addEventListener('input', () => { page = 1; render(); });
    if (year) year.addEventListener('change', () => { page = 1; render(); });
    load();
    return { reload: load };
  }

  function kpi(icon, tone, label, value, extra) {
    return '<article class="kpi-card"><span class="kpi-icon' + (tone ? ' kpi-icon--' + tone : '') + '">' + window.SalesAI.icon(icon, 22) + '</span>' +
      '<div class="kpi-body"><span class="kpi-label">' + V.esc(label) + '</span><span class="kpi-number">' + value + '</span>' +
      (extra ? '<span class="kpi-delta">' + V.esc(extra) + '</span>' : '') + '</div></article>';
  }

  /** Small helper for create dialogs: posts JSON, reports errors in the form, toasts success. */
  async function submitForm(form, url, payload, okMessage, onDone, method) {
    const err = form.querySelector('.form-error');
    const btn = form.querySelector('[type=submit]');
    if (btn) btn.disabled = true;
    const res = await V.getJson(url, { method: method || 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (btn) btn.disabled = false;
    if (!res.ok) {
      const detail = res.data && (typeof res.data.detail === 'string' ? res.data.detail : null);
      if (err) err.textContent = res.status === 403 ? "Votre rôle ne permet pas cette action." : (detail || V.errorText(res));
      return null;
    }
    const backdrop = form.closest('.modal-backdrop');
    if (backdrop) backdrop.hidden = true;
    form.reset();
    if (err) err.textContent = '';
    window.SalesAI.showToast(okMessage);
    if (onDone) onDone(res.data);
    return res.data;
  }

  window.SeliaList = { mount: mount, kpi: kpi, submitForm: submitForm };
})();
