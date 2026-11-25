/* Selia — Intégrations: outbox health (GET /api/v1/integrations/status) and the dead-letter
 * queue with retry. The previous page called /integrations/outbox, which does not exist. */
(function () {
  'use strict';
  const V = window.SalesViews, UI = window.SalesAI;
  const $ = (id) => document.getElementById(id);
  const kpi = (icon, tone, label, value, extra) => '<article class="kpi-card"><span class="kpi-icon' + (tone ? ' kpi-icon--' + tone : '') + '">' + UI.icon(icon, 22) +
    '</span><div class="kpi-body"><span class="kpi-label">' + V.esc(label) + '</span><span class="kpi-number">' + value + '</span>' + (extra ? '<span class="kpi-delta">' + V.esc(extra) + '</span>' : '') + '</div></article>';

  async function load() {
    const [st, dlq] = await Promise.all([V.getJson('/api/v1/integrations/status'), V.getJson('/api/v1/integrations/outbox/dlq')]);
    if (st.ok) {
      const s = st.data;
      $('kpis').innerHTML = kpi('target', s.status === 'HEALTHY' ? '' : 'terra', 'État', V.pill(s.status === 'HEALTHY' ? 'Sain' : 'À surveiller', s.status === 'HEALTHY' ? 'ok' : 'warn')) +
        kpi('arrow', 'sand', 'En attente d’envoi', V.esc(s.outbox_pending_count)) +
        kpi('calendar', 'terra', 'Échecs définitifs', V.esc(s.dead_letter_queue_count)) + kpi('grid', '', 'Intégrations actives', V.esc(s.active_integrations_count));
    } else $('kpis').innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(st)) + '</p>';
    const tbody = $('dlqRows');
    if (!dlq.ok) { V.rowState(tbody, 7, 'error', V.errorText(dlq)); return; }
    const rows = V.list(dlq.data);
    tbody.innerHTML = rows.length ? rows.map(e => '<tr><td data-label=""><code>' + V.esc(e.event_type) + '</code></td>' +
      '<td data-label="Canal">' + V.esc(e.channel_type || '—') + '</td><td data-label="Destinataire">' + V.esc(e.recipient_identifier ? '…' + String(e.recipient_identifier).slice(-6) : '—') + '</td>' +
      '<td data-label="Tentatives" class="num">' + V.esc((e.retry_count || 0) + ' / ' + (e.max_retries || 0)) + '</td>' +
      '<td data-label="Dernière erreur">' + V.esc(e.last_error || '—') + '</td><td data-label="Créé">' + V.esc(V.ago(e.created_at)) + '</td>' +
      '<td data-label=""><button type="button" class="btn btn-outline btn-sm" data-retry="' + V.esc(e.id) + '">Relancer</button></td></tr>').join('')
      : '<tr><td colspan="7" class="data-state">Aucun événement en échec. Tout est délivré ou en cours.</td></tr>';
  }

  function init() {
    $('dlqRows').addEventListener('click', async (e) => {
      const b = e.target.closest('[data-retry]');
      if (!b) return;
      b.disabled = true;
      const res = await V.getJson('/api/v1/integrations/outbox/dlq/' + encodeURIComponent(b.getAttribute('data-retry')) + '/retry', { method: 'POST' });
      if (!res.ok) { b.disabled = false; UI.showToast(res.status === 403 ? 'Votre rôle ne permet pas de relancer.' : 'Relance impossible : ' + V.errorText(res)); return; }
      UI.showToast('Événement remis dans la file d’envoi.');
      load();
    });
    $('btnRefresh').addEventListener('click', load);
    load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
