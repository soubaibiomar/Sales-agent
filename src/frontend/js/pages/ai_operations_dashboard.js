/* Selia — Opérations IA: measured model telemetry (/observability/ai-metrics). */
(function () {
  'use strict';
  const V = window.SalesViews, UI = window.SalesAI;
  const $ = (id) => document.getElementById(id);
  const kpi = (icon, tone, label, value, extra) => '<article class="kpi-card"><span class="kpi-icon' + (tone ? ' kpi-icon--' + tone : '') + '">' + UI.icon(icon, 22) +
    '</span><div class="kpi-body"><span class="kpi-label">' + V.esc(label) + '</span><span class="kpi-number">' + value + '</span>' + (extra ? '<span class="kpi-delta">' + V.esc(extra) + '</span>' : '') + '</div></article>';
  const fmt = (v, unit) => (v == null ? '—' : Number(v).toLocaleString('fr-FR', { maximumFractionDigits: 1 }) + (unit ? ' ' + unit : ''));

  async function load() {
    const res = await V.getJson('/api/v1/observability/ai-metrics');
    if (!res.ok) { $('kpis').innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(res)) + '</p>'; V.rowState($('execRows'), 7, 'error', V.errorText(res)); return; }
    const m = res.data || {};
    $('kpis').innerHTML = kpi('sparkle', '', 'Appels au modèle', fmt(m.total_inferences), (m.cold_starts_count || 0) + ' démarrage(s) à froid') +
      kpi('chart', 'sand', 'Premier jeton (moyenne)', fmt(m.avg_ttft_ms, 'ms')) + kpi('arrow', '', 'Débit moyen', fmt(m.avg_throughput_tok_s, 'jetons/s')) +
      kpi('target', 'terra', 'Taux d’erreur', fmt(m.error_rate_pct, '%'), fmt(m.total_tokens || 0) + ' jetons au total');
    const rows = m.recent_executions || [];
    $('execRows').innerHTML = rows.length ? rows.map(x => '<tr><td data-label=""><strong>' + V.esc(x.agent_role || '—') + '</strong></td>' +
      '<td data-label="Modèle"><code>' + V.esc(x.model_name) + '</code></td><td data-label="Jetons" class="num">' + V.esc(fmt(x.total_tokens)) + '</td>' +
      '<td data-label="1er jeton" class="num">' + V.esc(fmt(x.ttft_ms, 'ms')) + '</td><td data-label="Durée totale" class="num">' + V.esc(fmt(x.total_latency_ms, 'ms')) + '</td>' +
      '<td data-label="Débit" class="num">' + V.esc(fmt(x.throughput_tok_per_s, 'j/s')) + '</td>' +
      '<td data-label="Démarrage">' + V.pill(x.is_cold_start ? 'À froid' : 'À chaud', x.is_cold_start ? 'warn' : 'ok') + '</td></tr>').join('')
      : '<tr><td colspan="7" class="data-state">Aucun appel au modèle enregistré depuis le démarrage du service.</td></tr>';
  }

  function init() { $('btnRefresh').addEventListener('click', load); load(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
