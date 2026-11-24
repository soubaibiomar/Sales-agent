/* Event handlers extracted from agent_workspace.html (scripts/frontend_csp_build.py). */
(function () {
  'use strict';
  var H = {
    "h1": function (event) { window.location.href='agent_workspace.html'; },
    "h2": function (event) { refreshCatalog(); },
    "h3": function (event) { runOperationsTriage(); },
    "h4": function (event) { switchAgentTab('catalog'); },
    "h5": function (event) { switchAgentTab('copilot'); },
    "h6": function (event) { switchAgentTab('activity'); },
    "h7": function (event) { toggleHumanTakeover(this.checked); },
    "h8": function (event) { generateCopilotBrief(); },
    "h9": function (event) { copyReply(this); },
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
