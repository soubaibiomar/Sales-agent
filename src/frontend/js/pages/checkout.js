/* Extracted from checkout.html by scripts/frontend_csp_build.py */
let secondsLeft = 1799;
    setInterval(() => {
      if (secondsLeft > 0) {
        secondsLeft--;
        const mins = Math.floor(secondsLeft / 60);
        const secs = secondsLeft % 60;
        document.getElementById("countdown").innerText = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
      } else {
        document.getElementById("countdown").innerText = "EXPIRED";
      }
    }, 1000);

    async function executePayment() {
      const btn = document.getElementById("btn-pay");
      btn.innerText = "Processing Payment...";
      btn.disabled = true;

      setTimeout(() => {
        alert("Payment captured successfully in sandbox! Stock reservation committed and invoice generated.");
        window.location.href = "invoices.html";
      }, 1200);
    }
