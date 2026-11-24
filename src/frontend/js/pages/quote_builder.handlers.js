/* Event handlers extracted from quote_builder.html (scripts/frontend_csp_build.py). */
(function () {
  'use strict';
  var H = {
    "h1": function (event) { window.location.href='orders.html'; },
    "h2": function (event) { window.location.href='approvals.html'; },
    "h3": function (event) { window.location.href='pipeline.html'; },
    "h4": function (event) { window.location.href='analytics_dashboard.html'; },
    "h5": function (event) { window.location.href='approvals.html'; },
    "h6": function (event) { window.location.href='orders.html'; },
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
