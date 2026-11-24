/* Extracted from integrations.html by scripts/frontend_csp_build.py */
async function verifyBarrier(action) {
      const resultDiv = document.getElementById('barrierResult');
      resultDiv.style.display = 'block';
      resultDiv.style.background = '#F8FAFC';
      resultDiv.innerHTML = 'Testing barrier for action: <code>' + action + '</code>...';

      try {
        const res = await SalesApi.fetch('/api/v1/integrations/n8n/verify-barrier', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',},
          body: JSON.stringify({ action: action })
        });
        const data = await res.json();
        if (data.allowed) {
          resultDiv.style.background = '#DCFCE7';
          resultDiv.style.color = '#16A34A';
          resultDiv.innerHTML = `✅ <strong>PERMITTED PERIPHERAL ACTION:</strong> Action <code>${SalesViews.esc(action)}</code> was accepted as a non-commercial task.`;
        } else {
          resultDiv.style.background = '#FEE2E2';
          resultDiv.style.color = '#DC2626';
          resultDiv.innerHTML = `🛡️ <strong>BLOCKED BY SECURITY BARRIER (HTTP 403):</strong> ${SalesViews.esc(data.detail)}`;
        }
      } catch (err) {
        resultDiv.style.background = '#FEE2E2';
        resultDiv.style.color = '#DC2626';
        resultDiv.innerHTML = 'Error: ' + err.message;
      }
    }

    async function loadOutbox() {
      try {
        const res = await SalesApi.fetch('/api/v1/integrations/outbox', {
          headers: {}
        });
        if (res.ok) {
          const list = await res.json();
          const tbody = document.getElementById('outboxBody');
          if (list.length > 0) {
            tbody.innerHTML = list.map(item => `
              <tr>
                <td><code>${SalesViews.esc(item.id)}</code></td>
                <td><code>${SalesViews.esc(item.event_type)}</code></td>
                <td><span class="badge ${SalesViews.esc(item.status === 'PUBLISHED' ? 'badge-success' : (item.status === 'FAILED' ? 'badge-danger' : 'badge-pending'))}">${SalesViews.esc(item.status)}</span></td>
                <td>${SalesViews.esc(item.retry_count)}</td>
                <td>${SalesViews.esc(new Date(item.created_at).toLocaleTimeString())}</td>
                <td>${item.status === 'DEAD_LETTER' || item.status === 'FAILED' ? `<button class="btn btn-outline" data-retry-event="${SalesViews.esc(item.id)}">Retry DLQ</button>` : '—'}</td>
              </tr>
            `).join('');
          }
        }
      } catch (e) {
        console.warn("Could not load outbox dynamically:", e);
      }
    }

    async function retryEvent(id) {
      try {
        const res = await SalesApi.fetch(`/api/v1/integrations/outbox/${id}/retry`, {
          method: 'POST',
          headers: {}
        });
        if (res.ok) {
          alert("Event requeued from DLQ successfully!");
          loadOutbox();
        }
      } catch (err) {
        alert("Retry failed: " + err.message);
      }
    }

document.addEventListener('click', function (e) {
  var btn = e.target.closest('[data-retry-event]');
  if (btn) { retryEvent(btn.getAttribute('data-retry-event')); }
});
