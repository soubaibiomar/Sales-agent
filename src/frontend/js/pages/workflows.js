/* Extracted from workflows.html by scripts/frontend_csp_build.py */
async function handleTriggerWorkflow(e) {
      e.preventDefault();
      const sagaType = document.getElementById('sagaType').value;
      const idempotencyKey = document.getElementById('idempotencyKey').value || 'wf-' + Math.random().toString(36).substring(2, 9);
      let payload = {};
      try {
        payload = JSON.parse(document.getElementById('payloadJson').value);
      } catch (err) {
        alert("Invalid JSON payload");
        return;
      }

      try {
        const res = await SalesApi.fetch('/api/v1/workflows/executions', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',},
          body: JSON.stringify({
            workflow_type: sagaType,
            workflow_name: sagaType,
            idempotency_key: idempotencyKey,
            input_payload: payload
          })
        });
        const data = await res.json();
        if (res.ok) {
          alert("Workflow dispatched! ID: " + data.id + " Status: " + data.status);
          loadExecutions();
        } else {
          alert("Error: " + (data.detail || JSON.stringify(data)));
        }
      } catch (err) {
        alert("Network error: " + err.message);
      }
    }

    async function triggerCrashRecovery() {
      try {
        const res = await SalesApi.fetch('/api/v1/workflows/recovery/resume', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',}
        });
        const data = await res.json();
        alert("Crash recovery executed! Resumed: " + data.resumed_count + " workflows.");
        loadExecutions();
      } catch (err) {
        alert("Recovery error: " + err.message);
      }
    }

    async function loadExecutions() {
      try {
        const res = await SalesApi.fetch('/api/v1/workflows/executions', {
          headers: {}
        });
        if (res.ok) {
          const list = await res.json();
          const tbody = document.getElementById('executionsBody');
          if (list.length > 0) {
            tbody.innerHTML = list.map(item => `
              <tr>
                <td><code>${SalesViews.esc(item.id)}</code></td>
                <td><strong>${SalesViews.esc(item.workflow_type)}</strong></td>
                <td><span class="badge ${SalesViews.esc(getStatusBadge(item.status))}">${SalesViews.esc(item.status)}</span></td>
                <td>${SalesViews.esc(item.current_step || '—')}</td>
                <td>${SalesViews.esc(item.retry_count)}</td>
                <td>${SalesViews.esc(new Date(item.started_at).toLocaleTimeString())}</td>
                <td>${SalesViews.esc(item.completed_at ? new Date(item.completed_at).toLocaleTimeString() : 'In Progress')}</td>
                <td><button class="btn btn-outline" style="padding: 2px 8px; font-size: 0.75rem;">View</button></td>
              </tr>
            `).join('');
          }
        }
      } catch (e) {
        console.warn("Could not load executions dynamically:", e);
      }
    }

    function getStatusBadge(status) {
      if (status === 'COMPLETED') return 'badge-success';
      if (status === 'RUNNING') return 'badge-running';
      if (status === 'FAILED') return 'badge-failed';
      if (status === 'COMPENSATED') return 'badge-compensated';
      return 'badge-info';
    }
