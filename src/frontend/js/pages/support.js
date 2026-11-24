/* Extracted from support.html by scripts/frontend_csp_build.py */
function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      event.target.classList.add('active');
      document.getElementById('tab-tickets').style.display = tabId === 'tickets' ? 'block' : 'none';
      document.getElementById('tab-rmas').style.display = tabId === 'rmas' ? 'block' : 'none';
      document.getElementById('tab-warranties').style.display = tabId === 'warranties' ? 'block' : 'none';
    }

    function inspectRMA(rmaNumber) {
      const outcome = prompt(`Select inspection outcome for ${rmaNumber} (RESTOCK, QUARANTINE, SCRAP, REJECT):`, "RESTOCK");
      if (outcome) {
        alert(`RMA ${rmaNumber} inspected with outcome ${outcome}. Inventory and refund updated according to policy.`);
      }
    }
