/* Selia — Abonnement & quotas: plan, period and monthly consumption; quota adjustment is
 * reserved to tenant admins with step-up MFA (enforced server-side). */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList;
  const $ = (id) => document.getElementById(id);
  const PLAN = { FREE: 'Découverte', STARTER: 'Essentiel', PROFESSIONAL: 'Professionnel', PRO: 'Professionnel', ENTERPRISE: 'Entreprise' };
  const LABEL = { tokens: 'Jetons IA', voice_minutes: 'Minutes vocales', api_calls: 'Appels API', seats: 'Utilisateurs' };
  let sub = null;

  async function load() {
    const [s, q] = await Promise.all([V.getJson('/api/v1/saas/subscription'), V.getJson('/api/v1/saas/quotas')]);
    if (!s.ok) { $('kpis').innerHTML = '<p class="data-state data-state--error" role="alert">' + V.esc(V.errorText(s)) + '</p>'; }
    else {
      sub = s.data;
      const days = Math.max(0, Math.ceil((new Date(sub.current_period_end) - Date.now()) / 86400000));
      $('kpis').innerHTML = L.kpi('doc', '', 'Offre', V.esc(PLAN[String(sub.plan_id).toUpperCase()] || sub.plan_id)) +
        L.kpi('target', '', 'Statut', V.pill(sub.status)) +
        L.kpi('calendar', 'sand', 'Fin de période', V.esc(V.date(sub.current_period_end)), days + ' jour(s) restant(s)') +
        L.kpi('users', 'terra', 'Sièges', V.esc((sub.limits || {}).max_seats ?? '—'));
    }
    if (!q.ok) { $('quotas').innerHTML = '<li class="data-state data-state--error" role="alert">' + V.esc(V.errorText(q)) + '</li>'; return; }
    $('periodLabel').textContent = q.data.period_month ? 'Mois ' + q.data.period_month : '';
    const quotas = q.data.quotas || {};
    $('quotas').innerHTML = Object.keys(quotas).map(k => {
      const x = quotas[k], pct = Math.min(100, Math.round(Number(x.percentage || 0)));
      return '<li><strong>' + V.esc(LABEL[k] || k) + '</strong><span class="bar-track" role="progressbar" aria-valuenow="' + pct + '" aria-valuemin="0" aria-valuemax="100" aria-label="' +
        V.esc(LABEL[k] || k) + '"><span class="bar-fill' + (x.exhausted ? ' full' : pct >= 80 ? ' warn' : '') + '" style="width:' + Math.max(2, pct) + '%"></span></span>' +
        '<span class="amt">' + V.esc(Number(x.used || 0).toLocaleString('fr-FR')) + ' / ' + V.esc(Number(x.limit || 0).toLocaleString('fr-FR')) + ' (' + pct + ' %)</span></li>';
    }).join('') || '<li class="data-state">Aucune donnée de consommation.</li>';
  }

  function init() {
    $('btnAdjust').addEventListener('click', () => {
      const l = (sub && sub.limits) || {};
      $('qTokens').value = l.monthly_token_limit || ''; $('qVoice').value = l.monthly_voice_minutes_limit || '';
      $('qApi').value = l.monthly_api_call_limit || ''; $('qSeats').value = l.max_seats || '';
      window.SalesAI.openModal('quotaModal');
    });
    $('quotaForm').addEventListener('submit', (e) => {
      e.preventDefault();
      const n = (id) => ($(id).value === '' ? null : Number($(id).value));
      L.submitForm(e.target, '/api/v1/saas/quotas/adjust', { monthly_token_limit: n('qTokens'), monthly_voice_minutes_limit: n('qVoice'),
        monthly_api_call_limit: n('qApi'), max_seats: n('qSeats') }, 'Quotas mis à jour.', load);
    });
    load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
