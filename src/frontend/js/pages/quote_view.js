/* Selia — public quote page. The customer opens the signed link sent with the quote
 * (quote_view.html?quote=…&token=…). The quote is read through GET /quotes/{id}/public and
 * accepted/refused through the signed-link endpoints. Plain fetch (no staff session). */
(function () {
  'use strict';
  const V = window.SalesViews;
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const quoteId = params.get('quote'), token = params.get('token');

  function fail(text) { $('quoteDoc').innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(text) + '</p>'; $('quoteActions').hidden = true; }

  async function call(method, url, body) {
    try {
      const r = await fetch(url, { method: method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined, credentials: 'omit' });
      let data = null; try { data = await r.json(); } catch (e) { data = null; }
      return { ok: r.ok, status: r.status, data: data };
    } catch (e) { return { ok: false, status: 0, data: null }; }
  }

  function linkError(res) {
    if (res.status === 401) return 'Ce lien est invalide ou a expiré. Demandez un nouveau lien à votre interlocuteur.';
    if (res.status === 409) return 'Ce devis a été modifié depuis l’envoi du lien. Demandez un nouveau lien.';
    if (res.status === 410) return 'Ce devis a expiré.';
    if (res.status === 404) return 'Devis introuvable.';
    return (res.data && typeof res.data.detail === 'string') ? res.data.detail : 'Service indisponible, réessayez plus tard.';
  }

  function render(q) {
    const cur = q.currency || 'MAD';
    $('quoteDoc').innerHTML =
      '<div class="quote-top"><div><span class="cell-sub">Devis</span><h1>' + V.esc(q.quote_number) + '</h1></div>' + V.pill(q.status) + '</div>' +
      '<div class="quote-parties"><div><span>Émis par</span>' + V.esc(q.seller_name || '—') + '</div><div><span>Pour</span>' + V.esc(q.customer_name || '—') + '</div>' +
      '<div><span>Date</span>' + V.esc(V.date(q.issued_at)) + '</div><div><span>Valable jusqu’au</span>' + V.esc(V.date(q.valid_until)) + '</div></div>' +
      '<div class="table-responsive"><table class="data-table responsive-table"><thead><tr><th>Article</th><th class="num">Qté</th><th class="num">Prix unitaire</th><th class="num">Remise</th><th class="num">Total HT</th></tr></thead><tbody>' +
      (q.items || []).map(i => '<tr><td data-label=""><strong>' + V.esc(i.name) + '</strong><span class="cell-sub">' + V.esc(i.sku) + '</span></td>' +
        '<td data-label="Qté" class="num">' + V.esc(i.quantity) + '</td><td data-label="Prix unitaire" class="num">' + V.esc(V.money(i.unit_price_cents, cur)) + '</td>' +
        '<td data-label="Remise" class="num">' + V.esc(Number(i.discount_percent || 0).toLocaleString('fr-FR')) + ' %</td>' +
        '<td data-label="Total HT" class="num">' + V.esc(V.money(i.subtotal_cents, cur)) + '</td></tr>').join('') + '</tbody></table></div>' +
      '<div class="quote-totals"><div><span>Sous-total HT</span><strong>' + V.esc(V.money(q.subtotal_cents, cur)) + '</strong></div>' +
      (q.discount_total_cents ? '<div><span>Remise</span><strong>-' + V.esc(V.money(q.discount_total_cents, cur)) + '</strong></div>' : '') +
      '<div><span>TVA</span><strong>' + V.esc(V.money(q.tax_total_cents, cur)) + '</strong></div>' +
      '<div class="grand"><span>Total TTC</span><span>' + V.esc(V.money(q.grand_total_cents, cur)) + '</span></div></div>';
    $('quoteActions').hidden = ['SENT', 'ISSUED'].indexOf(q.status) === -1;
  }

  async function load() {
    if (!quoteId || !token) { fail('Lien incomplet. Utilisez le lien reçu avec votre devis.'); return; }
    const res = await call('GET', '/api/v1/quotes/' + encodeURIComponent(quoteId) + '/public?token=' + encodeURIComponent(token));
    if (!res.ok) { fail(linkError(res)); return; }
    render(res.data);
  }

  async function decide(kind) {
    const note = $('qNote').value.trim();
    $('qAccept').disabled = $('qReject').disabled = true;
    const body = kind === 'accept' ? { acceptance_token: token, signature_or_note: note || null } : { acceptance_token: token, reason: note || null };
    const res = await call('POST', '/api/v1/quotes/' + encodeURIComponent(quoteId) + '/' + kind, body);
    $('qAccept').disabled = $('qReject').disabled = false;
    if (!res.ok) { $('qError').textContent = linkError(res); return; }
    $('qError').textContent = '';
    await load();
    $('quoteActions').hidden = true;
    const msg = document.createElement('p');
    msg.className = 'data-state';
    msg.setAttribute('role', 'status');
    msg.textContent = kind === 'accept' ? 'Merci : votre acceptation a été enregistrée.' : 'Votre refus a été enregistré.';
    $('quoteDoc').appendChild(msg);
  }

  $('qAccept').addEventListener('click', () => decide('accept'));
  $('qReject').addEventListener('click', () => decide('reject'));
  load();
})();
