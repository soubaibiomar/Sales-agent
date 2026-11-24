/* Extracted from notifications.html by scripts/frontend_csp_build.py */
async function handleSendNotification(e) {
      e.preventDefault();
      const recipient = document.getElementById('recipient').value;
      const channel = document.getElementById('channel').value;
      const msgClass = document.getElementById('msgClass').value;
      const templateName = document.getElementById('templateName').value;
      let variables = {};
      try {
        variables = JSON.parse(document.getElementById('templateVariables').value);
      } catch (err) {
        alert("Invalid JSON in variables");
        return;
      }

      try {
        const res = await SalesApi.fetch('/api/v1/notifications/send', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',},
          body: JSON.stringify({
            recipient,
            channel,
            message_class: msgClass,
            template_name: templateName,
            variables
          })
        });
        const data = await res.json();
        if (res.ok) {
          alert(`Notification processed! Status: ${data.status}\n${data.error_reason ? 'Reason: ' + data.error_reason : ''}`);
          loadLogs();
        } else {
          alert("Error: " + (data.detail || JSON.stringify(data)));
        }
      } catch (err) {
        alert("Network error: " + err.message);
      }
    }

    async function simulateOptOut() {
      const recipient = document.getElementById('optoutRecipient').value;
      const text = document.getElementById('optoutText').value;
      try {
        const res = await SalesApi.fetch('/api/v1/notifications/opt-out', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',},
          body: JSON.stringify({
            recipient,
            channel: 'WHATSAPP',
            inbound_message_text: text
          })
        });
        const data = await res.json();
        if (res.ok) {
          alert(data.opted_out ? `Opt-out successfully registered via keyword '${data.matched_keyword}'!` : 'No opt-out keyword detected in message.');
        } else {
          alert("Error: " + (data.detail || JSON.stringify(data)));
        }
      } catch (err) {
        alert("Network error: " + err.message);
      }
    }

    async function loadLogs() {
      try {
        const res = await SalesApi.fetch('/api/v1/notifications/history', {
          headers: {}
        });
        if (res.ok) {
          const list = await res.json();
          const tbody = document.getElementById('logsBody');
          if (list.length > 0) {
            tbody.innerHTML = list.map(item => `
              <tr>
                <td><code>${SalesViews.esc(item.id)}</code></td>
                <td>${SalesViews.esc(item.recipient)}</td>
                <td><strong>${SalesViews.esc(item.channel)}</strong></td>
                <td><span class="badge" style="background:#DBEAFE; color:#2563EB;">${SalesViews.esc(item.message_class)}</span></td>
                <td><span class="badge ${SalesViews.esc(item.status === 'DELIVERED' ? 'badge-delivered' : (item.status === 'CANCELLED' ? 'badge-cancelled' : 'badge-suppressed'))}">${SalesViews.esc(item.status)}</span></td>
                <td>${SalesViews.esc(item.error_reason || 'Dispatched successfully')}</td>
                <td>${SalesViews.esc(new Date(item.created_at).toLocaleTimeString())}</td>
              </tr>
            `).join('');
          }
        }
      } catch (e) {
        console.warn("Could not load dynamic logs:", e);
      }
    }
