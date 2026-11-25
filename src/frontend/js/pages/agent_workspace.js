/* Selia — Espace agents IA: role catalogue (/api/v1/agents) and recent activity. */
(function () {
  'use strict';
  const V = window.SalesViews, UI = window.SalesAI;
  const $ = (id) => document.getElementById(id);
  const GROUP = { FRONT_DOOR: 'Accueil', SUPERVISION: 'Supervision', INTERACTIVE: 'Spécialistes', INTERACTIVE_SPECIALIST: 'Spécialistes',
    BACKGROUND: 'Tâches de fond', GOVERNED_BACKGROUND: 'Tâches de fond', INTERNAL_COPILOT: 'Copilote interne', COPILOT: 'Copilote interne' };
  const EXEC = { DIRECT_SAFE_READ: 'Lecture directe', BOUNDED_REASONING: 'Raisonnement borné', BOUNDED_REASONING_TURN: 'Raisonnement borné', DURABLE_WORKFLOW: 'Workflow durable' };
  let agents = [], group = 'all';
  const kpi = (icon, tone, label, value) => '<article class="kpi-card"><span class="kpi-icon' + (tone ? ' kpi-icon--' + tone : '') + '">' + UI.icon(icon, 22) +
    '</span><div class="kpi-body"><span class="kpi-label">' + V.esc(label) + '</span><span class="kpi-number">' + value + '</span></div></article>';
  const gname = (g) => GROUP[String(g || '').toUpperCase()] || g || 'Autre';

  function render() {
    const groups = Array.from(new Set(agents.map(a => gname(a.role_group))));
    $('groupChips').innerHTML = ['all'].concat(groups).map(g => '<button type="button" class="chip" data-group="' + V.esc(g) + '" aria-pressed="' + (g === group) + '">' +
      V.esc(g === 'all' ? 'Tous' : g) + ' (' + (g === 'all' ? agents.length : agents.filter(a => gname(a.role_group) === g).length) + ')</button>').join('');
    const list = agents.filter(a => group === 'all' || gname(a.role_group) === group);
    $('agents').innerHTML = list.length ? list.map(a => '<article class="card agent-card"><h3><span>' + V.esc(a.display_name) + '</span>' +
      V.pill(a.is_enabled ? 'Actif' : 'Désactivé', a.is_enabled ? 'ok' : 'neutral') + '</h3><span class="cell-sub">' + V.esc(gname(a.role_group)) + ' · modèle ' + V.esc(a.model_tier || '—') + '</span>' +
      '<p>' + V.esc(a.description || '') + '</p>' +
      ((a.allowed_tools || []).length ? '<div class="tool-list">' + a.allowed_tools.slice(0, 8).map(t => '<code>' + V.esc(t) + '</code>').join('') + (a.allowed_tools.length > 8 ? '<code>+' + (a.allowed_tools.length - 8) + '</code>' : '') + '</div>'
        : '<span class="cell-sub">Aucun outil : lecture seule.</span>') + '</article>').join('') : '<p class="data-state">Aucun agent.</p>';
  }

  async function load() {
    const [ag, act] = await Promise.all([V.getJson('/api/v1/agents'), V.getJson('/api/v1/agents/activity')]);
    if (!ag.ok) { $('agents').innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(ag)) + '</p>'; $('kpis').innerHTML = ''; }
    else agents = V.list(ag.data);
    const logs = act.ok ? V.list(act.data) : [];
    $('kpis').innerHTML = kpi('sparkle', '', 'Rôles d’agents', agents.length) + kpi('target', '', 'Actifs', agents.filter(a => a.is_enabled).length) +
      kpi('grid', 'sand', 'Outils autorisés', new Set(agents.flatMap(a => a.allowed_tools || [])).size) + kpi('chat', 'terra', 'Activités récentes', logs.length);
    if (ag.ok) render();
    if (!act.ok) V.rowState($('activityRows'), 4, 'error', V.errorText(act));
    else $('activityRows').innerHTML = logs.length ? logs.slice(0, 20).map(l => '<tr><td data-label=""><strong>' + V.esc((agents.find(a => a.role_code === l.agent_role || a.role_id === l.agent_role) || {}).display_name || l.agent_role) + '</strong></td>' +
      '<td data-label="Classe d’exécution">' + V.esc(EXEC[String(l.execution_class).toUpperCase()] || l.execution_class || '—') + '</td>' +
      '<td data-label="Conversation">' + (l.conversation_id ? '<code>' + V.esc(String(l.conversation_id).slice(0, 12)) + '</code>' : '—') + '</td>' +
      '<td data-label="Quand">' + V.esc(V.ago(l.created_at || l.timestamp)) + '</td></tr>').join('') : '<tr><td colspan="4" class="data-state">Aucune activité récente.</td></tr>';
  }

  function init() {
    $('groupChips').addEventListener('click', (e) => { const b = e.target.closest('[data-group]'); if (b) { group = b.getAttribute('data-group'); render(); } });
    load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
