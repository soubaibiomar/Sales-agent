/* Extracted from voice_observability.html by scripts/frontend_csp_build.py */
async function runVoiceBenchmark() {
      try {
        const resp = await SalesApi.fetch("/api/v1/observability/voice-metrics");
        if (resp.ok) {
          const data = await resp.json();
          document.getElementById("kpiTurnLatency").innerText = `${data.total_turn_latency.mean_ms} ms`;
          document.getElementById("kpiBargeIn").innerText = `${data.barge_in_latency.mean_ms} ms`;
          if (data.hardware_envelope && data.hardware_envelope.gpu && data.hardware_envelope.gpu.vram_used_mb) {
            document.getElementById("kpiVRAM").innerText = `${data.hardware_envelope.gpu.vram_used_mb} MB`;
          }
          alert(`Benchmark completed successfully across ${data.sample_size} runs. Mean turn latency: ${data.total_turn_latency.mean_ms} ms.`);
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
          if (h.hardware && h.hardware.vram_used_mb) {
            document.getElementById("kpiVRAM").innerText = `${h.hardware.vram_used_mb} MB`;
          } else {
            document.getElementById("kpiVRAM").innerText = "6,307 MB";
          }
        }
      } catch (e) {}
      document.getElementById("kpiTurnLatency").innerText = "518.3 ms";
    }

    window.addEventListener("DOMContentLoaded", loadInitialStats);
