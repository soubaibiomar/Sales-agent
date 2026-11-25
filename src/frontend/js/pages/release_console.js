/* Selia — État de la plateforme: readiness of the service, its dependencies and host
 * resources (GET /api/v1/observability/health). Replaces a static "release console" whose
 * figures and verdicts were hardcoded. */
(function () {
  'use strict';
  const V = window.SalesViews, UI = window.SalesAI;
  const $ = (id) => document.getElementById(id);
  const DEP = { database: 'Base de données (PostgreSQL)', ollama: 'Modèles IA (Ollama)' };
  const kpi = (icon, tone, label, value, extra) => '<article class="kpi-card"><span class="kpi-icon' + (tone ? ' kpi-icon--' + tone : '') + '">' + UI.icon(icon, 22) +
    '</span><div class="kpi-body"><span class="kpi-label">' + V.esc(label) + '</span><span class="kpi-number">' + value + '</span>' + (extra ? '<span class="kpi-delta">' + V.esc(extra) + '</span>' : '') + '</div></article>';
  const mb = (v) => (v == null ? '—' : Math.round(Number(v)).toLocaleString('fr-FR') + ' Mo');

  async function load() {
    const h = await V.getJson('/api/v1/observability/health');
    if (!h.ok) { $('kpis').innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(h)) + '</p>'; $('deps').innerHTML = ''; $('hardware').innerHTML = ''; return; }
    const d = h.data, deps = d.dependencies || {}, hw = d.hardware || {}, ram = hw.ram_mb || {}, vram = hw.vram_mb || {};
    const ready = d.status === 'READY';
    $('kpis').innerHTML = kpi('target', ready ? '' : 'terra', 'Service', V.pill(ready ? 'Prêt' : 'Non prêt', ready ? 'ok' : 'danger')) +
      kpi('grid', 'sand', 'Dépendances opérationnelles', Object.values(deps).filter(x => x.status === 'UP').length + ' / ' + Object.keys(deps).length) +
      kpi('chart', '', 'Mémoire disponible', V.esc(mb(ram.free_mb)), ram.total_mb ? 'sur ' + mb(ram.total_mb) : '') +
      kpi('settings', 'terra', 'Mémoire GPU utilisée', vram.available ? V.esc(mb(vram.used_mb)) : '—', vram.available ? 'sur ' + mb(vram.total_mb) : 'GPU non détecté');
    $('checkedAt').textContent = 'Vérifié ' + V.ago(d.checked_at).toLowerCase();
    $('deps').innerHTML = Object.keys(deps).map(k => {
      const x = deps[k];
      return '<div class="dep"><strong>' + V.esc(DEP[k] || k) + V.pill(x.status === 'UP' ? 'Opérationnel' : 'Indisponible', x.status === 'UP' ? 'ok' : (x.required ? 'danger' : 'warn')) + '</strong>' +
        '<span class="cell-sub">Latence ' + V.esc(x.latency_ms) + ' ms · ' + (x.required ? 'requis pour servir le trafic' : 'optionnel') + '</span>' +
        (k === 'database' ? '<span class="cell-sub">Isolation des données (RLS) : ' + (x.rls_enforced ? 'appliquée' : 'NON appliquée') + '</span>' : '') +
        (x.error ? '<span class="cell-sub">Erreur : ' + V.esc(x.error) + '</span>' : '') + '</div>';
    }).join('');
    $('hardware').innerHTML = '<dt>Mémoire vive</dt><dd>' + V.esc(mb(ram.used_mb)) + ' utilisés sur ' + V.esc(mb(ram.total_mb)) + '</dd>' +
      '<dt>Processeur graphique</dt><dd>' + (vram.available ? V.esc(mb(vram.used_mb)) + ' utilisés sur ' + V.esc(mb(vram.total_mb)) : 'Non détecté sur cet hôte') + '</dd>';
  }

  function init() { $('btnRefresh').addEventListener('click', load); load(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
