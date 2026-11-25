/* Selia — Rendez-vous: month calendar + day agenda from /api/v1/scheduling/appointments,
 * creation through POST /api/v1/scheduling/appointments. */
(function () {
  'use strict';
  const V = window.SalesViews, L = window.SeliaList, UI = window.SalesAI;
  const $ = (id) => document.getElementById(id);
  const SERVICE = { SALES_DEMO: 'Réunion commerciale', ON_SITE_INSTALLATION: 'Visite sur site', HARDWARE_SUPPORT: 'Support', DELIVERY_SLOT: 'Livraison' };
  const LOC_ICON = { VIDEO_CALL: '<path d="M15 10l5-3v10l-5-3z"/><rect x="3" y="6" width="12" height="12" rx="2"/>', ON_SITE: '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>', PHONE: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/>' };
  const STATUS = { REQUESTED: ['Demandé', 'warn'], CONFIRMED: ['Confirmé', 'ok'], SCHEDULED: ['À venir', 'warn'], RESCHEDULED: ['Reporté', 'warn'], COMPLETED: ['Terminé', 'neutral'], CANCELLED: ['Annulé', 'danger'], NO_SHOW: ['Absent', 'danger'] };
  let appts = [], names = new Map(), month = new Date(), selected = new Date();
  month.setDate(1);

  const key = (d) => d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate();
  const svg = (d) => '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';

  function renderKpis() {
    const now = new Date(), today = key(now);
    const n = (f) => appts.filter(f).length;
    $('kpis').innerHTML = L.kpi('calendar', '', 'Rendez-vous totaux', appts.length) +
      L.kpi('calendar', 'terra', "Aujourd'hui", n(a => key(new Date(a.start_time)) === today && a.status !== 'CANCELLED')) +
      L.kpi('target', 'sand', 'À venir', n(a => new Date(a.start_time) > now && ['REQUESTED', 'SCHEDULED', 'CONFIRMED', 'RESCHEDULED'].indexOf(a.status) !== -1)) +
      L.kpi('doc', '', 'Terminés', n(a => a.status === 'COMPLETED'));
  }

  function renderCalendar() {
    $('monthTitle').textContent = month.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' });
    const first = new Date(month), offset = (first.getDay() + 6) % 7;
    const start = new Date(first); start.setDate(1 - offset);
    const busy = new Set(appts.filter(a => a.status !== 'CANCELLED').map(a => key(new Date(a.start_time))));
    const today = key(new Date()), sel = key(selected);
    let html = '';
    for (let i = 0; i < 42; i++) {
      const d = new Date(start); d.setDate(start.getDate() + i);
      if (i >= 35 && d.getMonth() !== month.getMonth()) break;
      const k = key(d);
      html += '<button type="button" class="cal-day' + (d.getMonth() !== month.getMonth() ? ' is-out' : '') + (k === today ? ' is-today' : '') +
        (busy.has(k) ? ' has-events' : '') + '" data-day="' + d.toISOString() + '" aria-selected="' + (k === sel) + '" aria-label="' +
        V.esc(d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })) + (busy.has(k) ? ', rendez-vous prévus' : '') + '">' + d.getDate() + '</button>';
    }
    $('calDays').innerHTML = html;
  }

  function renderDay() {
    const label = selected.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    $('dayTitle').textContent = label.charAt(0).toUpperCase() + label.slice(1);
    const items = appts.filter(a => key(new Date(a.start_time)) === key(selected)).sort((a, b) => new Date(a.start_time) - new Date(b.start_time));
    $('dayCount').textContent = items.length + ' rendez-vous';
    $('agenda').innerHTML = items.length ? items.map(a => {
      const st = STATUS[a.status] || [a.status, 'neutral'];
      return '<li><span class="time">' + V.esc(new Date(a.start_time).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })) + '</span>' +
        '<span class="feed-icon">' + UI.icon('users', 18) + '</span>' +
        '<span class="feed-main"><strong>' + V.esc(a.notes || SERVICE[a.service_type] || a.service_type) + '</strong><span>' + V.esc(names.get(a.account_id) || SERVICE[a.service_type] || '') + '</span></span>' +
        '<span class="loc" title="' + V.esc(a.location_details || '') + '">' + svg(LOC_ICON[a.location_type] || LOC_ICON.ON_SITE) + '</span>' + V.pill(st[0], st[1]) + '</li>';
    }).join('') : '<li class="data-state">Aucun rendez-vous ce jour-là.</li>';
  }

  function render() { renderKpis(); renderCalendar(); renderDay(); }

  async function load() {
    const from = new Date(month.getFullYear(), month.getMonth() - 1, 1), to = new Date(month.getFullYear(), month.getMonth() + 2, 1);
    const [res, acc] = await Promise.all([
      V.getJson('/api/v1/scheduling/appointments?limit=200&from_date=' + encodeURIComponent(from.toISOString()) + '&to_date=' + encodeURIComponent(to.toISOString())),
      V.getJson('/api/v1/crm/accounts?limit=500')]);
    const accounts = acc.ok ? V.list(acc.data) : [];
    names = new Map(accounts.map(a => [a.id, a.name]));
    $('aAccount').innerHTML = '<option value="">Sans client</option>' + accounts.map(a => '<option value="' + V.esc(a.id) + '">' + V.esc(a.name) + '</option>').join('');
    if (!res.ok) { $('agenda').innerHTML = '<li class="data-state data-state--error" role="alert">' + V.esc(V.errorText(res)) + '</li>'; renderCalendar(); return; }
    appts = V.list(res.data);
    render();
  }

  async function create(e) {
    e.preventDefault();
    const err = $('apptError');
    if (!$('aDate').value || !$('aTime').value) { err.textContent = "La date et l'heure sont obligatoires."; return; }
    const start = new Date($('aDate').value + 'T' + $('aTime').value);
    const end = new Date(start.getTime() + Number($('aDur').value) * 60000);
    const res = await V.getJson('/api/v1/scheduling/appointments', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: $('aAccount').value || null, service_type: $('aType').value, location_type: $('aLoc').value,
        start_time: start.toISOString(), end_time: end.toISOString(), notes: $('aNotes').value.trim() || null })
    });
    if (!res.ok) { err.textContent = res.status === 403 ? 'Votre rôle ne permet pas de planifier un rendez-vous.' : (res.data && typeof res.data.detail === 'string' ? res.data.detail : V.errorText(res)); return; }
    $('apptModal').hidden = true; e.target.reset();
    selected = start; month = new Date(start.getFullYear(), start.getMonth(), 1);
    UI.showToast('Rendez-vous planifié le ' + start.toLocaleDateString('fr-FR') + '.');
    load();
  }

  function init() {
    $('calDays').addEventListener('click', (e) => { const b = e.target.closest('[data-day]'); if (b) { selected = new Date(b.getAttribute('data-day')); renderCalendar(); renderDay(); } });
    $('prevMonth').addEventListener('click', () => { month = new Date(month.getFullYear(), month.getMonth() - 1, 1); load(); });
    $('nextMonth').addEventListener('click', () => { month = new Date(month.getFullYear(), month.getMonth() + 1, 1); load(); });
    $('btnNewAppt').addEventListener('click', () => { $('aDate').value = selected.toISOString().slice(0, 10); UI.openModal('apptModal'); });
    $('apptForm').addEventListener('submit', create);
    if (location.hash === '#nouveau') { $('aDate').value = selected.toISOString().slice(0, 10); UI.openModal('apptModal'); }
    renderCalendar();
    window.addEventListener('hashchange', () => { if (location.hash === '#nouveau') { $('aDate').value = selected.toISOString().slice(0, 10); window.SalesAI.openModal('apptModal'); } });
    load();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
