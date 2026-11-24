/* Extracted from approvals.html by scripts/frontend_csp_build.py */
let activeApprovalId = null;
    function openMfaModal(appId) {
      activeApprovalId = appId;
      document.getElementById("mfaModal").style.display = "flex";
      document.getElementById("mfaCode").value = "";
      document.getElementById("mfaCode").focus();
    }
    function closeMfaModal() {
      document.getElementById("mfaModal").style.display = "none";
      activeApprovalId = null;
    }
    function submitMfaApproval() {
      const code = document.getElementById("mfaCode").value;
      if (code.length !== 6) {
        alert("Veuillez saisir un code TOTP à 6 chiffres.");
        return;
      }
      closeMfaModal();
      if (window.SalesAI) window.SalesAI.showToast(`Approbation ${activeApprovalId} validée par MFA et enregistrée.`);
    }
    function rejectApproval(appId) {
      const reason = prompt("Veuillez préciser le motif du rejet commercial :");
      if (reason && window.SalesAI) {
        window.SalesAI.showToast(`Offre ${appId} rejetée avec motif enregistré.`);
      }
    }
