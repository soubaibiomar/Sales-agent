/* Selia — Profil & Paramètres: /users/me (read + display-name edit), /tenants/current,
 * team from /users (when the role allows it), MFA status. */
(function () {
  'use strict';
  const V = window.SalesViews, UI = window.SalesAI;
  const $ = (id) => document.getElementById(id);
  const ROLE = { super_admin: 'Super administrateur', tenant_admin: 'Administrateur', sales_manager: 'Responsable commercial', sales_rep: 'Commercial',
    sales_representative: 'Commercial', support_agent: 'Agent support', inventory_manager: 'Gestionnaire stock', customer: 'Client' };
  const roleLabel = (roles) => (roles || []).map(r => ROLE[r] || r).filter((v, i, a) => a.indexOf(v) === i).join(', ') || '—';

  function selectTab(name) {
    document.querySelectorAll('[role="tab"]').forEach(t => t.setAttribute('aria-selected', String(t.getAttribute('data-tab') === name)));
    document.querySelectorAll('.tab-panel').forEach(p => { p.hidden = p.id !== 'panel-' + name; });
  }

  function paintMe(me) {
    $('pAvatar').textContent = V.initials(me.full_name || me.email);
    $('pName').textContent = me.full_name || me.email;
    $('pRole').textContent = roleLabel(me.roles);
    $('fName').value = me.full_name || '';
    $('fEmail').value = me.email || '';
    $('fRole').value = roleLabel(me.roles);
    $('mfaText').textContent = me.mfa_enabled ? 'Activée : un code est demandé à chaque connexion.' : "Désactivée : activez-la depuis votre application d'authentification.";
    $('mfaPill').innerHTML = me.mfa_enabled ? V.pill('Activée', 'ok') : V.pill('Désactivée', 'warn');
  }

  async function loadMe() {
    const res = await V.getJson('/api/v1/users/me');
    if (!res.ok) { $('profileError').textContent = V.errorText(res); return; }
    paintMe(res.data);
  }

  async function loadTenant() {
    const res = await V.getJson('/api/v1/tenants/current');
    $('tenantInfo').innerHTML = res.ok
      ? '<dt>Raison sociale</dt><dd>' + V.esc(res.data.name) + '</dd><dt>Identifiant</dt><dd>' + V.esc(res.data.slug) + '</dd>' +
        '<dt>Offre</dt><dd>' + V.esc(res.data.tier || '—') + '</dd><dt>Statut</dt><dd>' + (res.data.is_active ? V.pill('Actif', 'ok') : V.pill('Inactif', 'neutral')) + '</dd>' +
        '<dt>Client depuis</dt><dd>' + V.esc(V.date(res.data.created_at)) + '</dd>'
      : '<dt class="data-state data-state--error">' + V.esc(V.errorText(res)) + '</dt>';
  }

  async function loadTeam() {
    const res = await V.getJson('/api/v1/users');
    if (!res.ok) { V.rowState($('teamRows'), 4, res.status === 403 ? 'empty' : 'error', res.status === 403 ? "Votre rôle ne permet pas d'afficher l'équipe." : V.errorText(res)); return; }
    const users = V.list(res.data);
    $('teamRows').innerHTML = users.length ? users.map(u => '<tr><td data-label=""><span class="cell-entity"><span class="avatar-initials ' + V.tone(u.id) + '">' +
      V.esc(V.initials(u.full_name || u.email)) + '</span><strong>' + V.esc(u.full_name || '—') + '</strong></span></td><td data-label="E-mail">' + V.esc(u.email) + '</td>' +
      '<td data-label="Rôle">' + V.esc(roleLabel(u.roles)) + '</td><td data-label="Statut">' + (u.is_active ? V.pill('Actif', 'ok') : V.pill('Inactif', 'neutral')) + '</td></tr>').join('')
      : '<tr><td colspan="4" class="data-state">Aucun membre.</td></tr>';
  }

  async function save(e) {
    e.preventDefault();
    const name = $('fName').value.trim();
    const err = $('profileError');
    if (!name) { err.textContent = 'Le nom complet est obligatoire.'; return; }
    err.textContent = '';
    const res = await V.getJson('/api/v1/users/me', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ full_name: name }) });
    if (!res.ok) { err.textContent = 'Enregistrement impossible : ' + V.errorText(res); return; }
    paintMe(res.data);
    window.SalesApi.updateUser({ full_name: res.data.full_name });
    UI.showToast('Profil mis à jour. Le nouveau nom apparaîtra partout au prochain chargement de page.');
  }

  function init() {
    document.querySelectorAll('[role="tab"]').forEach(t => t.addEventListener('click', () => selectTab(t.getAttribute('data-tab'))));
    $('profileForm').addEventListener('submit', save);
    const hash = location.hash.replace('#', '');
    if (['profil', 'entreprise', 'equipe', 'securite'].indexOf(hash) !== -1) selectTab(hash);
    loadMe(); loadTenant(); loadTeam();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
