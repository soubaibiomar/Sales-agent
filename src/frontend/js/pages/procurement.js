/* Extracted from procurement.html by scripts/frontend_csp_build.py */
function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      event.target.classList.add('active');
      document.getElementById('tab-pos').style.display = tabId === 'pos' ? 'block' : 'none';
      document.getElementById('tab-suppliers').style.display = tabId === 'suppliers' ? 'block' : 'none';
      document.getElementById('tab-transfers').style.display = tabId === 'transfers' ? 'block' : 'none';
    }

    function receiveGoods(poNumber) {
      const qty = prompt(`Enter received quantity for ${poNumber}:`, "10");
      if (qty) {
        alert(`Goods Receipt recorded for ${poNumber}. Ledger updated.`);
      }
    }
