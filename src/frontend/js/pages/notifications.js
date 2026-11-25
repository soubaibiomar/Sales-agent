/* Selia — Notifications: delivery history, templates, manual send and opt-out (STOP). */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const $ = (id) => document.getElementById(id);
  const CH = { WHATSAPP: 'WhatsApp', EMAIL: 'E-mail', SMS: 'SMS', VOICE: 'Téléphone', WEBCHAT: 'Web' };
  const CLS = { TRANSACTIONAL: 'Transactionnel', MARKETING: 'Marketing', SERVICE: 'Service', OTP: 'Code' };
  const OK = ['SENT', 'DELIVERED', 'SUCCESS'];

  // Show only the end of a recipient identifier (phone/e-mail) in the list.
  const mask = (v) => { const s = String(v || ''); return s.length > 6 ? '…' + s.slice(-6) : s; };

  function renderTemplates(tpl, ok) {
    const tbody = $('templateRows');
    if (!ok) { V.rowState(tbody, 5, 'error', 'Modèles indisponibles.'); return; }
    tbody.innerHTML = tpl.length ? tpl.map(t => '<tr><td data-label=""><code>' + V.esc(t.template_code) + '</code></td>' +
      '<td data-label="Canal">' + V.esc(CH[t.channel_type] || t.channel_type) + '</td><td data-label="Type">' + V.esc(CLS[t.message_class] || t.message_class) + '</td>' +
      '<td data-label="Langue">' + V.esc(t.language) + '</td><td data-label="Statut">' + V.pill(t.is_active ? 'ACTIVE' : 'INACTIVE') + '</td></tr>').join('')
      : '<tr><td colspan="5" class="data-state">Aucun modèle.</td></tr>';
  }

  function init() {
    let templates = [];
    const list = L.mount({
      url: '/api/v1/notifications/history', accountsUrl: false, lookups: { tpl: '/api/v1/notifications/templates' },
      cols: 6, dateField: 'created_at', noun: 'notifications', empty: 'Aucune notification envoyée.',
      onLoaded: (ctx) => { templates = ctx.tpl; renderTemplates(ctx.tpl, ctx.tplOk); },
      chips: [['all', 'Toutes', null], ['ok', 'Envoyées', OK], ['fail', 'Échecs', ['FAILED', 'DEAD_LETTER']], ['blocked', 'Bloquées', ['SUPPRESSED', 'OPTED_OUT', 'BLOCKED']]],
      search: (n) => [n.recipient_identifier, n.subject, n.channel_type].join(' '),
      kpis: (rows) => L.kpi('chat', '', 'Envoyées', rows.filter(n => OK.indexOf(n.status) !== -1).length) +
        L.kpi('target', 'terra', 'Échecs', rows.filter(n => ['FAILED', 'DEAD_LETTER'].indexOf(n.status) !== -1).length) +
        L.kpi('user', 'sand', 'Bloquées (désinscrits)', rows.filter(n => ['SUPPRESSED', 'OPTED_OUT', 'BLOCKED'].indexOf(n.status) !== -1).length) +
        L.kpi('doc', '', 'Modèles', templates.length),
      row: (n) => '<tr><td data-label=""><strong>' + V.esc(mask(n.recipient_identifier)) + '</strong></td>' +
        '<td data-label="Canal">' + V.esc(CH[n.channel_type] || n.channel_type) + '</td><td data-label="Type">' + V.esc(CLS[n.message_class] || n.message_class || '—') + '</td>' +
        '<td data-label="Sujet">' + V.esc(n.subject || '—') + (n.error_reason ? '<span class="cell-sub">' + V.esc(n.error_reason) + '</span>' : '') + '</td>' +
        '<td data-label="Date">' + V.esc(V.ago(n.sent_at || n.created_at)) + '</td><td data-label="Statut">' + V.pill(n.status) + '</td></tr>'
    });
    $('btnSend').addEventListener('click', () => window.SalesAI.openModal('sendModal'));
    $('btnOptOut').addEventListener('click', () => window.SalesAI.openModal('optModal'));
    $('sendModalForm').addEventListener('submit', (e) => {
      e.preventDefault();
      if (!$('nTo').value.trim() || !$('nContent').value.trim()) { e.target.querySelector('.form-error').textContent = 'Destinataire et message sont obligatoires.'; return; }
      L.submitForm(e.target, '/api/v1/notifications/send', { recipient_identifier: $('nTo').value.trim(), channel_type: $('nChannel').value,
        subject: $('nSubject').value.trim() || null, content: $('nContent').value.trim(), message_class: 'TRANSACTIONAL' }, 'Notification envoyée.', () => list.reload());
    });
    $('optModalForm').addEventListener('submit', (e) => {
      e.preventDefault();
      if (!$('oTo').value.trim()) { e.target.querySelector('.form-error').textContent = 'Le destinataire est obligatoire.'; return; }
      L.submitForm(e.target, '/api/v1/notifications/opt-out', { recipient_identifier: $('oTo').value.trim(), channel_type: $('oChannel').value, directive: 'STOP' },
        'Destinataire désinscrit : il ne recevra plus de messages sur ce canal.', () => list.reload());
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
