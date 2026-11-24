/* Inventory page: live stock ledger (F-20). Values are escaped; loading/empty/error states shown. */
(function () {
  'use strict';
  var V = window.SalesViews;

  function warehouseName(map, id) { return map[id] || id || '—'; }

  async function loadInventory() {
    var tbody = document.getElementById('inventory-body');
    if (!tbody) { return; }
    V.rowState(tbody, 8, 'loading', 'Chargement du stock…');
    var [items, whs] = await Promise.all([V.getJson('/api/v1/inventory/items'), V.getJson('/api/v1/inventory/warehouses')]);
    if (!items.ok) { V.rowState(tbody, 8, 'error', V.errorText(items)); return; }
    var whMap = {};
    (whs.ok && Array.isArray(whs.data) ? whs.data : []).forEach(function (w) { whMap[w.id] = w.name || w.code; });
    var rows = Array.isArray(items.data) ? items.data : [];
    if (!rows.length) { V.rowState(tbody, 8, 'empty', 'Aucun article en stock pour cette organisation.'); return; }
    tbody.innerHTML = rows.map(function (it) {
      var atp = Number(it.available_to_promise || 0);
      var cls = atp > 10 ? 'atp-pill' : (atp > 0 ? 'atp-pill atp-low' : 'atp-pill atp-out');
      return '<tr>' +
        '<td><strong>' + V.esc(it.sku) + '</strong></td>' +
        '<td>' + V.esc(warehouseName(whMap, it.warehouse_id)) + '</td>' +
        '<td>' + V.esc(it.on_hand_quantity) + '</td>' +
        '<td>' + V.esc(it.reserved_quantity) + '</td>' +
        '<td>' + V.esc(it.allocated_quantity) + '</td>' +
        '<td><span class="' + cls + '">' + V.esc(atp) + ' unités</span></td>' +
        '<td>' + (it.backorder_allowed ? 'Oui' : 'Non') + '</td>' +
        '<td><a class="btn btn-outline" href="inventory.html?item=' + encodeURIComponent(it.id) + '">Mouvements</a></td>' +
        '</tr>';
    }).join('');
  }

  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', loadInventory); } else { loadInventory(); }
})();
