/* Selia — Support & SAV: tickets (with creation) and return authorisations. */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const $ = (id) => document.getElementById(id);
  const ACTION = { REFUND: 'Remboursement', REPLACE: 'Échange', REPLACEMENT: 'Échange', REPAIR: 'Réparation', CREDIT: 'Avoir' };

  function renderRmas(rmas, ok) {
    const tbody = $('rmaRows');
    if (!ok) { V.rowState(tbody, 5, 'error', 'Retours indisponibles.'); return; }
    tbody.innerHTML = rmas.length ? rmas.map(r => '<tr><td data-label=""><strong>' + V.esc(r.rma_number) + '</strong></td>' +
      '<td data-label="Motif">' + V.esc(r.reason || '—') + '</td><td data-label="Action demandée">' + V.esc(ACTION[r.requested_action] || r.requested_action || '—') + '</td>' +
      '<td data-label="Remboursement (MAD)" class="num">' + V.esc(r.refund_amount_cents ? V.money(r.refund_amount_cents, '').trim() : '—') + '</td>' +
      '<td data-label="Statut">' + V.pill(r.status) + '</td></tr>').join('') : '<tr><td colspan="5" class="data-state">Aucun retour.</td></tr>';
  }

  function init() {
    const list = L.mount({
      url: '/api/v1/support/tickets', lookups: { rmas: '/api/v1/support/rmas' }, cols: 6, dateField: 'created_at', noun: 'tickets',
      empty: 'Aucun ticket. Tout est sous contrôle.',
      onLoaded: (ctx) => {
        renderRmas(ctx.rmas, ctx.rmasOk);
        $('tAccount').innerHTML = '<option value="">Sans client</option>' + Array.from(ctx.names.entries())
          .map(([id, name]) => '<option value="' + V.esc(id) + '">' + V.esc(name) + '</option>').join('');
      },
      chips: [['all', 'Tous', null], ['open', 'Ouverts', ['OPEN']], ['progress', 'En cours', ['IN_PROGRESS']], ['done', 'Résolus', ['RESOLVED', 'CLOSED']]],
      search: (t, names) => [t.ticket_number, t.subject, names.get(t.account_id)].join(' '),
      kpis: (rows, names, ctx) => {
        const open = rows.filter(t => ['OPEN', 'IN_PROGRESS'].indexOf(t.status) !== -1);
        return L.kpi('chat', '', 'Tickets ouverts', open.length) +
          L.kpi('target', 'terra', 'Urgents', open.filter(t => ['HIGH', 'URGENT', 'CRITICAL'].indexOf(t.priority) !== -1).length) +
          L.kpi('doc', '', 'Résolus', rows.filter(t => ['RESOLVED', 'CLOSED'].indexOf(t.status) !== -1).length) +
          L.kpi('cart', 'sand', 'Retours (RMA)', (ctx.rmas || []).length);
      },
      row: (t, names) => '<tr><td data-label=""><strong>' + V.esc(t.ticket_number) + '</strong></td>' +
        '<td data-label="Sujet">' + V.esc(t.subject) + '</td><td data-label="Client">' + V.esc(names.get(t.account_id) || '—') + '</td>' +
        '<td data-label="Priorité">' + V.pill(t.priority) + '</td><td data-label="Créé le">' + V.esc(V.ago(t.created_at)) + '</td>' +
        '<td data-label="Statut">' + V.pill(t.status) + '</td></tr>'
    });
    $('btnNew').addEventListener('click', () => window.SalesAI.openModal('newModal'));
    $('newModalForm').addEventListener('submit', (e) => {
      e.preventDefault();
      if (!$('tSubject').value.trim() || !$('tDesc').value.trim()) { e.target.querySelector('.form-error').textContent = 'Sujet et description sont obligatoires.'; return; }
      L.submitForm(e.target, '/api/v1/support/tickets', {
        subject: $('tSubject').value.trim(), description: $('tDesc').value.trim(), account_id: $('tAccount').value || null,
        priority: $('tPriority').value, category: $('tCategory').value
      }, 'Ticket créé.', () => list.reload());
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
