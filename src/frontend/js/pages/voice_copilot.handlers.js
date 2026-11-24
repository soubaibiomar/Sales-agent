/* Event handlers extracted from voice_copilot.html (scripts/frontend_csp_build.py). */
(function () {
  'use strict';
  var H = {
    "h1": function (event) { window.location.href='agent_workspace.html'; },
    "h2": function (event) { runQuery('Donne-moi le chiffre d\'affaires et les ventes du jour'); },
    "h3": function (event) { runQuery('Quels sont les devis en attente d\'approbation ?'); },
    "h4": function (event) { runQuery('Y a-t-il des alertes de rupture de stock ?'); },
    "h5": function (event) { runQuery('Quel est l\'état des tickets de support urgents ?'); },
    "h6": function (event) { runQuery('Approuve le bon de commande fournisseur PO-2026-001'); },
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
