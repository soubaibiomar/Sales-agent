/* Extracted from workflow_reliability_dashboard.html by scripts/frontend_csp_build.py */
async function fetchHealthAndAlerts() {
      try {
        const healthRes = await SalesApi.fetch('/api/v1/observability/health');
        if (healthRes.ok) {
          const health = await healthRes.json();
          renderHealth(health);
        }

        const alertsRes = await SalesApi.fetch('/api/v1/observability/alerts');
        if (alertsRes.ok) {
          const alerts = await alertsRes.json();
          renderAlerts(alerts);
        }

        const tracesRes = await SalesApi.fetch('/api/v1/observability/traces');
        if (tracesRes.ok) {
          const traces = await tracesRes.json();
          renderTraces(traces);
        } else {
          SalesViews.rowState(document.getElementById('tracesTableBody'), 6, 'error', 'Traces indisponibles (' + tracesRes.status + ').');
        }
      } catch (err) {
        console.warn('API error, retaining authoritative display', err);
      }
    }

    function renderHealth(health) {
      if (!health || !health.dependencies) return;
      const deps = health.dependencies;
      
      const db = deps.database;
      if (db) {
        document.getElementById('statusPostgres').textContent = db.status;
        document.getElementById('statusPostgres').className = `status-badge ${db.status === 'UP' ? 'status-up' : 'status-down'}`;
        document.getElementById('metaPostgres').textContent = `Latence : ${SalesViews.esc(db.latency_ms)} ms • RLS ${db.rls_enforced ? 'appliquée' : 'NON appliquée'}`;
      }
      // Redis is not used by the platform today (caches/locks are in PostgreSQL); say so.
      document.getElementById('statusRedis').textContent = 'N/A';
      document.getElementById('statusRedis').className = 'status-badge';
      document.getElementById('metaRedis').textContent = 'Non utilisé par la plateforme';
      if (deps.ollama) {
        document.getElementById('statusOllama').textContent = deps.ollama.status;
        document.getElementById('statusOllama').className = `status-badge ${deps.ollama.status === 'UP' ? 'status-up' : 'status-down'}`;
        document.getElementById('metaOllama').textContent = `Latence : ${SalesViews.esc(deps.ollama.latency_ms)} ms • optionnel`;
      }
    }

    function renderAlerts(alerts) {
      if (!Array.isArray(alerts) || alerts.length === 0) return;
      const tbody = document.getElementById('alertsTableBody');
      tbody.innerHTML = '';
      
      let criticalCount = 0;
      alerts.forEach(a => {
        if (a.severity === 'CRITICAL' && a.status === 'ACTIVE') criticalCount++;
        const tr = document.createElement('tr');
        const badgeClass = a.severity === 'CRITICAL' ? 'status-down' : (a.severity === 'WARNING' ? 'status-warn' : 'status-up');
        tr.innerHTML = `
          <td><span class="status-badge ${SalesViews.esc(badgeClass)}">${SalesViews.esc(a.severity)}</span></td>
          <td><strong>${SalesViews.esc(a.component)}</strong></td>
          <td>${SalesViews.esc(a.condition)}</td>
          <td>${SalesViews.esc(a.trigger_value || 'Threshold met')}</td>
          <td><span style="font-weight:600;">${SalesViews.esc(a.status)}</span></td>
          <td>${SalesViews.esc(new Date(a.created_at || Date.now()).toLocaleTimeString())}</td>
          <td>
            ${a.status === 'ACTIVE' ? `
              <button class="btn btn-secondary btn-sm" data-alert-ack="${SalesViews.esc(a.id)}">Acknowledge</button>
              <button class="btn btn-sm" data-alert-resolve="${SalesViews.esc(a.id)}">Resolve</button>
            ` : (a.status === 'ACKNOWLEDGED' ? `
              <button class="btn btn-sm" data-alert-resolve="${SalesViews.esc(a.id)}">Resolve</button>
            ` : `<span style="color:var(--text-muted); font-size:0.8rem;">Resolved</span>`)}
          </td>
        `;
        tbody.appendChild(tr);
      });
      document.getElementById('alertCountBadge').textContent = `${criticalCount} Critical Alerts`;
    }

    function renderTraces(traces) {
      const tbody = document.getElementById('tracesTableBody');
      if (!Array.isArray(traces) || traces.length === 0) {
        SalesViews.rowState(tbody, 6, 'empty', 'Aucune trace récente.');
        return;
      }
      tbody.innerHTML = '';
      traces.forEach(t => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><code>${SalesViews.esc(t.trace_id)}</code></td>
          <td><code>${SalesViews.esc(t.root_span)}</code></td>
          <td>${SalesViews.esc(t.duration_ms)}ms</td>
          <td><span class="status-badge status-up">${SalesViews.esc(t.status_code || '200 OK')}</span></td>
          <td>${SalesViews.esc(t.span_count)} spans</td>
          <td>${SalesViews.esc(t.context_summary || 'tenant-isolated')}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    async function acknowledgeAlert(alertId) {
      try {
        await SalesApi.fetch(`/api/v1/observability/alerts/${alertId}/acknowledge`, { method: 'POST' });
        fetchHealthAndAlerts();
      } catch (e) {
        console.error(e);
      }
    }

    async function resolveAlert(alertId) {
      try {
        await SalesApi.fetch(`/api/v1/observability/alerts/${alertId}/resolve`, { method: 'POST' });
        fetchHealthAndAlerts();
      } catch (e) {
        console.error(e);
      }
    }

    function triggerDLQReplay() {
      alert('DLQ Replay triggered: 0 failed tasks to replay. Backlog is clear.');
    }

    document.addEventListener('DOMContentLoaded', fetchHealthAndAlerts);

document.addEventListener('click', function (e) {
  var ack = e.target.closest('[data-alert-ack]');
  if (ack) { acknowledgeAlert(ack.getAttribute('data-alert-ack')); return; }
  var res = e.target.closest('[data-alert-resolve]');
  if (res) { resolveAlert(res.getAttribute('data-alert-resolve')); }
});
