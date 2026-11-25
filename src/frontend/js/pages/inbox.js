/* Selia — Conversations: live inbox (list, timeline, reply) and an on-demand AI copilot
 * brief (suggested reply, sentiment, objections, summary). Suggestions are drafts that are
 * only sent when the agent clicks "Envoyer" (AGENTS.md invariant 2). All text is escaped. */
(function () {
  'use strict';
  const V = window.SalesViews, UI = window.SalesAI;
  const $ = (id) => document.getElementById(id);
  const CHANNEL = { WHATSAPP: 'WhatsApp', WEBCHAT: 'Web', WEB: 'Web', EMAIL: 'E-mail', VOICE: 'Téléphone', SMS: 'SMS' };
  const SENT = { POSITIVE: ['Positif', 'ok'], NEUTRAL: ['Neutre', 'neutral'], NEGATIVE: ['Négatif', 'danger'], MIXED: ['Mitigé', 'warn'] };
  let convs = [], current = null, suggestion = '';

  function renderList() {
    const ch = $('channelFilter').value, st = $('statusFilter').value;
    const rows = convs.filter(c => (!ch || c.channel_type === ch) && (!st || c.status === st));
    $('convCount').textContent = '(' + rows.length + ')';
    $('liveCount').lastChild.textContent = ' Boîte en direct · ' + convs.filter(c => c.status === 'OPEN').length + ' actives';
    $('convList').innerHTML = rows.length ? rows.map(c => {
      const name = c.contact_name || c.channel_identifier || 'Contact';
      return '<li><button type="button" class="conv" data-conv="' + V.esc(c.id) + '" aria-current="' + (current && current.id === c.id) + '">' +
        '<span class="avatar-initials ' + V.tone(c.id) + '">' + V.esc(V.initials(name)) + '</span>' +
        '<span><span class="name">' + V.esc(name) + '</span><br><span class="chan">' + V.esc(CHANNEL[c.channel_type] || c.channel_type) + '</span></span>' +
        '<span class="time">' + V.esc(V.ago(c.last_message_at)) + '</span>' + (c.unread_count ? '<span class="unread" aria-label="Non lu"></span>' : '') + '</button></li>';
    }).join('') : '<li class="data-state">Aucune conversation.</li>';
  }

  async function loadList() {
    const res = await V.getJson('/api/v1/inbox/conversations');
    if (!res.ok) { $('convList').innerHTML = '<li class="data-state data-state--error" role="alert">' + V.esc(V.errorText(res)) + '</li>'; return; }
    convs = V.list(res.data, 'conversations');
    renderList();
    if (!current && convs.length) select(convs[0].id);
  }

  async function select(id) {
    current = convs.find(c => c.id === id);
    if (!current) return;
    renderList();
    const name = current.contact_name || current.channel_identifier || 'Contact';
    $('threadHead').innerHTML = '<span class="avatar-initials ' + V.tone(current.id) + '">' + V.esc(V.initials(name)) + '</span><span class="feed-main"><strong>' + V.esc(name) +
      '</strong><span>' + V.esc(CHANNEL[current.channel_type] || current.channel_type) + ' · depuis le ' + V.esc(V.date(current.created_at)) + '</span></span>' +
      '<span class="thread-status">' + V.pill(current.status) + (current.is_ai_silenced ? ' ' + V.pill('Agent humain', 'info') : '') + '</span>';
    $('replyInput').disabled = false; $('sendBtn').disabled = false; $('aiGenerate').disabled = false;
    $('aiSuggestion').innerHTML = '<p class="cell-sub">Générez une suggestion à partir de l’historique de la conversation.</p>';
    $('aiUse').disabled = true; $('aiSentiment').textContent = '—'; $('aiObjections').textContent = '—'; $('aiSummary').textContent = '—';
    const box = $('messages');
    box.innerHTML = '<p class="data-state">Chargement…</p>';
    const res = await V.getJson('/api/v1/inbox/conversations/' + encodeURIComponent(id) + '/timeline');
    if (!res.ok) { box.innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(res)) + '</p>'; return; }
    const msgs = V.list(res.data, 'messages');
    box.innerHTML = msgs.length ? msgs.map(m => {
      const inbound = m.sender_type === 'CUSTOMER' || m.sender_type === 'CONTACT';
      const sys = m.sender_type === 'SYSTEM';
      return '<div class="bubble ' + (sys ? 'sys' : inbound ? 'in' : 'out') + '">' + V.esc(m.content_redacted || m.content) +
        '<time>' + V.esc(new Date(m.created_at).toLocaleString('fr-FR', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })) + '</time></div>';
    }).join('') : '<p class="data-state">Aucun message.</p>';
    box.scrollTop = box.scrollHeight;
    $('composerHint').textContent = current.is_ai_silenced ? "L'IA est en pause : vous répondez en direct." : '';
  }

  async function send(e) {
    e.preventDefault();
    const text = $('replyInput').value.trim();
    if (!text || !current) return;
    $('sendBtn').disabled = true;
    const res = await V.getJson('/api/v1/inbox/conversations/' + encodeURIComponent(current.id) + '/reply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: text }) });
    $('sendBtn').disabled = false;
    if (!res.ok) { UI.showToast('Envoi impossible : ' + V.errorText(res)); return; }
    $('replyInput').value = '';
    select(current.id);
  }

  async function generate() {
    if (!current) return;
    const btn = $('aiGenerate');
    btn.disabled = true;
    $('aiSuggestion').innerHTML = '<p class="cell-sub">Analyse de la conversation…</p>';
    const transcript = Array.from($('messages').querySelectorAll('.bubble')).slice(-8).map(b => b.firstChild ? b.firstChild.textContent : '').join('\n');
    const res = await V.getJson('/api/v1/agents/copilot/brief', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_id: current.id, customer_id: current.contact_id || current.id, transcript_snippet: transcript.slice(0, 4000) }) });
    btn.disabled = false;
    if (!res.ok) {
      $('aiSuggestion').innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(res.status === 403 ? "Votre rôle n'a pas accès à l'assistant." : V.errorText(res)) + '</p>';
      return;
    }
    const b = res.data || {};
    suggestion = (b.suggested_replies || [])[0] || '';
    $('aiSuggestion').textContent = suggestion || 'Aucune suggestion pour cette conversation.';
    $('aiUse').disabled = !suggestion;
    const s = SENT[String(b.sentiment || '').toUpperCase()];
    $('aiSentiment').innerHTML = s ? V.pill(s[0], s[1]) : V.esc(b.sentiment || '—');
    $('aiObjections').textContent = (b.key_objections || []).length ? b.key_objections.join(' · ') : 'Aucune';
    $('aiSummary').textContent = b.customer_summary || '—';
  }

  function init() {
    $('convList').addEventListener('click', (e) => { const b = e.target.closest('[data-conv]'); if (b) select(b.getAttribute('data-conv')); });
    $('channelFilter').addEventListener('change', renderList);
    $('statusFilter').addEventListener('change', renderList);
    $('composer').addEventListener('submit', send);
    $('replyInput').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send(e); });
    $('aiGenerate').addEventListener('click', generate);
    $('aiUse').addEventListener('click', () => { $('replyInput').value = suggestion; $('replyInput').focus(); });
    loadList();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
