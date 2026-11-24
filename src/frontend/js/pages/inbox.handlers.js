/* Event handlers extracted from inbox.html (scripts/frontend_csp_build.py). */
(function () {
  'use strict';
  var H = {
    "h1": function (event) { window.location.href='agent_workspace.html'; },
    "h2": function (event) { window.location.href='schedule.html'; },
    "h3": function (event) { window.location.href='voice_agent.html'; },
    "h4": function (event) { applySuggestion('Je prépare le devis complet avec livraison incluse.'); },
    "h5": function (event) { applySuggestion('Avez-vous une date de livraison souhaitée sur le chantier ?'); },
    "h6": function (event) { applySuggestion('Souhaitez-vous une version renforcée haute densité du PR-480 ?'); },
    "h7": function (event) { window.location.href='quote_builder.html?client=Atlas+Construction'; },
    "h8": function (event) { window.location.href='schedule.html'; },
  };
  function bind() {
    Object.keys(H).forEach(function (hid) {
      document.querySelectorAll('[data-on-click="' + hid + '"],[data-on-change="' + hid + '"],[data-on-submit="' + hid + '"],[data-on-input="' + hid + '"]').forEach(function (el) {
        ['click', 'change', 'submit', 'input'].forEach(function (evt) {
          if (el.getAttribute('data-on-' + evt) === hid) {
            el.addEventListener(evt, function (e) { return H[hid].call(el, e); });
          }
        });
      });
    });
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', bind); } else { bind(); }
})();
