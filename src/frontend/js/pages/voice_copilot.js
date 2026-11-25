/* Selia — Copilote vocal manager. Questions go to POST /api/v1/voice/copilot/command;
 * sensitive actions return a preview and are only executed after a TOTP confirmation
 * (POST /api/v1/voice/copilot/confirm-action, verified server-side). Text via textContent. */
(function () {
  'use strict';
  const V = window.SalesViews, UI = window.SalesAI;
  const $ = (id) => document.getElementById(id);
  let pendingActionToken = null;

  function addMsg(type, text) {
    const div = document.createElement('div');
    div.className = 'msg ' + type;
    div.textContent = text;
    $('copilotFeed').appendChild(div);
    $('copilotFeed').scrollTop = $('copilotFeed').scrollHeight;
  }

  function addActionCard(preview) {
    const card = document.createElement('div');
    card.className = 'action-card';
    const title = document.createElement('strong'); title.textContent = 'Action sensible : confirmation requise';
    const summary = document.createElement('span'); summary.textContent = preview.summary || preview.action_type || '';
    const risk = document.createElement('span'); risk.className = 'cell-sub'; risk.textContent = 'Niveau de risque : ' + (preview.risk_level || '—');
    card.append(title, summary, risk);
    $('copilotFeed').appendChild(card);
  }

  async function send(text) {
    text = (text || $('commandInput').value).trim();
    if (!text) return;
    addMsg('manager', text);
    $('commandInput').value = '';
    $('sendBtn').disabled = true;
    const res = await V.getJson('/api/v1/voice/copilot/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command_text: text }) });
    $('sendBtn').disabled = false;
    if (!res.ok) { addMsg('system', res.status === 403 ? "Votre rôle n'a pas accès au copilote." : 'Commande refusée : ' + V.errorText(res)); return; }
    addMsg('copilot', res.data.insight_text || '');
    if (res.data.requires_confirmation && res.data.action_preview) {
      pendingActionToken = res.data.action_preview.action_token;
      addActionCard(res.data.action_preview);
      UI.openModal('mfaModal');
    }
  }

  async function confirm() {
    const code = $('mfaInput').value.trim();
    if (!pendingActionToken) return;
    if (!/^[0-9]{6}$/.test(code)) { addMsg('system', 'Saisissez le code à 6 chiffres pour confirmer.'); return; }
    const res = await V.getJson('/api/v1/voice/copilot/confirm-action', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action_token: pendingActionToken, totp_code: code, confirmed: true }) });
    $('mfaModal').hidden = true; $('mfaInput').value = '';
    if (!res.ok) { addMsg('system', 'Confirmation refusée : ' + V.errorText(res)); return; }
    pendingActionToken = null;
    addMsg('copilot', res.data.message || 'Action exécutée.');
  }

  function init() {
    $('sendBtn').addEventListener('click', () => send());
    $('commandInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
    document.querySelectorAll('[data-query]').forEach(b => b.addEventListener('click', () => send(b.getAttribute('data-query'))));
    $('confirmActionBtn').addEventListener('click', confirm);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
