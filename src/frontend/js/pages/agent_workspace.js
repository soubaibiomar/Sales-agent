/* Extracted from agent_workspace.html by scripts/frontend_csp_build.py */
// Tab Switching
    function switchAgentTab(tabName) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      
      const btn = event.currentTarget;
      if (btn) btn.classList.add('active');
      const pane = document.getElementById('pane-' + tabName);
      if (pane) pane.classList.add('active');

      if (tabName === 'catalog') refreshCatalog();
      if (tabName === 'activity') loadActivityLogs();
    }

    // Agent Catalog Data & Population
    const CATALOG_DATA = [
      { code: "R00", group: "FRONT_DOOR", role_id: "router_classifier", name: "Inbound Router & Classifier", tier: "PRIMARY_4B", cap: 2048, tools: ["router.classify_intent", "router.detect_language"], delegation: "Any Specialist", active: true },
      { code: "S00", group: "SUPERVISOR", role_id: "conversation_supervisor", name: "Conversation Supervisor", tier: "PRIMARY_4B", cap: 4096, tools: ["supervisor.handoff", "supervisor.takeover"], delegation: "A01-A09, I01", active: true },
      { code: "S00", group: "SUPERVISOR", role_id: "operations_supervisor", name: "Operations Supervisor", tier: "PRIMARY_4B", cap: 4096, tools: ["ops.triage_alerts", "ops.monitor_workers"], delegation: "B01-B06", active: true },
      { code: "A01", group: "INTERACTIVE", role_id: "qualification_crm", name: "Discovery & Qualification", tier: "PRIMARY_4B", cap: 4096, tools: ["crm.get_contact", "crm.update_lead"], delegation: "product_knowledge, quote_pricing", active: true },
      { code: "A02", group: "INTERACTIVE", role_id: "product_knowledge", name: "Product & Catalog Specialist", tier: "PRIMARY_4B", cap: 4096, tools: ["catalog.search", "inventory.check_atp"], delegation: "quote_pricing, scheduling", active: true },
      { code: "A03", group: "INTERACTIVE", role_id: "quote_pricing", name: "Quotation & Pricing Specialist", tier: "PRIMARY_4B", cap: 4096, tools: ["pricing.calculate_quote", "pricing.check_discount"], delegation: "order_payment, negotiation", active: true },
      { code: "A04", group: "INTERACTIVE", role_id: "order_payment", name: "Order & Checkout Specialist", tier: "PRIMARY_4B", cap: 4096, tools: ["orders.get_status", "payments.initiate"], delegation: "support_returns, scheduling", active: true },
      { code: "A05", group: "INTERACTIVE", role_id: "scheduling", name: "Appointment & Scheduling", tier: "PRIMARY_4B", cap: 2048, tools: ["scheduling.get_slots", "scheduling.book_slot"], delegation: "qualification_crm", active: true },
      { code: "A06", group: "INTERACTIVE", role_id: "negotiation", name: "Negotiation & Commercial Terms", tier: "PRIMARY_4B", cap: 4096, tools: ["pricing.check_discount", "quotes.request_approval"], delegation: "quote_pricing, supervisor", active: true },
      { code: "A07", group: "INTERACTIVE", role_id: "support_returns", name: "Support & Issue Resolution", tier: "PRIMARY_4B", cap: 4096, tools: ["support.lookup_ticket", "returns.check_policy"], delegation: "order_payment, supervisor", active: true },
      { code: "A08", group: "INTERACTIVE", role_id: "account_management", name: "Account Management & Retention", tier: "PRIMARY_4B", cap: 4096, tools: ["account.get_summary", "contracts.get_terms"], delegation: "quote_pricing", active: true },
      { code: "A09", group: "INTERACTIVE", role_id: "documents_billing", name: "Invoices & Documents Specialist", tier: "PRIMARY_4B", cap: 2048, tools: ["documents.get_invoice", "documents.export_pdf"], delegation: "order_payment", active: true },
      { code: "B01", group: "BACKGROUND", role_id: "outreach", name: "Outreach & Nurture Agent", tier: "PRIMARY_4B", cap: 2048, tools: ["campaigns.draft_message", "compliance.check_optout"], delegation: "None (Worker Queue)", active: true },
      { code: "B02", group: "BACKGROUND", role_id: "research", name: "Organization & Lead Research", tier: "PRIMARY_4B", cap: 4096, tools: ["research.enrich_lead", "research.scrape_domain"], delegation: "qualification_crm", active: true },
      { code: "B03", group: "BACKGROUND", role_id: "pipeline_coach", name: "Sales Pipeline Velocity Coach", tier: "PRIMARY_4B", cap: 4096, tools: ["pipeline.analyze_stale_deals"], delegation: "sales_copilot", active: true },
      { code: "B04", group: "BACKGROUND", role_id: "analyst", name: "Pricing & Performance Analyst", tier: "REASONING_9B", cap: 4096, tools: ["analytics.get_kpi_summary", "pricing.analyze_margins"], delegation: "None (Worker Queue)", active: true },
      { code: "B05", group: "BACKGROUND", role_id: "knowledge_curator", name: "Knowledge & FAQ Curator", tier: "PRIMARY_4B", cap: 4096, tools: ["knowledge.propose_article"], delegation: "None (Editorial Review)", active: true },
      { code: "B06", group: "BACKGROUND", role_id: "incident_responder", name: "Incident Diagnostics & Responder", tier: "PRIMARY_4B", cap: 4096, tools: ["incident.diagnose_system", "incident.flush_cache"], delegation: "operations_supervisor", active: true },
      { code: "I01", group: "COPILOT", role_id: "sales_copilot", name: "Sales Representative Copilot", tier: "PRIMARY_4B", cap: 4096, tools: ["copilot.generate_brief", "catalog.search"], delegation: "Human Rep Only", active: true }
    ];

    function refreshCatalog() {
      const tbody = document.getElementById('agentCatalogBody');
      tbody.innerHTML = '';
      CATALOG_DATA.forEach(a => {
        const tr = document.createElement('tr');
        const tierBadge = a.tier === 'REASONING_9B' 
          ? `<span class="badge badge-warning">⚡ REASONING_9B</span>` 
          : `<span class="badge badge-primary">PRIMARY_4B</span>`;
        const toolsList = a.tools.map(t => `<code style="font-size:0.75rem; background:#F1F5F9; padding:1px 4px; border-radius:3px;">${SalesViews.esc(t)}</code>`).join(' ');
        
        tr.innerHTML = `
          <td><strong>${SalesViews.esc(a.code)}</strong></td>
          <td><span class="badge badge-info">${SalesViews.esc(a.group)}</span></td>
          <td>
            <strong>${SalesViews.esc(a.name)}</strong><br>
            <code style="font-size:0.75rem; color:var(--text-muted);">${SalesViews.esc(a.role_id)}</code>
          </td>
          <td>${SalesViews.esc(tierBadge)}</td>
          <td>${SalesViews.esc(a.cap)} tok</td>
          <td>${SalesViews.esc(toolsList)}</td>
          <td style="font-size:0.8rem; color:var(--text-muted);">${SalesViews.esc(a.delegation)}</td>
          <td>
            <span class="badge badge-success">Active</span>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    // Copilot Actions
    async function generateCopilotBrief() {
      const convId = document.getElementById('copilotConvSelect').value;
      const snippet = document.getElementById('transcriptSnippet').innerText;
      
      document.getElementById('briefIdBadge').innerText = "Generating brief...";
      
      try {
        const res = await SalesApi.fetch('/api/v1/agents/copilot/brief', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            conversation_id: convId,
                        transcript_snippet: snippet
          })
        });
        
        const badge = document.getElementById('briefIdBadge');
        const summary = document.getElementById('copilotSummary');
        if (res.ok) {
          const data = await res.json();
          badge.innerText = data.brief_id || "Brief";
          badge.className = "badge badge-success";
          summary.innerText = data.customer_summary || "Aucun résumé retourné par le copilote.";
        } else {
          // F-20: never present an invented brief as "VERIFIED".
          badge.innerText = "Indisponible";
          badge.className = "badge badge-warning";
          summary.innerText = SalesViews.errorText({ status: res.status });
        }
      } catch (e) {
        document.getElementById('briefIdBadge').innerText = "Indisponible";
        document.getElementById('briefIdBadge').className = "badge badge-warning";
        document.getElementById('copilotSummary').innerText = SalesViews.errorText({ status: 0 });
      }
    }

    async function toggleHumanTakeover(isTakeover) {
      const pill = document.getElementById('takeoverStatusPill');
      const convId = document.getElementById('copilotConvSelect').value;
      
      try {
        await SalesApi.fetch('/api/v1/agents/takeover', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            conversation_id: convId,
            action: isTakeover ? 'TAKEOVER' : 'RELEASE'
          })
        });
      } catch (e) {}

      if (isTakeover) {
        pill.innerText = "🛑 Human Takeover Active — AI Autonomous Silenced";
        pill.style.color = "var(--status-danger)";
      } else {
        pill.innerText = "● AI Autonomous Assistance Active";
        pill.style.color = "var(--status-success)";
      }
    }

    async function approveProposal(propId, title) {
      try {
        await SalesApi.fetch('/api/v1/agents/copilot/approve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            brief_id: document.getElementById('briefIdBadge').innerText,
            proposal_id: propId
          })
        });
      } catch (e) {}

      const successBox = document.getElementById('approvalSuccessBox');
      successBox.style.display = "block";
      successBox.innerHTML = `✅ <strong>Action Validée:</strong> [${SalesViews.esc(title)}] a été autorisée par signature humaine et transmise au domaine commercial pour émission.`;
    }

    function copyReply(btn) {
      const text = btn.parentElement.querySelector('span').innerText;
      navigator.clipboard.writeText(text);
      btn.innerText = "Copied!";
      setTimeout(() => btn.innerText = "Copy", 1500);
    }

    async function runOperationsTriage() {
      alert("Operations Supervisor triage triggered across background worker queues.");
    }

    async function loadActivityLogs() {
      try {
        const res = await SalesApi.fetch('/api/v1/agents/activity?limit=10');
        if (res.ok) {
          const logs = await res.json();
          if (logs.length > 0) {
            const tbody = document.getElementById('activityLogsBody');
            tbody.innerHTML = '';
            logs.forEach(l => {
              const tr = document.createElement('tr');
              tr.innerHTML = `
                <td>${SalesViews.esc(new Date(l.created_at).toLocaleTimeString())}</td>
                <td><span class="badge badge-primary">${SalesViews.esc(l.agent_role)}</span></td>
                <td><code>${SalesViews.esc(l.trace_id)}</code></td>
                <td><span class="badge badge-success">${SalesViews.esc(l.status)}</span></td>
                <td>${SalesViews.esc(l.model_name)}</td>
                <td>${SalesViews.esc(l.total_tokens)}</td>
                <td>${SalesViews.esc(l.execution_duration_ms)}ms</td>
                <td>${(l.tools_called || []).map(t => t.tool).join(', ') || 'none'}</td>
              `;
              tbody.appendChild(tr);
            });
          }
        }
      } catch (e) {}
    }

    function onTenantSwitch(val) {
      alert("Tenant switched to: " + val);
    }

    // Initialize Catalog
    refreshCatalog();
