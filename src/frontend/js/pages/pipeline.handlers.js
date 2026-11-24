/* Event handlers extracted from pipeline.html (scripts/frontend_csp_build.py). */
(function () {
  'use strict';
  var H = {
    "h1": function (event) { window.location.href='agent_workspace.html'; },
    "h2": function (event) { openNewOppModal(); },
    "h3": function (event) { loadPipeline(); },
    "h4": function (event) { openNewOppModal(); },
    "h5": function (event) { closeModal(); },
    "h6": function (event) { closeModal(); },
    "h7": function (event) { submitNewOpp(); },
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
