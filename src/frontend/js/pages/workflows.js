/* Selia — Workflows: durable executions, recovery of stuck runs, automation rules. */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const $ = (id) => document.getElementById(id);
  const TYPE = { CHECKOUT: 'Validation de commande', ORDER_FULFILLMENT: 'Exécution de commande', PAYMENT: 'Paiement', REFUND: 'Remboursement',
    QUOTE_APPROVAL: 'Approbation de devis', FOLLOW_UP: 'Relance', PROCUREMENT: 'Achat' };
  const RUN = ['PENDING', 'RUNNING', 'RETRYING', 'COMPENSATING'], FAIL = ['FAILED', 'DEAD_LETTER', 'COMPENSATED'];
  const label = (t) => TYPE[String(t || '').toUpperCase()] || String(t || '—').replace(/_/g, ' ').toLowerCase().replace(/^./, c => c.toUpperCase());

  function renderRules(rules, ok) {
    const tbody = $('ruleRows');
    if (!ok) { V.rowState(tbody, 4, 'error', 'Règles indisponibles.'); return; }
    tbody.innerHTML = rules.length ? rules.map(r => '<tr><td data-label=""><strong>' + V.esc(r.name) + '</strong></td>' +
      '<td data-label="Déclencheur"><code>' + V.esc(r.trigger_event) + '</code></td><td data-label="Action">' + V.esc(label(r.action_type)) + '</td>' +
      '<td data-label="Statut">' + V.pill(r.is_active ? 'ACTIVE' : 'INACTIVE') + '</td></tr>').join('')
      : '<tr><td colspan="4" class="data-state">Aucune règle d’automatisation.</td></tr>';
  }

  function init() {
    const list = L.mount({
      url: '/api/v1/workflows/executions', accountsUrl: false, lookups: { rules: '/api/v1/workflows/automations/rules' },
      cols: 6, dateField: 'created_at', noun: 'exécutions', empty: 'Aucune exécution de workflow.',
      onLoaded: (ctx) => renderRules(ctx.rules, ctx.rulesOk),
      chips: [['all', 'Toutes', null], ['run', 'En cours', RUN], ['done', 'Terminées', ['COMPLETED']], ['fail', 'Échecs', FAIL]],
      search: (w) => [w.workflow_type, w.current_step, w.correlation_id].join(' '),
      kpis: (rows) => L.kpi('grid', '', 'Exécutions', rows.length) + L.kpi('arrow', 'sand', 'En cours', rows.filter(w => RUN.indexOf(w.status) !== -1).length) +
        L.kpi('target', '', 'Terminées', rows.filter(w => w.status === 'COMPLETED').length) +
        L.kpi('calendar', 'terra', 'Échecs', rows.filter(w => FAIL.indexOf(w.status) !== -1).length),
      row: (w) => '<tr><td data-label=""><strong>' + V.esc(label(w.workflow_type)) + '</strong><span class="cell-sub">' + V.esc(String(w.correlation_id || w.id).slice(0, 24)) + '</span></td>' +
        '<td data-label="Étape en cours">' + V.esc(w.current_step || '—') + '</td>' +
        '<td data-label="Tentatives" class="num">' + V.esc((w.retry_count || 0) + ' / ' + (w.max_retries || 0)) + '</td>' +
        '<td data-label="Démarré">' + V.esc(V.ago(w.created_at)) + '</td><td data-label="Terminé">' + V.esc(w.completed_at ? V.date(w.completed_at) : '—') + '</td>' +
        '<td data-label="Statut">' + V.pill(w.status) + '</td></tr>'
    });
    $('btnResume').addEventListener('click', async () => {
      const btn = $('btnResume'); btn.disabled = true;
      const res = await V.getJson('/api/v1/workflows/recovery/resume', { method: 'POST' });
      btn.disabled = false;
      if (!res.ok) { window.SalesAI.showToast(res.status === 403 ? 'Votre rôle ne permet pas de relancer les workflows.' : 'Relance impossible : ' + V.errorText(res)); return; }
      const n = res.data && (res.data.resumed_count != null ? res.data.resumed_count : (res.data.resumed || []).length);
      window.SalesAI.showToast(n != null ? n + ' workflow(s) relancé(s).' : 'Relance demandée.');
      list.reload();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
