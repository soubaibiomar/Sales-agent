/* Selia — Gouvernance IA: model gateway health (/ai/health), knowledge base documents
 * (/ai/rag/documents, ingestion), and offline evaluations on demand (/ai/evaluations/run). */
(function () {
  'use strict';
  const V = window.SalesViews, UI = window.SalesAI, L = window.SeliaList;
  const $ = (id) => document.getElementById(id);
  const SRC = { POLICY: 'Politique', FAQ: 'FAQ', PRODUCT_SHEET: 'Fiche produit', PROCEDURE: 'Procédure' };
  const DOC = { INDEXED: ['Indexé', 'ok'], ACTIVE: ['Indexé', 'ok'], PENDING_EMBEDDING: ['En attente', 'warn'], QUARANTINED: ['Mis en quarantaine', 'danger'], TOMBSTONED: ['Retiré', 'neutral'] };
  const mb = (v) => (v == null ? '—' : Math.round(Number(v)).toLocaleString('fr-FR') + ' Mo');

  async function loadHealth() {
    const h = await V.getJson('/api/v1/ai/health');
    if (!h.ok) { $('kpis').innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(h)) + '</p>'; return; }
    const d = h.data;
    $('kpis').innerHTML = L.kpi('sparkle', '', 'Modèle principal', V.esc(d.primary_llm || '—'), 'Raisonnement : ' + (d.reasoning_llm || '—')) +
      L.kpi('target', d.active_gpu_model ? '' : 'sand', 'Modèle chargé (GPU)', V.esc(d.active_gpu_model || 'Aucun')) +
      L.kpi('settings', 'terra', 'Marge mémoire GPU', V.esc(mb(d.gpu_vram_headroom_mb))) + L.kpi('chart', 'sand', 'Marge mémoire vive', V.esc(mb(d.system_ram_headroom_mb)));
  }

  async function loadDocs() {
    const res = await V.getJson('/api/v1/ai/rag/documents');
    if (!res.ok) { V.rowState($('docRows'), 6, 'error', V.errorText(res)); return; }
    const docs = V.list(res.data);
    $('docRows').innerHTML = docs.length ? docs.map(d => {
      const st = DOC[String(d.status).toUpperCase()] || [d.status, 'neutral'];
      const roles = d.acl_roles || [];
      return '<tr><td data-label=""><strong>' + V.esc(d.title) + '</strong>' + (d.poison_reason ? '<span class="cell-sub">' + V.esc(d.poison_reason) + '</span>' : '') + '</td>' +
        '<td data-label="Source">' + V.esc(SRC[d.source_type] || d.source_type) + '</td>' +
        '<td data-label="Accès">' + V.esc(roles.indexOf('public') !== -1 || !roles.length ? 'Tout le monde' : 'Équipe interne') + '</td>' +
        '<td data-label="Segments" class="num">' + V.esc(d.chunk_count) + '</td><td data-label="Ajouté">' + V.esc(V.date(d.created_at)) + '</td>' +
        '<td data-label="Statut">' + V.pill(st[0], st[1]) + '</td></tr>';
    }).join('') : '<tr><td colspan="6" class="data-state">Aucun document : les agents répondent sans base de connaissances.</td></tr>';
  }

  async function evaluate() {
    const btn = $('btnEval'); btn.disabled = true;
    $('evalCard').hidden = false; $('evalBody').innerHTML = '<p class="data-state" role="status">Évaluation en cours…</p>';
    const res = await V.getJson('/api/v1/ai/evaluations/run');
    btn.disabled = false;
    if (!res.ok) { $('evalBody').innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(res)) + '</p>'; return; }
    const r = res.data || {};
    const cells = Object.keys(r).filter(k => typeof r[k] === 'number' || typeof r[k] === 'string' || typeof r[k] === 'boolean').slice(0, 12);
    $('evalWhen').textContent = 'à l’instant';
    $('evalBody').innerHTML = '<div class="eval-grid">' + cells.map(k => '<div><strong>' + V.esc(typeof r[k] === 'number' ? r[k].toLocaleString('fr-FR') : String(r[k])) + '</strong><span>' +
      V.esc(k.replace(/_/g, ' ')) + '</span></div>').join('') + '</div>';
  }

  function init() {
    $('btnEval').addEventListener('click', evaluate);
    $('btnDoc').addEventListener('click', () => UI.openModal('docModal'));
    $('docForm').addEventListener('submit', (e) => {
      e.preventDefault();
      if (!$('dTitle').value.trim() || !$('dContent').value.trim()) { e.target.querySelector('.form-error').textContent = 'Titre et contenu sont obligatoires.'; return; }
      L.submitForm(e.target, '/api/v1/ai/rag/documents', { title: $('dTitle').value.trim(), content: $('dContent').value.trim(), source_type: $('dSource').value,
        acl_roles: $('dAcl').value === 'public' ? ['public'] : ['tenant_admin', 'sales_manager', 'sales_rep', 'support_agent'] }, 'Document indexé.', loadDocs);
    });
    loadHealth(); loadDocs();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
