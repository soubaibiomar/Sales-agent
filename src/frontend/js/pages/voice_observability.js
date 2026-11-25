/* Extracted from voice_observability.html by scripts/frontend_csp_build.py */
async function runVoiceBenchmark() {
      try {
        const resp = await SalesApi.fetch("/api/v1/observability/voice-metrics");
        if (resp.ok) {
          const data = await resp.json();
          document.getElementById("kpiTurnLatency").textContent = "Non mesuré (ASR/LLM exclus)";
          document.getElementById("kpiBargeIn").textContent = `${data.barge_in_latency.mean_ms} ms`;
          if (data.hardware_envelope && data.hardware_envelope.gpu && data.hardware_envelope.gpu.vram_used_mb) {
            document.getElementById("kpiVRAM").textContent = `${data.hardware_envelope.gpu.vram_used_mb} MB`;
          }
          const rows = [
            ["Détection d'activité vocale (VAD)", "Seuil d'énergie RMS", data.vad_latency],
            ["Identification de langue", "MultilingualVoiceEngine", data.lid_latency],
            ["Synthèse vocale (premier segment)", "Piper, CPU", data.tts_first_chunk_latency],
            ["Annulation sur interruption", "BargeInManager", data.barge_in_latency]
          ];
          const tbody = document.getElementById("componentTableBody");
          tbody.innerHTML = rows.map(r => `<tr><td>${SalesViews.esc(r[0])}</td><td>${SalesViews.esc(r[1])}</td><td>${SalesViews.esc(r[2].mean_ms)} ms</td><td>${SalesViews.esc(r[2].p95_ms)} ms</td><td>—</td><td>Mesuré (n=${SalesViews.esc(r[2].count)})</td></tr>`).join("") +
            '<tr><td>ASR et LLM</td><td>faster-whisper, qwen3.5:4b</td><td colspan="4">Non mesurés ici — voir scripts/benchmark_real_voice_turn.py</td></tr>';
          if (window.SalesAI && window.SalesAI.showToast) { window.SalesAI.showToast(`Étapes mesurées (VAD, garde, TTS, interruption) sur ${data.sample_size} essais : ${data.measured_stages_latency.mean_ms} ms. ASR et LLM non inclus.`); }
        }
      } catch (e) {
        console.error("Failed to run voice benchmark:", e);
      }
    }

    async function loadInitialStats() {
      try {
        const hResp = await SalesApi.fetch("/api/v1/observability/health");
        if (hResp.ok) {
          const h = await hResp.json();
          const v = h.hardware && h.hardware.vram_mb;
          document.getElementById("kpiVRAM").textContent = (v && v.available) ? `${Math.round(v.used_mb)} MB` : "Indisponible";
        } else {
          document.getElementById("kpiVRAM").textContent = "Indisponible";
        }
      } catch (e) {
        document.getElementById("kpiVRAM").textContent = "Indisponible";
      }
      // No measured turn latency is exposed by the API yet: never show an invented figure.
      document.getElementById("kpiTurnLatency").textContent = "Non mesuré";
    }

    window.addEventListener("DOMContentLoaded", loadInitialStats);
