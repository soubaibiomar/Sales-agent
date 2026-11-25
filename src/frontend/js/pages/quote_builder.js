/* Quote builder wired to the quotation domain service (F-20, AGENTS.md invariant 2).
 * The browser only chooses a customer, products, quantities and requested discounts;
 * prices, discounts, tax, totals and approval requirements are computed by the server
 * (POST /api/v1/quotes, PUT /api/v1/quotes/{id}/items) and rendered from its response.
 * No figure shown here is computed client-side. */
(function () {
  'use strict';
  var V = window.SalesViews;
  var $ = function (id) { return document.getElementById(id); };

  var STATUS = {
    DRAFT: ['Brouillon', 'badge-warning'], PRICED: ['Chiffré', 'badge-info'], PENDING_APPROVAL: ['En validation', 'badge-warning'],
    APPROVED: ['Approuvé', 'badge-success'], ISSUED: ['Émis', 'badge-info'], SENT: ['Envoyé', 'badge-info'],
    ACCEPTED: ['Accepté', 'badge-success'], REJECTED: ['Refusé', 'badge-danger'], EXPIRED: ['Expiré', 'badge-neutral']
  };

  var accounts = [], products = [];
  var customer = null;          // selected account
  var lines = [];               // [{product, quantity, discount_percent}]
  var quote = null;             // last server QuoteResponse

  function toast(msg) { if (window.SalesAI && window.SalesAI.showToast) { window.SalesAI.showToast(msg); } }

  /* ---------- KPIs (server data) ---------- */
  async function loadKpis() {
    var res = await V.getJson('/api/v1/quotes?limit=500');
    if (!res.ok) { return; }
    var qs = res.data || [];
    var count = function (st) { return qs.filter(function (q) { return st.indexOf(q.status) !== -1; }).length; };
    $('kpiQuotesTotal').textContent = String(qs.length);
    $('kpiQuotesApproved').textContent = String(count(['APPROVED', 'ISSUED', 'SENT', 'ACCEPTED']));
    $('kpiQuotesPending').textContent = String(count(['PENDING_APPROVAL']));
    $('kpiQuotesAccepted').textContent = String(count(['ACCEPTED']));
    var value = qs.filter(function (q) { return q.currency === 'MAD'; })
      .reduce(function (sum, q) { return sum + (q.grand_total_cents || 0); }, 0);
    $('kpiQuotesValue').textContent = V.money(value, 'MAD');
  }

  /* ---------- Customers ---------- */
  function renderCustomers() {
    var tbody = $('qbCustomerBody');
    var term = ($('qbCustomerSearch').value || '').toLowerCase();
    var list = accounts.filter(function (a) { return !term || String(a.name).toLowerCase().indexOf(term) !== -1; });
    if (!list.length) { V.rowState(tbody, 3, 'empty', accounts.length ? 'Aucun client ne correspond.' : 'Aucun client.'); return; }
    tbody.innerHTML = list.slice(0, 50).map(function (a) {
      var sel = customer && customer.id === a.id;
      return '<tr data-account="' + V.esc(a.id) + '"' + (sel ? ' class="is-selected"' : '') + '>' +
        '<td><input type="radio" name="selCust" aria-label="Choisir ' + V.esc(a.name) + '"' + (sel ? ' checked' : '') + '></td>' +
        '<td><strong>' + V.esc(a.name) + '</strong><div class="kpi-caption">' + V.esc(a.account_type || '') + '</div></td>' +
        '<td>' + V.esc(a.industry || '—') + '</td></tr>';
    }).join('');
  }

  function renderBanner() {
    var el = $('qbCustomerBanner');
    el.textContent = '';
    var strong = document.createElement('strong');
    strong.className = 'qb-banner-name';
    strong.textContent = customer ? customer.name : 'Aucun client sélectionné';
    el.appendChild(strong);
    var meta = document.createElement('div');
    meta.className = 'kpi-caption';
    meta.textContent = customer
      ? [customer.tax_identifier ? 'ICE : ' + customer.tax_identifier : null, customer.phone, customer.billing_address].filter(Boolean).join(' • ') || 'Coordonnées non renseignées'
      : 'Choisissez un client dans la liste.';
    el.appendChild(meta);
  }

  /* ---------- Catalogue ---------- */
  function renderProducts() {
    var tbody = $('qbProductBody');
    var term = ($('qbProductSearch').value || '').toLowerCase();
    var list = products.filter(function (p) {
      return !term || (String(p.name) + ' ' + String(p.sku)).toLowerCase().indexOf(term) !== -1;
    });
    if (!list.length) { V.rowState(tbody, 4, 'empty', products.length ? 'Aucun produit ne correspond.' : 'Catalogue vide.'); return; }
    tbody.innerHTML = list.slice(0, 50).map(function (p) {
      return '<tr><td><code>' + V.esc(p.sku) + '</code></td><td>' + V.esc(p.name) + '</td>' +
        '<td>' + V.esc(V.money(p.base_price_cents, p.currency)) + '</td>' +
        '<td><button type="button" class="btn btn-outline qb-add" data-product="' + V.esc(p.id) + '" aria-label="Ajouter ' + V.esc(p.name) + '">+</button></td></tr>';
    }).join('');
  }

  /* ---------- Lines / totals (server-priced) ---------- */
  function serverItem(productId) {
    if (!quote || !quote.items) { return null; }
    for (var i = 0; i < quote.items.length; i++) { if (quote.items[i].product_id === productId) { return quote.items[i]; } }
    return null;
  }

  function renderLines() {
    var tbody = $('qbItemsBody');
    $('qbItemsCount').textContent = 'Articles du devis (' + lines.length + ')';
    if (!lines.length) { V.rowState(tbody, 7, 'empty', 'Aucun article. Ajoutez-en depuis le catalogue.'); return; }
    tbody.innerHTML = lines.map(function (l, i) {
      var it = serverItem(l.product.id);
      return '<tr data-line="' + i + '"><td>' + (i + 1) + '</td>' +
        '<td><strong>' + V.esc(l.product.name) + '</strong><div class="kpi-caption">' + V.esc(l.product.sku) + '</div></td>' +
        '<td><input type="number" min="1" step="1" class="form-control qb-qty" value="' + V.esc(l.quantity) + '" aria-label="Quantité"></td>' +
        '<td>' + (it ? V.esc(V.money(it.unit_price_cents, quote.currency)) : '<span class="kpi-caption">à chiffrer</span>') + '</td>' +
        '<td><input type="number" min="0" max="100" step="0.5" class="form-control qb-disc" value="' + V.esc(l.discount_percent) + '" aria-label="Remise demandée (%)"></td>' +
        '<td>' + (it ? V.esc(V.money(it.subtotal_cents, quote.currency)) : '—') + '</td>' +
        '<td><button type="button" class="btn btn-outline qb-remove" aria-label="Retirer">✕</button></td></tr>';
    }).join('');
  }

  function renderTotals() {
    var cur = quote ? quote.currency : 'MAD';
    var priced = quote && quote.items && quote.items.length;
    $('qbSubtotal').textContent = priced ? V.money(quote.subtotal_cents, cur) : '—';
    $('qbDiscount').textContent = priced ? '-' + V.money(quote.discount_total_cents, cur) : '—';
    $('qbTax').textContent = priced ? V.money(quote.tax_total_cents, cur) : '—';
    $('qbTotal').textContent = priced ? V.money(quote.grand_total_cents, cur) : '—';
    var note = $('qbTotalsNote');
    if (quote && quote.requires_approval) {
      note.textContent = 'Approbation requise : ' + (quote.approval_reason || 'seuil de remise ou de marge dépassé') + '.';
    } else if (priced) {
      note.textContent = 'Montants calculés par le serveur — marge ' + quote.margin_percent + ' %.';
    } else {
      note.textContent = 'Les montants sont calculés par le serveur (prix catalogue, remises autorisées, TVA).';
    }
    var st = STATUS[quote ? quote.status : 'DRAFT'] || [String(quote.status), 'badge-neutral'];
    var badge = $('qbQuoteStatus');
    badge.textContent = st[0];
    badge.className = 'badge ' + st[1];
    $('qbQuoteNumber').textContent = quote ? quote.quote_number : 'Nouveau devis';
    // The server allows issuing PRICED quotes (or APPROVED ones when approval was required).
    $('qbIssue').disabled = !(priced && (quote.status === 'APPROVED' || (quote.status === 'PRICED' && !quote.requires_approval)));
    $('qbSend').disabled = !(quote && (quote.status === 'ISSUED' || quote.status === 'SENT'));
  }

  function markDirty() {
    // Any edit invalidates the server pricing until the quote is saved again.
    if (quote) { quote.items = []; }
    renderLines(); renderTotals();
  }

  /* ---------- Server calls ---------- */
  async function save() {
    if (!customer) { toast('Sélectionnez un client.'); return; }
    if (!lines.length) { toast('Ajoutez au moins un article.'); return; }
    var btn = $('qbSave');
    btn.disabled = true;
    try {
      if (!quote) {
        var created = await V.getJson('/api/v1/quotes', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ account_id: customer.id, currency: 'MAD', payment_terms: $('qbTerms').value, valid_days: parseInt($('qbValidity').value, 10) })
        });
        if (!created.ok) { toast('Création impossible : ' + V.errorText(created)); return; }
        quote = created.data;
      }
      var priced = await V.getJson('/api/v1/quotes/' + encodeURIComponent(quote.id) + '/items', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: lines.map(function (l) { return { product_id: l.product.id, quantity: l.quantity, discount_percent: String(l.discount_percent || 0) }; }),
          payment_terms: $('qbTerms').value,
          expected_version: quote.version
        })
      });
      if (!priced.ok) {
        toast(priced.status === 403 ? "Votre rôle ne permet pas de chiffrer ce devis (brouillon enregistré)." : 'Chiffrage impossible : ' + V.errorText(priced));
        renderTotals();
        return;
      }
      quote = priced.data;
      renderLines(); renderTotals(); loadKpis();
      toast('Devis ' + quote.quote_number + ' chiffré.');
    } finally {
      btn.disabled = false;
    }
  }

  async function issue() {
    if (!quote) { return; }
    var res = await V.getJson('/api/v1/quotes/' + encodeURIComponent(quote.id) + '/issue', { method: 'POST' });
    if (!res.ok) { toast('Émission impossible : ' + V.errorText(res)); return; }
    quote.status = res.data.quote_status || 'ISSUED';
    renderTotals(); loadKpis();
    toast('Devis ' + res.data.quote_number + ' émis.');
  }

  /* ---------- Wiring ---------- */
  function init() {
    $('qbCustomerSearch').addEventListener('input', renderCustomers);
    $('qbProductSearch').addEventListener('input', renderProducts);

    $('qbCustomerBody').addEventListener('click', function (e) {
      var tr = e.target.closest('[data-account]');
      if (!tr) { return; }
      var id = tr.getAttribute('data-account');
      var next = accounts.filter(function (a) { return a.id === id; })[0] || null;
      if (quote && next && quote.account_id !== next.id) { quote = null; }  // new customer -> new quote
      customer = next;
      renderCustomers(); renderBanner(); markDirty();
    });

    $('qbProductBody').addEventListener('click', function (e) {
      var btn = e.target.closest('.qb-add');
      if (!btn) { return; }
      var id = btn.getAttribute('data-product');
      var existing = lines.filter(function (l) { return l.product.id === id; })[0];
      if (existing) { existing.quantity += 1; }
      else { lines.push({ product: products.filter(function (p) { return p.id === id; })[0], quantity: 1, discount_percent: 0 }); }
      markDirty();
    });

    var items = $('qbItemsBody');
    items.addEventListener('change', function (e) {
      var tr = e.target.closest('[data-line]');
      if (!tr) { return; }
      var line = lines[parseInt(tr.getAttribute('data-line'), 10)];
      if (e.target.classList.contains('qb-qty')) { line.quantity = Math.max(1, parseInt(e.target.value, 10) || 1); }
      if (e.target.classList.contains('qb-disc')) { line.discount_percent = Math.min(100, Math.max(0, parseFloat(e.target.value) || 0)); }
      markDirty();
    });
    items.addEventListener('click', function (e) {
      if (!e.target.closest('.qb-remove')) { return; }
      lines.splice(parseInt(e.target.closest('[data-line]').getAttribute('data-line'), 10), 1);
      markDirty();
    });

    $('qbSave').addEventListener('click', save);
    $('qbIssue').addEventListener('click', issue);

    $('qbSend').addEventListener('click', function () { window.SalesAI.openModal('sendModal'); });
    $('sendForm').addEventListener('submit', function (e) {
      e.preventDefault();
      var to = $('sRecipient').value.trim();
      if (!to) { e.target.querySelector('.form-error').textContent = 'Le destinataire est obligatoire.'; return; }
      window.SeliaList.submitForm(e.target, '/api/v1/quotes/' + encodeURIComponent(quote.id) + '/send',
        { recipient_identifier: to, channel_type: $('sChannel').value }, 'Lien d’acceptation généré.', function (d) {
          quote.status = d.quote_status || 'SENT';
          $('qbLink').value = location.origin + location.pathname.replace(/[^/]+$/, '') + String(d.acceptance_path || '').replace(/^\//, '');
          $('qbLinkBox').hidden = false; renderTotals(); loadKpis();
        });
    });
    $('qbCopy').addEventListener('click', function () { $('qbLink').select(); if (navigator.clipboard) { navigator.clipboard.writeText($('qbLink').value); } toast('Lien copié.'); });
    renderBanner(); renderLines(); renderTotals(); loadKpis();

    V.getJson('/api/v1/crm/accounts?limit=200&is_active=true').then(function (res) {
      if (!res.ok) { V.rowState($('qbCustomerBody'), 3, 'error', V.errorText(res)); return; }
      accounts = res.data || []; renderCustomers();
    });
    V.getJson('/api/v1/catalog/products?limit=200&is_active=true').then(function (res) {
      if (!res.ok) { V.rowState($('qbProductBody'), 4, 'error', V.errorText(res)); return; }
      products = res.data || []; renderProducts();
    });
  }

  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
