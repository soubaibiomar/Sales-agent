/* Approvals center: live pending approvals and real decisions (F-20).
 * Previously "Valider avec MFA" only displayed a toast claiming the approval was recorded;
 * no request was sent. Now decisions go to POST /api/v1/approvals/{id}/decide and the
 * TOTP code is verified server-side (F-04). */
(function () {
  'use strict';
  var V = window.SalesViews;
  var listEl = null;
  var pendingId = null;

  function render(items) {
    if (!items.length) {
      listEl.innerHTML = '<div class="data-state data-state--empty" role="status">Aucune approbation en attente.</div>';
      return;
    }
    listEl.innerHTML = items.map(function (a) {
      return '<div class="approval-card-item">' +
        '<div class="approval-card-body">' +
        '<div class="approval-card-title">Devis ' + V.esc(a.quote_id) + ' — version ' + V.esc(a.quote_version) + '</div>' +
        '<div class="approval-card-meta">Empreinte des conditions : <code>' + V.esc(String(a.terms_hash || '').slice(0, 12)) + '…</code></div>' +
        '<div class="approval-card-meta">Demandé par ' + V.esc(a.requested_by_user_id) + ' le ' + V.esc(V.date(a.requested_at)) +
        ' • l\'auto-approbation est refusée par le serveur</div>' +
        '</div>' +
        '<div class="approval-card-actions">' +
        '<button class="btn btn-outline btn-danger-outline" data-reject="' + V.esc(a.id) + '">Rejeter</button>' +
        '<button class="btn btn-primary" data-approve="' + V.esc(a.id) + '">Valider avec MFA</button>' +
        '</div></div>';
    }).join('');
  }

  async function load() {
    listEl.innerHTML = '<div class="data-state data-state--loading" role="status">Chargement des approbations…</div>';
    var res = await V.getJson('/api/v1/approvals/pending');
    if (!res.ok) {
      listEl.innerHTML = '<div class="data-state data-state--error" role="alert">' + V.esc(V.errorText(res)) + '</div>';
      return;
    }
    render(Array.isArray(res.data) ? res.data : []);
  }

  async function decide(id, decision, payload) {
    var res = await V.getJson('/api/v1/approvals/' + encodeURIComponent(id) + '/decide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ decision: decision }, payload))
    });
    var toast = window.SalesAI && window.SalesAI.showToast ? window.SalesAI.showToast : function (m) { window.alert(m); };
    if (res.ok) {
      toast(decision === 'APPROVED' ? 'Approbation enregistrée.' : 'Rejet enregistré.');
    } else if (res.status === 403) {
      var detail = res.data && res.data.detail;
      toast((detail && (detail.error || detail)) || 'Refusé : code MFA invalide ou approbation non autorisée.');
    } else {
      toast('Échec de la décision : ' + V.errorText(res));
    }
    load();
  }

  // Override the page's former toast-only handlers (still referenced by the modal buttons).
  window.openMfaModal = function (id) {
    pendingId = id;
    document.getElementById('mfaModal').style.display = 'flex';
    var input = document.getElementById('mfaCode');
    input.value = '';
    input.focus();
  };
  window.closeMfaModal = function () {
    document.getElementById('mfaModal').style.display = 'none';
    pendingId = null;
  };
  window.submitMfaApproval = function () {
    var code = document.getElementById('mfaCode').value.trim();
    if (!/^[0-9]{6}$/.test(code)) { window.alert('Veuillez saisir un code TOTP à 6 chiffres.'); return; }
    var id = pendingId;
    window.closeMfaModal();
    decide(id, 'APPROVED', { mfa_code: code });
  };
  window.rejectApproval = function (id) {
    var reason = window.prompt('Motif du rejet :');
    if (reason) { decide(id, 'REJECTED', { reason: reason }); }
  };

  function init() {
    var first = document.querySelector('.approval-card-item');
    listEl = first ? first.parentElement : document.querySelector('main');
    // Remove the hardcoded demo approvals; keep the section header.
    listEl.querySelectorAll('.approval-card-item').forEach(function (el) { el.remove(); });
    var holder = document.createElement('div');
    holder.className = 'approval-live-list';
    listEl.appendChild(holder);
    listEl = holder;
    listEl.addEventListener('click', function (e) {
      var a = e.target.closest('[data-approve]');
      if (a) { window.openMfaModal(a.getAttribute('data-approve')); return; }
      var r = e.target.closest('[data-reject]');
      if (r) { window.rejectApproval(r.getAttribute('data-reject')); }
    });
    var badge = document.querySelector('.badge.badge-warning');
    if (badge && /dérogations/.test(badge.textContent)) { badge.remove(); }
    load();
  }

  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
