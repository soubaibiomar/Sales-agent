/**
 * Shared rendering helpers for live data (F-20 / F-32).
 * - esc(): every API value is HTML-escaped before it reaches innerHTML (stored-XSS defence).
 * - rowState(): loading / empty / error rows instead of leaving hardcoded demo rows on screen.
 * - markDemo(): visibly labels widgets that still show illustrative, non-live content.
 */
(function () {
  'use strict';

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"'`]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' }[c];
    });
  }

  function money(cents, currency) {
    var n = Number(cents || 0) / 100;
    return n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ' + (currency || 'MAD');
  }

  function date(iso) {
    if (!iso) { return '—'; }
    var d = new Date(iso);
    return isNaN(d.getTime()) ? '—' : d.toLocaleDateString('fr-FR');
  }

  function rowState(tbody, colspan, kind, text) {
    if (!tbody) { return; }
    tbody.innerHTML = '<tr><td colspan="' + Number(colspan) + '" class="data-state data-state--' + esc(kind) + '"' +
      (kind === 'error' ? ' role="alert"' : ' role="status"') + '>' + esc(text) + '</td></tr>';
  }

  /** Fetch JSON through SalesApi; resolves {ok, status, data}. */
  function getJson(url, init) {
    return window.SalesApi.fetch(url, init).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (data) { return { ok: r.ok, status: r.status, data: data }; });
    }).catch(function () { return { ok: false, status: 0, data: null }; });
  }

  function errorText(res) {
    if (res.status === 403) { return "Accès refusé : votre rôle ne permet pas d'afficher ces données."; }
    if (res.status === 0) { return 'Service indisponible. Vérifiez votre connexion et réessayez.'; }
    return 'Impossible de charger les données (erreur ' + res.status + ').';
  }

  function markDemo(el, label) {
    if (!el || el.querySelector('.demo-chip')) { return; }
    var chip = document.createElement('span');
    chip.className = 'demo-chip';
    chip.textContent = label || "Données d'exemple";
    chip.title = 'Ce widget affiche un contenu illustratif, non connecté aux données réelles.';
    el.insertBefore(chip, el.firstChild);
  }

  // Pages not yet connected to the API carry <body data-demo-page>: say so on screen (F-20).
  function markDemoPage() {
    if (!document.body || !document.body.hasAttribute('data-demo-page')) { return; }
    var host = document.querySelector('.content-wrapper') || document.body;
    if (host.querySelector('.demo-page-banner')) { return; }
    var banner = document.createElement('div');
    banner.className = 'demo-page-banner';
    banner.setAttribute('role', 'note');
    banner.textContent = "Page de démonstration : les données affichées sont des exemples et ne proviennent pas de votre organisation.";
    host.insertBefore(banner, host.firstChild);
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', markDemoPage); } else { markDemoPage(); }

  window.SalesViews = { esc: esc, money: money, date: date, rowState: rowState, getJson: getJson, errorText: errorText, markDemo: markDemo };
})();
