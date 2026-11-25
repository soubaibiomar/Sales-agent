/**
 * Shared rendering helpers for live data (F-20 / F-32).
 * - esc(): every API value is HTML-escaped before it reaches innerHTML (stored-XSS defence).
 * - rowState(): loading / empty / error rows instead of leaving hardcoded demo rows on screen.
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

  /** Whole-unit amount for KPI tiles: "1 410 077" (currency rendered separately). */
  function amount(cents) {
    return Math.round(Number(cents || 0) / 100).toLocaleString('fr-FR');
  }

  function initials(name) {
    return String(name || '?').split(/[\s.@-]+/).filter(Boolean).slice(0, 2).map(function (w) { return w[0].toUpperCase(); }).join('') || '?';
  }

  /** Deterministic avatar tone so a client keeps the same colour everywhere. */
  function tone(seed) {
    var h = 0; String(seed || '').split('').forEach(function (c) { h = (h * 31 + c.charCodeAt(0)) >>> 0; });
    return 'tone-' + (h % 3);
  }

  var STATUS = {
    // quotes
    DRAFT: ['Brouillon', 'neutral'], PRICED: ['Chiffré', 'info'], PENDING_APPROVAL: ['En attente', 'warn'], APPROVED: ['Approuvé', 'ok'],
    ISSUED: ['Émis', 'info'], SENT: ['Envoyé', 'info'], ACCEPTED: ['Accepté', 'ok'], REJECTED: ['Refusé', 'danger'], EXPIRED: ['Expiré', 'neutral'],
    // orders
    CONFIRMED: ['Confirmée', 'info'], PROCESSING: ['En préparation', 'warn'], IN_PREPARATION: ['En préparation', 'warn'],
    SHIPPED: ['En cours', 'info'], DELIVERED: ['Livrée', 'ok'], COMPLETED: ['Terminée', 'ok'], CANCELLED: ['Annulée', 'danger'],
    PENDING_PAYMENT: ['Paiement en attente', 'warn'], PAID: ['Payée', 'ok'],
    // appointments
    SCHEDULED: ['À venir', 'warn'], RESCHEDULED: ['Reportée', 'warn'], NO_SHOW: ['Absent', 'danger'],
    // opportunities
    DISCOVERY: ['Prospection', 'neutral'], QUALIFICATION: ['Qualification', 'info'], PROPOSAL: ['Proposition', 'warn'],
    NEGOTIATION: ['Négociation', 'warn'], CLOSED_WON: ['Gagnée', 'ok'], CLOSED_LOST: ['Perdue', 'danger'],
    // logistics
    CREATED: ['Créée', 'neutral'], PICKING: ['Préparation', 'warn'], PACKED: ['Emballée', 'warn'], IN_TRANSIT: ['En transit', 'info'],
    OUT_FOR_DELIVERY: ['En livraison', 'info'], FAILED: ['Échec', 'danger'], RETURNED: ['Retournée', 'neutral'],
    // procurement / returns / payments
    PARTIALLY_RECEIVED: ['Reçue partiellement', 'warn'], RECEIVED: ['Reçue', 'ok'], AUTHORIZED: ['Autorisé', 'info'], INSPECTED: ['Inspecté', 'info'],
    RESTOCKED: ['Remis en stock', 'ok'], SUCCEEDED: ['Réussie', 'ok'], SUCCESS: ['Réussie', 'ok'], PROCESSED: ['Traitée', 'ok'],
    REFUNDED: ['Remboursée', 'info'], PARTIALLY_REFUNDED: ['Remb. partiel', 'info'], REQUIRES_PAYMENT_METHOD: ['Moyen requis', 'warn'],
    PENDING: ['En attente', 'warn'], REQUESTED: ['Demandé', 'warn'],
    // invoices (computed) & support
    OVERDUE: ['En retard', 'danger'], UNPAID: ['À encaisser', 'warn'], IN_PROGRESS: ['En cours', 'info'], RESOLVED: ['Résolu', 'ok'],
    // workflows & notifications
    RUNNING: ['En cours', 'info'], COMPENSATED: ['Compensé', 'warn'], COMPENSATING: ['Compensation', 'warn'], QUEUED: ['En file', 'neutral'],
    SENT: ['Envoyé', 'info'], SUPPRESSED: ['Bloqué', 'neutral'], DEAD_LETTER: ['En échec définitif', 'danger'], RETRYING: ['Nouvel essai', 'warn'],
    // priorities
    LOW: ['Basse', 'neutral'], MEDIUM: ['Moyenne', 'info'], HIGH: ['Haute', 'warn'], URGENT: ['Urgente', 'danger'], CRITICAL: ['Critique', 'danger'],
    // generic
    ACTIVE: ['Actif', 'ok'], INACTIVE: ['Inactif', 'neutral'], OPEN: ['Ouverte', 'info'], CLOSED: ['Fermée', 'neutral']
  };

  /** Status pill markup (label is escaped). */
  function pill(status, override) {
    var s = STATUS[String(status || '').toUpperCase()] || [status || '—', 'neutral'];
    return '<span class="status-pill pill-' + esc(override || s[1]) + '">' + esc(s[0]) + '</span>';
  }

  function statusLabel(status) {
    var s = STATUS[String(status || '').toUpperCase()];
    return s ? s[0] : String(status || '—');
  }

  /** Relative French time: "Il y a 5 min". */
  function ago(iso) {
    var t = new Date(iso).getTime();
    if (isNaN(t)) { return '—'; }
    var m = Math.round((Date.now() - t) / 60000);
    if (m < 1) { return "À l'instant"; }
    if (m < 60) { return 'Il y a ' + m + ' min'; }
    var h = Math.round(m / 60);
    if (h < 24) { return 'Il y a ' + h + ' h'; }
    var d = Math.round(h / 24);
    if (d < 31) { return 'Il y a ' + d + (d > 1 ? ' jours' : ' jour'); }
    return date(iso);
  }

  /** Percentage change label, or null when there is no comparable previous value. */
  function delta(current, previous) {
    if (!previous) { return null; }
    var p = (current - previous) / Math.abs(previous) * 100;
    return { up: p >= 0, text: (p >= 0 ? '+' : '−') + Math.abs(p).toLocaleString('fr-FR', { maximumFractionDigits: 1 }) + ' %' };
  }

  /** Normalise list responses ([...] or {items|data|results: [...]}). */
  function list(data, key) {
    if (Array.isArray(data)) { return data; }
    if (data && key && Array.isArray(data[key])) { return data[key]; }
    if (data) { return data.items || data.results || data.data || []; }
    return [];
  }

  window.SalesViews = { esc: esc, money: money, amount: amount, date: date, ago: ago, rowState: rowState, getJson: getJson, errorText: errorText,
    initials: initials, tone: tone, pill: pill, statusLabel: statusLabel, delta: delta, list: list };
})();
