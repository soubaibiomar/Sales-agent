/* Selia — Observabilité vocale. The full-turn figure is the measured group D benchmark
 * (static, dated on the page); local stages (VAD, language ID, TTS, barge-in) are measured
 * on demand through /observability/voice-metrics. ASR and LLM are never invented. */
(function () {
  'use strict';
  const V = window.SalesViews;
  const $ = (id) => document.getElementById(id);

  async function loadInitial() {
    $('kpiTurnLatency').textContent = '6 859 ms';
    const h = await V.getJson('/api/v1/observability/health');
    const v = h.ok && h.data.hardware && h.data.hardware.vram_mb;
    $('kpiVRAM').textContent = v && v.available ? Math.round(v.used_mb).toLocaleString('fr-FR') + ' Mo' : 'Indisponible';
    V.rowState($('componentTableBody'), 6, 'empty', 'Cliquez sur « Mesurer les étapes locales » pour lancer une mesure.');
  }

  async function benchmark() {
    const btn = $('btnBenchmark');
    btn.disabled = true;
    V.rowState($('componentTableBody'), 6, 'loading', 'Mesure en cours…');
    const res = await V.getJson('/api/v1/observability/voice-metrics');
    btn.disabled = false;
    if (!res.ok) { V.rowState($('componentTableBody'), 6, 'error', V.errorText(res)); return; }
    const d = res.data;
    $('kpiBargeIn').textContent = d.barge_in_latency.mean_ms + ' ms';
    const rows = [
      ["Détection d'activité vocale", "Seuil d'énergie RMS", d.vad_latency],
      ['Identification de langue', 'MultilingualVoiceEngine', d.lid_latency],
      ['Synthèse vocale (premier segment)', 'Piper, CPU', d.tts_first_chunk_latency],
      ['Annulation sur interruption', 'BargeInManager', d.barge_in_latency]
    ];
    $('componentTableBody').innerHTML = rows.map(r => '<tr><td data-label=""><strong>' + V.esc(r[0]) + '</strong></td><td data-label="Implémentation">' + V.esc(r[1]) + '</td>' +
      '<td data-label="Moyenne" class="num">' + V.esc(r[2].mean_ms) + ' ms</td><td data-label="p95" class="num">' + V.esc(r[2].p95_ms) + ' ms</td>' +
      '<td data-label="Objectif">—</td><td data-label="Mesure">' + V.pill('n = ' + r[2].count, 'info') + '</td></tr>').join('') +
      '<tr><td data-label=""><strong>Reconnaissance et modèle</strong></td><td data-label="Implémentation">faster-whisper, qwen3.5:4b</td>' +
      '<td colspan="4" data-label="Mesure">Non mesurés ici — voir le bloc « tour vocal complet » ci-dessus.</td></tr>';
    window.SalesAI.showToast('Étapes locales mesurées sur ' + d.sample_size + ' essais.');
  }

  function init() { $('btnBenchmark').addEventListener('click', benchmark); loadInitial(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
