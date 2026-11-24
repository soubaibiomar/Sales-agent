/* Extracted from ai_governance.html by scripts/frontend_csp_build.py */
function switchTab(tabId) {
      document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
      document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
      document.getElementById(tabId).style.display = 'block';
      event.target.classList.add('active');
    }

    async function executeGeneration() {
      const prompt = document.getElementById('genPrompt').value;
      const model = document.getElementById('genModel').value;
      const maxLatency = document.getElementById('genBudgetMs').value;
      const outBox = document.getElementById('genOutput');
      outBox.textContent = "Processing with Model Gateway...";

      try {
        const res = await SalesApi.fetch('/api/v1/ai/generate', {
          method: 'POST',
          headers: {'Content-Type': 'application/json',},
          body: JSON.stringify({
            tenant_id: 'default',
            prompt: prompt,
            model: model,
            max_latency_ms: parseFloat(maxLatency)
          })
        });
        const data = await res.json();
        outBox.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        outBox.textContent = "Error: " + err.message;
      }
    }

    async function evaluateRouter() {
      const text = document.getElementById('routerInput').value;
      const outBox = document.getElementById('routerOutput');
      outBox.textContent = "Analyzing language, intent and risk...";

      try {
        const res = await SalesApi.fetch('/api/v1/ai/route', {
          method: 'POST',
          headers: {'Content-Type': 'application/json',},
          body: JSON.stringify({ text: text })
        });
        const data = await res.json();
        outBox.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        outBox.textContent = "Error: " + err.message;
      }
    }

    async function verifyOutputClaims() {
      const text = document.getElementById('claimText').value;
      const outBox = document.getElementById('claimOutput');
      outBox.textContent = "Verifying against ground truth evidence...";

      try {
        const res = await SalesApi.fetch('/api/v1/ai/guard/verify', {
          method: 'POST',
          headers: {'Content-Type': 'application/json',},
          body: JSON.stringify({
            text: text,
            evidence: {
              tenant_id: 'default',
              verified_prices: {"SKU-SOLAR-01": 1250.0},
              approved_discounts_percent: [10.0]
            }
          })
        });
        const data = await res.json();
        outBox.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        outBox.textContent = "Error: " + err.message;
      }
    }

    async function executeToolCall() {
      const role = document.getElementById('toolRole').value;
      const toolName = document.getElementById('toolName').value;
      const outBox = document.getElementById('toolOutput');
      outBox.textContent = "Evaluating tool authorization...";

      try {
        const res = await SalesApi.fetch('/api/v1/ai/tools/execute', {
          method: 'POST',
          headers: {'Content-Type': 'application/json',},
          body: JSON.stringify({
            tool_name: toolName,
            params: { query: "solaire", sku: "SKU-SOLAR-01", items: [], idempotency_key: "IDEM-TEST-12345", subject: "Test Ticket", description: "Test ticket details" }
          })
        });
        const data = await res.json();
        outBox.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        outBox.textContent = "Error: " + err.message;
      }
    }

    async function runOfflineEvaluations() {
      alert("Triggering offline evaluation suite across defense, routing, and grounding...");
      try {
        const res = await SalesApi.fetch('/api/v1/ai/evaluations/run', {
          headers: {}
        });
        const data = await res.json();
        alert(`Evaluation Complete!\nPassed: ${data.passed_cases}/${data.total_cases} (${data.accuracy_percent}%)`);
      } catch (err) {
        alert("Evaluation run failed: " + err.message);
      }
    }
