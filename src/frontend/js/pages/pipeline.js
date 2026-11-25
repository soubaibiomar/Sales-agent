/* Selia — Opportunités: pipeline board / list from the CRM API, stage moves through
 * PATCH /crm/opportunities/{id}/stage and creation through POST /crm/opportunities. */
(function () {
  'use strict';
  const V = window.SalesViews;
  const $ = (id) => document.getElementById(id);
  const COLS = [['DISCOVERY', 'Prospection'], ['QUALIFICATION', 'Qualification'], ['PROPOSAL', 'Proposition'], ['NEGOTIATION', 'Négociation'], ['CLOSED_WON', 'Gagnée']];
  let opps = [], names = new Map(), current = null;

  function render() {
    const open = opps.filter(o => o.stage !== 'CLOSED_LOST' && o.stage !== 'CLOSED_WON').length;
    $('oppCount').textContent = '(' + open + ')';
    $('board').innerHTML = COLS.map(([key, label]) => {
      const items = opps.filter(o => o.stage === key);
      const total = items.reduce((n, o) => n + (o.amount_cents || 0), 0);
      return '<div class="board-col' + (key === 'CLOSED_WON' ? ' board-col--won' : '') + '"><h2>' + V.esc(label) + ' <span class="n">(' + items.length + ')</span></h2>' +
        '<p class="board-total">' + V.esc(V.money(total, 'MAD')) + '</p>' +
        (items.length ? items.map(o => '<button type="button" class="deal" data-opp="' + V.esc(o.id) + '"><strong>' + V.esc(o.title) + '</strong>' +
          '<span class="cell-sub">' + V.esc(names.get(o.account_id) || '') + '</span><span class="deal-amount">' + V.esc(V.money(o.amount_cents, o.currency)) + '</span></button>').join('')
          : '<p class="board-empty">Aucune opportunité.</p>') + '</div>';
    }).join('');
    $('oppRows').innerHTML = opps.length ? opps.map(o => '<tr><td data-label=""><button type="button" class="deal-link" data-opp="' + V.esc(o.id) + '"><strong>' + V.esc(o.title) + '</strong></button></td>' +
      '<td data-label="Client">' + V.esc(names.get(o.account_id) || '—') + '</td><td data-label="Étape">' + V.pill(o.stage) + '</td>' +
      '<td data-label="Montant (MAD)" class="num">' + V.esc(V.money(o.amount_cents, '').trim()) + '</td><td data-label="Probabilité" class="num">' + V.esc(o.probability_percent) + ' %</td></tr>').join('')
      : '<tr><td colspan="5" class="data-state">Aucune opportunité.</td></tr>';
  }

  async function load() {
    const [o, a] = await Promise.all([V.getJson('/api/v1/crm/opportunities?limit=500'), V.getJson('/api/v1/crm/accounts?limit=500')]);
    if (!o.ok) { $('board').innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(o)) + '</p>'; return; }
    opps = V.list(o.data);
    const accounts = a.ok ? V.list(a.data) : [];
    names = new Map(accounts.map(x => [x.id, x.name]));
    $('oAccount').innerHTML = '<option value="">Choisir un client…</option>' + accounts.map(x => '<option value="' + V.esc(x.id) + '">' + V.esc(x.name) + '</option>').join('');
    render();
  }

  function openDeal(id) {
    current = opps.find(o => o.id === id);
    if (!current) return;
    $('dealTitle').textContent = current.title;
    $('dealMeta').textContent = (names.get(current.account_id) || '') + ' • ' + V.money(current.amount_cents, current.currency) + ' • ' + V.statusLabel(current.stage);
    $('dealStage').value = current.stage;
    $('lostReasonField').hidden = current.stage !== 'CLOSED_LOST';
    $('dealError').textContent = '';
    $('dealQuote').href = 'quote_builder.html?account=' + encodeURIComponent(current.account_id || '');
    window.SalesAI.openModal('dealModal');
  }

  async function saveStage(e) {
    e.preventDefault();
    if (!current) return;
    const stage = $('dealStage').value;
    if (stage === current.stage) { $('dealModal').hidden = true; return; }
    const res = await V.getJson('/api/v1/crm/opportunities/' + encodeURIComponent(current.id) + '/stage', {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stage: stage, lost_reason: stage === 'CLOSED_LOST' ? ($('dealLost').value.trim() || null) : null })
    });
    if (!res.ok) { $('dealError').textContent = res.status === 403 ? "Votre rôle ne permet pas de modifier l'étape." : (res.data && res.data.detail) || V.errorText(res); return; }
    $('dealModal').hidden = true;
    window.SalesAI.showToast('« ' + current.title + ' » déplacée vers ' + V.statusLabel(stage) + '.');
    load();
  }

  async function create(e) {
    e.preventDefault();
    const err = $('oppFormError');
    const title = $('oTitle').value.trim(), account = $('oAccount').value;
    if (!title || !account) { err.textContent = "L'intitulé et le client sont obligatoires."; return; }
    const close = $('oClose').value;
    const res = await V.getJson('/api/v1/crm/opportunities', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title, account_id: account, stage: $('oStage').value, currency: 'MAD',
        amount_cents: Math.round(Number($('oAmount').value || 0) * 100), probability_percent: Math.min(100, Math.max(0, Number($('oProb').value || 0))),
        expected_close_date: close ? new Date(close + 'T12:00:00').toISOString() : null })
    });
    if (!res.ok) { err.textContent = res.status === 403 ? "Votre rôle ne permet pas de créer une opportunité." : 'Création impossible : ' + V.errorText(res); return; }
    $('oppModal').hidden = true; e.target.reset();
    window.SalesAI.showToast('Opportunité « ' + title + ' » créée.');
    load();
  }

  function init() {
    document.addEventListener('click', (e) => { const d = e.target.closest('[data-opp]'); if (d) openDeal(d.getAttribute('data-opp')); });
    document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => {
      const list = b.getAttribute('data-view') === 'list';
      document.querySelectorAll('[data-view]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
      $('board').hidden = list; $('listView').hidden = !list;
    }));
    $('dealStage').addEventListener('change', () => { $('lostReasonField').hidden = $('dealStage').value !== 'CLOSED_LOST'; });
    $('dealForm').addEventListener('submit', saveStage);
    $('oppForm').addEventListener('submit', create);
    $('btnNewOpp').addEventListener('click', () => window.SalesAI.openModal('oppModal'));
    if (location.hash === '#nouveau') window.SalesAI.openModal('oppModal');
    window.addEventListener('hashchange', () => { if (location.hash === '#nouveau') { window.SalesAI.openModal('oppModal'); } });
    load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
