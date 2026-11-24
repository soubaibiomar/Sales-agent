/* Extracted from pipeline.html by scripts/frontend_csp_build.py */
const STAGES = [
      { id: "DISCOVERY", title: "Prospection", icon: "🎯", color: "#64748B" },
      { id: "QUALIFICATION", title: "Qualification", icon: "👥", color: "#10B981" },
      { id: "PROPOSAL", title: "Proposition", icon: "📄", color: "#2563EB" },
      { id: "NEGOTIATION", title: "Négociation", icon: "🤝", color: "#D97706" },
      { id: "CLOSED_WON", title: "Gagné", icon: "🏆", color: "#0A3A2A" },
      { id: "CLOSED_LOST", title: "Perdu", icon: "✕", color: "#DC2626" }
    ];

    async function loadPipeline() {
      const board = document.getElementById("kanbanBoard");
      if (board) board.innerHTML = '<div class="data-state data-state--loading" role="status">Chargement du pipeline…</div>';
      const res = await SalesViews.getJson("/api/v1/crm/pipeline");
      if (!res.ok || !res.data) {
        // No invented "demo" deals on failure (F-20): show the real error.
        if (board) board.innerHTML = '<div class="data-state data-state--error" role="alert">' + SalesViews.esc(SalesViews.errorText(res)) + '</div>';
        return;
      }
      renderKanban(res.data.stages || {});
    }

    function renderKanban(stageData) {
      const container = document.getElementById("kanbanBoard");
      container.innerHTML = "";
      STAGES.forEach(st => {
        const colData = stageData[st.id] || { opportunities: [], count: 0 };
        const col = document.createElement("div");
        col.className = "kanban-column";
        col.innerHTML = `
          <div class="kanban-col-header">
            <span class="kanban-col-title">
              <span>${SalesViews.esc(st.icon)}</span> ${SalesViews.esc(st.title)}
            </span>
            <span class="badge" style="background:#E2ECE6; color:#0A3A2A; font-weight:700;">${SalesViews.esc(colData.count)}</span>
          </div>
          <div class="kanban-cards-stream">
            ${colData.opportunities.map(opp => `
              <div class="deal-card" data-href="quote_builder.html?opp_id=${SalesViews.esc(encodeURIComponent(opp.id))}" tabindex="0" role="link">
                <div style="font-weight:700; font-size:13px; color:#17251F;">${SalesViews.esc(opp.title)}</div>
                <div style="font-size:11px; color:#66756D;">🏢 ${SalesViews.esc(opp.client || 'Client d\'affaires')}</div>
                <div class="deal-amount">${SalesViews.esc((opp.amount_cents / 100).toLocaleString('fr-FR', {minimumFractionDigits: 2}))} <span style="font-size:11px; font-weight:500;">${SalesViews.esc(opp.currency)}</span></div>
                <div class="progress-bar-bg">
                  <div class="progress-bar-fill" style="width:${SalesViews.esc(opp.probability_percent)}%;"></div>
                </div>
                <div class="deal-footer">
                  <span>Probabilité: <strong>${SalesViews.esc(opp.probability_percent)}%</strong></span>
                  <span>#${SalesViews.esc(opp.id)}</span>
                </div>
              </div>
            `).join("")}
          </div>
        `;
        container.appendChild(col);
      });
    }

    function openNewOppModal() { document.getElementById("oppModal").style.display = "flex"; }
    function closeModal() { document.getElementById("oppModal").style.display = "none"; }
    async function submitNewOpp() {
      const title = document.getElementById("oppTitle").value.trim();
      const amount = parseFloat(document.getElementById("oppAmount").value) || 0;
      if (!title) return alert("Veuillez saisir un titre d'opportunité.");
      closeModal();
      if (window.SalesAI) window.SalesAI.showToast(`Opportunité créée : ${title}`);
      loadPipeline();
    }

    loadPipeline();

document.addEventListener('click', function (e) {
  var card = e.target.closest('.deal-card[data-href]');
  if (card) { window.location.href = card.getAttribute('data-href'); }
});
document.addEventListener('keydown', function (e) {
  var card = e.target.closest && e.target.closest('.deal-card[data-href]');
  if (card && e.key === 'Enter') { window.location.href = card.getAttribute('data-href'); }
});
