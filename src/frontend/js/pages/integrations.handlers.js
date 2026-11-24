/* Event handlers extracted from integrations.html (scripts/frontend_csp_build.py). */
(function () {
  'use strict';
  var H = {
    "h1": function (event) { window.location.href='agent_workspace.html'; },
    "h2": function (event) { verifyBarrier('quotes:approve'); },
    "h3": function (event) { verifyBarrier('orders:mark_paid'); },
    "h4": function (event) { verifyBarrier('inventory:adjust'); },
    "h5": function (event) { verifyBarrier('payments:refund'); },
    "h6": function (event) { verifyBarrier('leads:enrich_summary'); },
    "h7": function (event) { loadOutbox(); },
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
