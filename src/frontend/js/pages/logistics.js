/* Extracted from logistics.html by scripts/frontend_csp_build.py */
function attachProof(shipmentNumber) {
      const recipient = prompt(`Enter recipient name for POD on ${shipmentNumber}:`, "Karim Bennani");
      if (recipient) {
        alert(`Proof of Delivery recorded for ${shipmentNumber}. Status monotonically updated to DELIVERED.`);
      }
    }
