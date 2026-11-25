/* Unified inbox: live conversations, timeline and agent replies (F-20).
 * Previously the list and thread were hardcoded and "send" only appended the typed text
 * to the page (unescaped, never sent). Now: GET /api/v1/inbox/conversations,
 * GET .../timeline, POST .../reply. All message content is rendered as text. */
(function () {
  'use strict';
  var V = window.SalesViews;
  var current = null;

  function initials(name) {
    return String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(function (w) { return w[0].toUpperCase(); }).join('') || '?';
  }

  function listEl() { return document.querySelector('.threads-list'); }

  function renderList(convs) {
    var ul = listEl();
    if (!ul) { return; }
    if (!convs.length) {
      ul.innerHTML = '<li class="data-state data-state--empty" role="status">Aucune conversation.</li>';
      return;
    }
    ul.innerHTML = convs.map(function (c) {
      var name = c.contact_name || c.channel_identifier || 'Contact';
      return '<li class="thread-item" data-conversation="' + V.esc(c.id) + '" tabindex="0">' +
        '<div class="thread-avatar">' + V.esc(initials(name)) + '</div>' +
        '<div class="thread-content"><div class="thread-top"><span class="thread-name">' + V.esc(name) + '</span>' +
        '<span class="thread-time">' + V.esc(V.date(c.last_message_at)) + '</span></div>' +
        '<div class="thread-snippet">' + V.esc(c.channel_type) + ' • ' + V.esc(c.status) + (c.is_ai_silenced ? ' • humain' : '') + '</div>' +
        '<div class="thread-bottom"><div class="thread-tags">' + (c.unread_count ? '<span class="badge badge-info">' + V.esc(c.unread_count) + '</span>' : '') +
        '</div></div></div></li>';
    }).join('');
  }

  async function loadList() {
    var ul = listEl();
    if (ul) { ul.innerHTML = '<li class="data-state data-state--loading" role="status">Chargement des conversations…</li>'; }
    var res = await V.getJson('/api/v1/inbox/conversations');
    if (!res.ok) {
      if (ul) { ul.innerHTML = '<li class="data-state data-state--error" role="alert">' + V.esc(V.errorText(res)) + '</li>'; }
      return;
    }
    var convs = (res.data && res.data.conversations) || [];
    renderList(convs);
    if (convs.length) { select(convs[0]); }
    else { var s = document.getElementById('chatStream'); if (s) { s.innerHTML = ''; } }
  }

  async function select(conv) {
    current = conv;
    document.querySelectorAll('.thread-item').forEach(function (li) {
      li.classList.toggle('active', li.getAttribute('data-conversation') === conv.id);
    });
    var title = document.querySelector('.chat-header-title');
    if (title) { title.textContent = conv.contact_name || conv.channel_identifier || 'Contact'; }
    var stream = document.getElementById('chatStream');
    stream.innerHTML = '<div class="data-state data-state--loading" role="status">Chargement…</div>';
    var res = await V.getJson('/api/v1/inbox/conversations/' + encodeURIComponent(conv.id) + '/timeline');
    if (!res.ok) { stream.innerHTML = '<div class="data-state data-state--error" role="alert">' + V.esc(V.errorText(res)) + '</div>'; return; }
    var msgs = (res.data && res.data.messages) || [];
    if (!msgs.length) { stream.innerHTML = '<div class="data-state data-state--empty" role="status">Aucun message.</div>'; return; }
    stream.innerHTML = msgs.map(function (m) {
      var outbound = m.sender_type !== 'CUSTOMER' && m.sender_type !== 'CONTACT';
      return '<div class="msg-group ' + (outbound ? 'outbound' : 'inbound') + '"><div>' +
        '<div class="msg-bubble">' + V.esc(m.content_redacted || m.content) + '</div>' +
        '<div class="msg-meta">' + V.esc(m.sender_type) + ' • ' + V.esc(new Date(m.created_at).toLocaleString('fr-FR')) + '</div>' +
        '</div></div>';
    }).join('');
    stream.scrollTop = stream.scrollHeight;
  }

  async function sendMessage() {
    var input = document.getElementById('chatInput');
    var text = input.value.trim();
    if (!text || !current) { return; }
    input.disabled = true;
    var res = await V.getJson('/api/v1/inbox/conversations/' + encodeURIComponent(current.id) + '/reply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: text })
    });
    input.disabled = false;
    if (res.ok) { input.value = ''; select(current); }
    else if (window.SalesAI && window.SalesAI.showToast) { window.SalesAI.showToast("Envoi impossible : " + V.errorText(res)); }
  }

  // Kept global: referenced by the suggestion buttons' handlers.
  window.applySuggestion = function (text) {
    var input = document.getElementById('chatInput');
    input.value = text;
    input.focus();
  };

  function init() {
    document.getElementById('btnSendChat').addEventListener('click', sendMessage);
    document.getElementById('chatInput').addEventListener('keydown', function (e) { if (e.key === 'Enter') { sendMessage(); } });
    var ul = listEl();
    if (ul) {
      ul.addEventListener('click', function (e) {
        var li = e.target.closest('[data-conversation]');
        if (li) { select({ id: li.getAttribute('data-conversation'), contact_name: li.querySelector('.thread-name').textContent }); }
      });
    }
    loadList();
  }

  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
