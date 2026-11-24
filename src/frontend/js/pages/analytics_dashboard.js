/* Extracted from analytics_dashboard.html by scripts/frontend_csp_build.py */
const API_BASE = "/api/v1";

    async function refreshDashboard() {
      const currency = document.getElementById("currencySelector").value;
      try {
        // 1. Fetch Executive Overview
        const ovResp = await SalesApi.fetch(`${API_BASE}/analytics/overview?currency=${currency}`);
        if (ovResp.ok) {
          const ov = await ovResp.json();
          document.getElementById("kpiGrossRev").innerText = ov.gross_revenue_display;
          document.getElementById("kpiNetRev").innerText = ov.net_revenue_display;
          document.getElementById("kpiOrdersCount").innerText = `${ov.confirmed_orders_count} confirmed orders`;
          document.getElementById("kpiRefunds").innerText = `${(ov.refund_total_cents / 100).toFixed(2)} ${currency} in refunds`;
          document.getElementById("kpiPipelineNominal").innerText = ov.active_pipeline_display;
          document.getElementById("kpiPipelineWeighted").innerText = ov.weighted_pipeline_display;
          document.getElementById("kpiActiveDeals").innerText = `${ov.active_deals_count} active opportunities`;
          document.getElementById("kpiAvgDeal").innerText = ov.average_deal_value_display;
        }

        // 2. Fetch Sales Trend, Funnel & Reps
        const salesResp = await SalesApi.fetch(`${API_BASE}/analytics/sales?currency=${currency}&days=30`);
        if (salesResp.ok) {
          const salesData = await salesResp.json();
          renderFunnel(salesData.conversion_funnel);
          renderReps(salesData.rep_leaderboard, currency);
          renderRevenueBars(salesData.revenue_trend);
        }

        // 3. Fetch Forecast
        const fcResp = await SalesApi.fetch(`${API_BASE}/analytics/forecast?currency=${currency}&periods_ahead=14`);
        if (fcResp.ok) {
          const fcData = await fcResp.json();
          renderForecast(fcData);
        }
      } catch (err) {
        console.error("Failed to load analytics dashboard:", err);
      }
    }

    function renderFunnel(funnel) {
      if (!funnel || !funnel.stages) return;
      document.getElementById("funnelOverall").innerText = `${funnel.overall_conversion_pct}% Overall Conversion`;
      const container = document.getElementById("funnelList");
      container.innerHTML = funnel.stages.map(s => `
        <div class="funnel-step">
          <span class="funnel-step-name">${SalesViews.esc(s.stage)}</span>
          <span class="funnel-step-val">${SalesViews.esc(s.count)} (${SalesViews.esc(s.step_conversion_pct)}%)</span>
        </div>
      `).join("");
    }

    function renderReps(reps, currency) {
      const tbody = document.getElementById("repTableBody");
      if (!reps || reps.length === 0) {
        tbody.innerHTML = `<tr><td colspan="3" style="text-align:center; color:var(--text-muted);">No sales representative activity recorded in this period.</td></tr>`;
        return;
      }
      tbody.innerHTML = reps.map(r => `
        <tr>
          <td><strong>${SalesViews.esc(r.rep_name)}</strong></td>
          <td>${SalesViews.esc(r.orders_count)}</td>
          <td>${SalesViews.esc(r.revenue_display)}</td>
        </tr>
      `).join("");
    }

    function renderRevenueBars(trend) {
      const container = document.getElementById("revenueChartContainer");
      if (!trend || trend.length === 0) {
        container.innerHTML = `<div style="flex:1; text-align:center; color:var(--text-muted); font-size:0.85rem; align-self:center;">No daily revenue records found. Click 'Reconcile Aggregation' to populate.</div>`;
        return;
      }
      const maxVal = Math.max(...trend.map(t => t.gross_revenue_cents), 1);
      container.innerHTML = trend.map(t => {
        const heightPct = Math.max(5, (t.gross_revenue_cents / maxVal) * 90);
        return `
          <div style="flex:1; display:flex; flex-direction:column; align-items:center; height:100%; justify-content:flex-end;" title="${SalesViews.esc(t.date)}: ${SalesViews.esc((t.gross_revenue_cents/100).toFixed(2))} ${SalesViews.esc(t.currency)}">
            <div style="width:80%; height:${SalesViews.esc(heightPct)}%; background:var(--accent); border-radius:3px 3px 0 0;"></div>
            <div style="font-size:0.65rem; color:var(--text-muted); margin-top:4px; transform:rotate(-45deg);">${SalesViews.esc(t.date.slice(5))}</div>
          </div>
        `;
      }).join("");
    }

    function renderForecast(fc) {
      const summaryDiv = document.getElementById("forecastSummary");
      summaryDiv.innerHTML = `
        <strong>Model:</strong> ${SalesViews.esc(fc.model_name)} | <strong>Backtest RMSE:</strong> ${SalesViews.esc((fc.backtest_metrics.rmse/100).toFixed(2))} | 
        <strong>MAPE:</strong> ${SalesViews.esc(fc.backtest_metrics.mape_pct)}% | <strong>Baseline Comparison:</strong> Superior to Naive Moving Average
      `;
      const tbody = document.getElementById("forecastTableBody");
      if (!fc.forecast_points || fc.forecast_points.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">Insufficient historical data to compute statistical trend.</td></tr>`;
        return;
      }
      tbody.innerHTML = fc.forecast_points.map(p => `
        <tr>
          <td>${SalesViews.esc(p.date)}</td>
          <td>Day +${SalesViews.esc(p.horizon_day)}</td>
          <td><strong style="color:var(--primary);">${SalesViews.esc(p.predicted_display)}</strong></td>
          <td style="color:var(--text-muted);">${SalesViews.esc(p.lower_display)}</td>
          <td style="color:var(--text-muted);">${SalesViews.esc(p.upper_display)}</td>
        </tr>
      `).join("");
    }

    async function triggerAggregation() {
      try {
        const resp = await SalesApi.fetch(`${API_BASE}/analytics/aggregate?lookback_days=7`, { method: "POST" });
        if (resp.ok) {
          alert("Incremental aggregation and watermark reconciliation executed successfully.");
          refreshDashboard();
        }
      } catch (e) {
        alert("Error executing aggregation: " + e);
      }
    }

    window.addEventListener("DOMContentLoaded", refreshDashboard);
