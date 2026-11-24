/* Extracted from ai_operations_dashboard.html by scripts/frontend_csp_build.py */
async function fetchAIMetrics() {
      try {
        const resp = await SalesApi.fetch("/api/v1/observability/ai-metrics");
        if (resp.ok) {
          const m = await resp.json();
          document.getElementById("kpiTotalInferences").innerText = m.total_inferences;
          document.getElementById("kpiColdStarts").innerText = `${m.cold_starts_count} cold starts recorded`;
          document.getElementById("kpiTotalTokens").innerText = (m.total_tokens || 0).toLocaleString();
          document.getElementById("kpiTokenSplit").innerText = `${(m.total_prompt_tokens||0).toLocaleString()} in / ${(m.total_completion_tokens||0).toLocaleString()} out`;
          document.getElementById("kpiAvgTTFT").innerText = `${m.avg_ttft_ms} ms`;
          document.getElementById("kpiP95TTFT").innerText = `p95: ${m.p95_ttft_ms} ms`;
          document.getElementById("kpiThroughput").innerText = `${m.avg_throughput_tok_s} tok/s`;
          document.getElementById("kpiErrorRate").innerText = `${m.error_rate_pct}%`;

          renderRecentTurns(m.recent_executions);
        }
      } catch (e) {
        console.error("Failed to load AI metrics:", e);
      }
    }

    function renderRecentTurns(turns) {
      const tbody = document.getElementById("turnsTableBody");
      if (!turns || turns.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--text-muted);">No model inference turns recorded yet in this session.</td></tr>`;
        return;
      }
      tbody.innerHTML = turns.map(t => `
        <tr>
          <td>${SalesViews.esc(t.timestamp.slice(11, 19))}</td>
          <td><strong>${SalesViews.esc(t.agent_role)}</strong></td>
          <td>${SalesViews.esc(t.model_name)}</td>
          <td>${SalesViews.esc(t.prompt_tokens)} / ${SalesViews.esc(t.completion_tokens)}</td>
          <td>${SalesViews.esc(t.ttft_ms)} ms</td>
          <td>${SalesViews.esc(t.throughput_tok_per_s)} tok/s</td>
          <td>${SalesViews.esc(t.total_latency_ms)} ms</td>
          <td><span class="${SalesViews.esc(t.status === 'SUCCESS' ? 'badge-ok' : 'badge-err')}">${SalesViews.esc(t.status)}</span></td>
        </tr>
      `).join("");
    }

    window.addEventListener("DOMContentLoaded", fetchAIMetrics);
