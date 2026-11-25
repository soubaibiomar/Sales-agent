/* Selia — Approbations: pending quote approvals with real decisions
 * (POST /api/v1/approvals/{id}/decide). Approving requires a TOTP code (server-verified
 * step-up MFA); rejecting requires a reason. */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList, UI = window.SalesAI;
  const $ = (id) => document.getElementById(id);
  let pending = [], quotes = new Map(), names = new Map(), current = null;

  function render() {
    const total = pending.reduce((n, a) => n + ((quotes.get(a.quote_id) || {}).grand_total_cents || 0), 0);
    const oldest = pending.reduce((m, a) => Math.min(m, new Date(a.requested_at).getTime()), Date.now());
    $('kpis').innerHTML = L.kpi('target', 'terra', 'En attente', pending.length) +
      L.kpi('chart', 'sand', 'Montant à valider', V.esc(V.amount(total)) + '<small>MAD</small>') +
      L.kpi('calendar', '', 'Plus ancienne', pending.length ? V.esc(V.ago(new Date(oldest).toISOString())) : '—');
    $('approvalList').innerHTML = pending.length ? pending.map(a => {
      const q = quotes.get(a.quote_id) || {};
      return '<article class="card approval-card"><div class="approval-head"><div><strong>' + V.esc(q.quote_number || 'Devis') + '</strong>' +
        '<span class="cell-sub">' + V.esc(names.get(q.account_id) || 'Client non renseigné') + '</span></div>' + V.pill('PENDING_APPROVAL') + '</div>' +
        '<span class="approval-amount">' + V.esc(q.grand_total_cents != null ? V.money(q.grand_total_cents, q.currency) : '—') + '</span>' +
        (q.approval_reason ? '<p class="approval-reason">' + V.esc(q.approval_reason) + '</p>' : '') +
        '<div class="approval-meta"><span>Version ' + V.esc(a.quote_version) + '</span><span>Demandée ' + V.esc(V.ago(a.requested_at).toLowerCase()) + '</span>' +
        (q.margin_percent != null ? '<span>Marge ' + V.esc(q.margin_percent) + ' %</span>' : '') + '</div>' +
        '<div class="approval-actions"><button type="button" class="btn btn-outline" data-reject="' + V.esc(a.id) + '">Refuser</button>' +
        '<button type="button" class="btn btn-primary" data-approve="' + V.esc(a.id) + '">Approuver</button></div></article>';
    }).join('') : '<p class="data-state">Aucune demande en attente. Tous les devis sont dans vos seuils.</p>';
  }

  async function load() {
    const [ap, qs, acc] = await Promise.all([V.getJson('/api/v1/approvals/pending'), V.getJson('/api/v1/quotes?limit=500'), V.getJson('/api/v1/crm/accounts?limit=500')]);
    if (!ap.ok) { $('approvalList').innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(ap)) + '</p>'; $('kpis').innerHTML = ''; return; }
    pending = V.list(ap.data);
    quotes = new Map((qs.ok ? V.list(qs.data) : []).map(q => [q.id, q]));
    names = new Map((acc.ok ? V.list(acc.data) : []).map(a => [a.id, a.name]));
    render();
  }

  function decide(form, payload, message) {
    return L.submitForm(form, '/api/v1/approvals/' + encodeURIComponent(current.id) + '/decide', payload, message, load);
  }

  function init() {
    $('approvalList').addEventListener('click', (e) => {
      const a = e.target.closest('[data-approve]'), r = e.target.closest('[data-reject]');
      if (!a && !r) return;
      current = pending.find(p => p.id === (a || r).getAttribute(a ? 'data-approve' : 'data-reject'));
      if (!current) return;
      if (a) {
        const q = quotes.get(current.quote_id) || {};
        $('approveMeta').textContent = (q.quote_number || 'Devis') + ' — ' + (q.grand_total_cents != null ? V.money(q.grand_total_cents, q.currency) : '');
        UI.openModal('approveModal');
      } else UI.openModal('rejectModal');
    });
    $('approveForm').addEventListener('submit', (e) => {
      e.preventDefault();
      const code = $('mfaCode').value.trim();
      if (!/^[0-9]{6}$/.test(code)) { e.target.querySelector('.form-error').textContent = 'Saisissez le code à 6 chiffres.'; return; }
      decide(e.target, { decision: 'APPROVED', mfa_code: code }, 'Devis approuvé.');
    });
    $('rejectForm').addEventListener('submit', (e) => {
      e.preventDefault();
      const reason = $('rejectReason').value.trim();
      if (!reason) { e.target.querySelector('.form-error').textContent = 'Le motif est obligatoire.'; return; }
      decide(e.target, { decision: 'REJECTED', reason: reason }, 'Devis refusé.');
    });
    load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
