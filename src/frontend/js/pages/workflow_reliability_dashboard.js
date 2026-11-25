/* Selia — Fiabilité & alertes: real dependency checks (/observability/health), alerts with
 * acknowledge/resolve, and recent traces. */
(function () {
  'use strict';
  const V = window.SalesViews, UI = window.SalesAI;
  const $ = (id) => document.getElementById(id);
  const DEP = { database: 'Base de données (PostgreSQL)', ollama: 'Modèles IA (Ollama)' };
  const SEV = { CRITICAL: ['Critique', 'danger'], HIGH: ['Haute', 'danger'], WARNING: ['Avertissement', 'warn'], MEDIUM: ['Moyenne', 'warn'], INFO: ['Info', 'info'], LOW: ['Basse', 'neutral'] };
  const AST = { ACTIVE: ['Active', 'danger'], FIRING: ['Active', 'danger'], ACKNOWLEDGED: ['Prise en compte', 'warn'], RESOLVED: ['Résolue', 'ok'] };
  const kpi = (icon, tone, label, value) => '<article class="kpi-card"><span class="kpi-icon' + (tone ? ' kpi-icon--' + tone : '') + '">' + UI.icon(icon, 22) +
    '</span><div class="kpi-body"><span class="kpi-label">' + V.esc(label) + '</span><span class="kpi-number">' + value + '</span></div></article>';

  async function load() {
    const [h, a, t] = await Promise.all([V.getJson('/api/v1/observability/health'), V.getJson('/api/v1/observability/alerts'), V.getJson('/api/v1/observability/traces?limit=20')]);
    const deps = h.ok ? (h.data.dependencies || {}) : {};
    const alerts = a.ok ? V.list(a.data, 'alerts') : [];
    const open = alerts.filter(x => x.status !== 'RESOLVED');
    $('kpis').innerHTML = kpi('target', h.ok && h.data.status === 'READY' ? '' : 'terra', 'Service', h.ok ? V.pill(h.data.status === 'READY' ? 'Disponible' : 'Dégradé', h.data.status === 'READY' ? 'ok' : 'danger') : '—') +
      kpi('calendar', 'terra', 'Alertes ouvertes', open.length) + kpi('grid', 'sand', 'Dépendances en panne', Object.values(deps).filter(d => d.status !== 'UP').length) +
      kpi('chart', '', 'Traces récentes', t.ok ? (t.data.count || 0) : '—');
    $('checkedAt').textContent = h.ok ? 'Vérifié ' + V.ago(h.data.checked_at).toLowerCase() : '';
    $('deps').innerHTML = h.ok ? Object.keys(deps).map(k => {
      const d = deps[k];
      return '<div class="dep"><strong>' + V.esc(DEP[k] || k) + V.pill(d.status === 'UP' ? 'Opérationnel' : 'Indisponible', d.status === 'UP' ? 'ok' : (d.required ? 'danger' : 'warn')) + '</strong>' +
        '<span class="cell-sub">Latence ' + V.esc(d.latency_ms) + ' ms' + (d.required ? ' · requis' : ' · optionnel') + (k === 'database' ? (d.rls_enforced ? ' · RLS appliquée' : ' · RLS NON appliquée') : '') + '</span>' +
        (d.error ? '<span class="cell-sub">Erreur : ' + V.esc(d.error) + '</span>' : '') + '</div>';
    }).join('') : '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(h)) + '</p>';
    if (!a.ok) V.rowState($('alertRows'), 6, 'error', V.errorText(a));
    else $('alertRows').innerHTML = alerts.length ? alerts.map(x => {
      const sev = SEV[String(x.severity).toUpperCase()] || [x.severity, 'neutral'], st = AST[String(x.status).toUpperCase()] || [x.status, 'neutral'];
      const actions = x.status === 'RESOLVED' ? '' : (x.status !== 'ACKNOWLEDGED' ? '<button type="button" class="btn btn-outline btn-sm" data-ack="' + V.esc(x.id) + '">Prendre en compte</button> ' : '') +
        '<button type="button" class="btn btn-soft-green btn-sm" data-resolve="' + V.esc(x.id) + '">Résoudre</button>';
      return '<tr><td data-label=""><strong>' + V.esc(x.title) + '</strong><span class="cell-sub">' + V.esc(x.description || '') + '</span></td>' +
        '<td data-label="Source">' + V.esc(x.source || '—') + '</td><td data-label="Gravité">' + V.pill(sev[0], sev[1]) + '</td>' +
        '<td data-label="Depuis">' + V.esc(V.ago(x.created_at)) + '</td><td data-label="Statut">' + V.pill(st[0], st[1]) + '</td><td data-label="">' + actions + '</td></tr>';
    }).join('') : '<tr><td colspan="6" class="data-state">Aucune alerte.</td></tr>';
    const traces = t.ok ? V.list(t.data, 'traces') : [];
    if (!t.ok) V.rowState($('traceRows'), 5, 'error', V.errorText(t));
    else $('traceRows').innerHTML = traces.length ? traces.map(s => '<tr><td data-label=""><code>' + V.esc(s.operation) + '</code></td>' +
      '<td data-label="Composant">' + V.esc(s.component) + '</td><td data-label="Durée" class="num">' + V.esc(s.duration_ms) + ' ms</td>' +
      '<td data-label="Statut">' + V.pill(s.status === 'OK' ? 'OK' : s.status, s.status === 'OK' ? 'ok' : 'danger') + '</td><td data-label="Quand">' + V.esc(V.ago(s.timestamp)) + '</td></tr>').join('')
      : '<tr><td colspan="5" class="data-state">Aucune trace récente.</td></tr>';
  }

  async function act(id, verb) {
    const res = await V.getJson('/api/v1/observability/alerts/' + encodeURIComponent(id) + '/' + verb, { method: 'POST' });
    if (!res.ok) { UI.showToast('Action impossible : ' + V.errorText(res)); return; }
    UI.showToast(verb === 'resolve' ? 'Alerte résolue.' : 'Alerte prise en compte.');
    load();
  }

  function init() {
    $('alertRows').addEventListener('click', (e) => {
      const ack = e.target.closest('[data-ack]'), res = e.target.closest('[data-resolve]');
      if (ack) act(ack.getAttribute('data-ack'), 'acknowledge');
      if (res) act(res.getAttribute('data-resolve'), 'resolve');
    });
    $('btnRefresh').addEventListener('click', load);
    load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
