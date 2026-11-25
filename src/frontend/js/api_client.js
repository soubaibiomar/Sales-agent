/**
 * SALES AI MANAGEMENT — AUTHENTICATED API CLIENT (inspection finding F-20)
 *
 * Every page talks to the backend through SalesApi.fetch:
 *  - the bearer access token issued by /api/v1/auth/login is attached automatically;
 *  - client-chosen tenant headers (X-Tenant-ID) and hardcoded tokens are stripped: the
 *    tenant always comes from the verified token on the server;
 *  - on 401 the refresh token is rotated once (/api/v1/auth/refresh, single-use tokens);
 *    if that fails the user is sent back to the login page.
 * Tokens live in sessionStorage (per tab, cleared when the tab closes), never in
 * localStorage. Pages without a session redirect to login.html.
 */
(function () {
  'use strict';

  var KEY = 'salesai.session';
  var LOGIN_PAGE = 'login.html';
  var PUBLIC_PAGES = ['login.html', 'quote_view.html'];

  function readSession() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch (e) { return null; }
  }

  function writeSession(tokens) {
    try { sessionStorage.setItem(KEY, JSON.stringify(tokens)); } catch (e) { /* storage blocked */ }
  }

  function clearSession() {
    try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ }
  }

  function decodeClaims(token) {
    try {
      var part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      return JSON.parse(decodeURIComponent(escape(atob(part))));
    } catch (e) { return null; }
  }

  function currentPage() {
    return window.location.pathname.split('/').pop() || 'index.html';
  }

  function goToLogin() {
    clearSession();
    if (currentPage() !== LOGIN_PAGE) {
      window.location.href = LOGIN_PAGE + '?next=' + encodeURIComponent(currentPage() + window.location.search);
    }
  }

  var refreshing = null;
  function refreshTokens() {
    var session = readSession();
    if (!session || !session.refresh_token) { return Promise.resolve(false); }
    if (!refreshing) {
      refreshing = window.fetch('/api/v1/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: session.refresh_token })
      }).then(function (r) {
        if (!r.ok) { return false; }
        return r.json().then(function (data) {
          writeSession({ access_token: data.access_token, refresh_token: data.refresh_token, user: data.user });
          return true;
        });
      }).catch(function () { return false; }).finally(function () { refreshing = null; });
    }
    return refreshing;
  }

  function buildHeaders(init) {
    var headers = new Headers((init && init.headers) || {});
    headers.delete('X-Tenant-ID');
    headers.delete('X-Tenant-Id');
    headers.delete('Authorization');
    var session = readSession();
    if (session && session.access_token) {
      headers.set('Authorization', 'Bearer ' + session.access_token);
    }
    return headers;
  }

  function apiFetch(url, init) {
    init = init || {};
    var first = Object.assign({}, init, { headers: buildHeaders(init) });
    return window.fetch(url, first).then(function (resp) {
      if (resp.status !== 401) { return resp; }
      return refreshTokens().then(function (ok) {
        if (!ok) { goToLogin(); return resp; }
        return window.fetch(url, Object.assign({}, init, { headers: buildHeaders(init) }));
      });
    });
  }

  function login(email, password, tenantId) {
    return window.fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ email: email, password: password }, tenantId ? { tenant_id: tenantId } : {}))
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) { return { ok: r.ok, status: r.status, data: data }; });
    }).then(function (res) {
      if (res.ok && res.data && !res.data.mfa_required) {
        writeSession({ access_token: res.data.access_token, refresh_token: res.data.refresh_token, user: res.data.user });
      }
      return res;
    });
  }

  function verifyMfa(tempToken, code) {
    return window.fetch('/api/v1/auth/mfa/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ temp_token: tempToken, mfa_code: code })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (r.ok) { writeSession({ access_token: data.access_token, refresh_token: data.refresh_token, user: data.user }); }
        return { ok: r.ok, status: r.status, data: data };
      });
    });
  }

  function logout() {
    var p = readSession() ? apiFetch('/api/v1/auth/logout', { method: 'POST' }).catch(function () {}) : Promise.resolve();
    return p.then(function () { clearSession(); window.location.href = LOGIN_PAGE; });
  }

  function user() {
    var session = readSession();
    if (!session) { return null; }
    var claims = decodeClaims(session.access_token) || {};
    var u = session.user || {};
    return {
      id: u.id || claims.sub,
      tenantId: u.tenant_id || claims.tenant_id,
      email: u.email || claims.email,
      fullName: u.full_name || claims.email || '',
      roles: u.roles || claims.roles || [],
      mfaVerified: !!claims.mfa_verified
    };
  }

  /** Refresh display fields (e.g. full name) of the cached session user after a profile edit.
   *  Only presentation data: tokens and claims are untouched; authorisation stays server-side. */
  function updateUser(fields) {
    var session = readSession();
    if (!session) { return; }
    session.user = session.user || {};
    if (fields && typeof fields.full_name === 'string') { session.user.full_name = fields.full_name; }
    writeSession(session);
  }

  /** Small helpers for loading / empty / error states. */
  function renderState(container, kind, message) {
    if (!container) { return; }
    container.innerHTML = '';
    var box = document.createElement('div');
    box.className = 'data-state data-state--' + kind;
    box.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    box.textContent = message;
    container.appendChild(box);
  }

  window.SalesApi = {
    fetch: apiFetch,
    login: login,
    verifyMfa: verifyMfa,
    logout: logout,
    user: user,
    updateUser: updateUser,
    isAuthenticated: function () { return !!readSession(); },
    renderState: renderState
  };

  // Auth guard: every application page needs a session (login & public quote view excepted).
  if (PUBLIC_PAGES.indexOf(currentPage()) === -1 && !readSession()) {
    goToLogin();
  }
})();
