/* Event handlers extracted from approvals.html (scripts/frontend_csp_build.py). */
(function () {
  'use strict';
  var H = {
    "h1": function (event) { alert('Délégation d\'autorité temporaire'); },
    "h2": function (event) { rejectApproval('QT-B89E21'); },
    "h3": function (event) { openMfaModal('QT-B89E21'); },
    "h4": function (event) { rejectApproval('QT-C10A92'); },
    "h5": function (event) { openMfaModal('QT-C10A92'); },
    "h6": function (event) { closeMfaModal(); },
    "h7": function (event) { closeMfaModal(); },
    "h8": function (event) { submitMfaApproval(); },
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
