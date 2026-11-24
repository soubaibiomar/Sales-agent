/* Login page: password + optional TOTP step-up, using SalesApi (see js/api_client.js). */
(function () {
  'use strict';
  var params = new URLSearchParams(window.location.search);
  var next = params.get('next') || 'index.html';
  // Only same-origin relative page names are accepted as a redirect target (no open redirect).
  if (!/^[a-z_]+\.html(\?[^#]*)?$/.test(next)) { next = 'index.html'; }

  if (window.SalesApi.isAuthenticated()) { window.location.replace(next); return; }

  var loginForm = document.getElementById('loginForm');
  var mfaForm = document.getElementById('mfaForm');
  var message = document.getElementById('loginMessage');
  var tempToken = null;

  function show(text) { message.textContent = text || ''; }

  loginForm.addEventListener('submit', function (e) {
    e.preventDefault();
    show('');
    var email = document.getElementById('email').value.trim();
    var password = document.getElementById('password').value;
    var tenantId = document.getElementById('tenantId').value.trim();
    if (!email || !password) { show('Veuillez saisir votre e-mail et votre mot de passe.'); return; }
    var btn = document.getElementById('loginSubmit');
    btn.disabled = true; btn.textContent = 'Connexion…';
    window.SalesApi.login(email, password, tenantId).then(function (res) {
      if (res.ok && res.data.mfa_required) {
        tempToken = res.data.temp_token;
        loginForm.hidden = true; mfaForm.hidden = false;
        document.getElementById('mfaCode').focus();
      } else if (res.ok) {
        window.location.replace(next);
      } else if (res.status === 403) {
        show('Compte temporairement verrouillé ou désactivé.');
      } else {
        show('E-mail ou mot de passe incorrect.');
      }
    }).catch(function () {
      show('Service indisponible. Réessayez dans un instant.');
    }).finally(function () { btn.disabled = false; btn.textContent = 'Se connecter'; });
  });

  mfaForm.addEventListener('submit', function (e) {
    e.preventDefault();
    var code = document.getElementById('mfaCode').value.trim();
    if (!/^[0-9]{6}$/.test(code)) { show('Le code doit contenir 6 chiffres.'); return; }
    window.SalesApi.verifyMfa(tempToken, code).then(function (res) {
      if (res.ok) { window.location.replace(next); } else { show('Code invalide.'); }
    }).catch(function () { show('Service indisponible.'); });
  });
})();
