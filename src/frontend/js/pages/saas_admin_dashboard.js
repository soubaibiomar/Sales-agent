/* Extracted from saas_admin_dashboard.html by scripts/frontend_csp_build.py */
async function fetchSaaSData() {
      try {
        const subRes = await SalesApi.fetch('/api/v1/saas/subscription');
        if (subRes.ok) {
          const sub = await subRes.json();
          document.getElementById('tenantBadge').textContent = `🏢 Tenant: ${sub.tenant_id}`;
          updatePlanHighlight(sub.plan_tier);
        }

        const usageRes = await SalesApi.fetch('/api/v1/saas/usage');
        if (usageRes.ok) {
          const usage = await usageRes.json();
          renderUsageMeters(usage);
        }
      } catch (err) {
        console.warn('API fetch error, keeping default authoritative display', err);
      }
    }

    function updatePlanHighlight(planTier) {
      document.querySelectorAll('.plan-card').forEach(c => c.classList.remove('current'));
      if (planTier === 'STARTER') document.getElementById('planStarter')?.classList.add('current');
      else if (planTier === 'ENTERPRISE') document.getElementById('planEnterprise')?.classList.add('current');
      else document.getElementById('planPro')?.classList.add('current');
    }

    function renderUsageMeters(usage) {
      if (!usage || !usage.meters) return;
      
      let hasWarning = false;
      const meters = usage.meters;
      
      // Tokens
      if (meters.tokens) {
        const cur = meters.tokens.current || 0;
        const lim = meters.tokens.limit || 10000000;
        const pct = Math.min(100, (cur / lim) * 100).toFixed(1);
        document.getElementById('tokensValues').textContent = `${cur.toLocaleString()} / ${lim.toLocaleString()}`;
        document.getElementById('tokensPct').textContent = `${pct}% Utilized`;
        const bar = document.getElementById('tokensProgressBar');
        bar.style.width = `${pct}%`;
        if (pct >= 90) bar.className = 'progress-bar danger';
        else if (pct >= 80) { bar.className = 'progress-bar warning'; hasWarning = true; }
        else bar.className = 'progress-bar';
      }

      // Voice
      if (meters.voice_seconds) {
        const curMin = Math.round((meters.voice_seconds.current || 0) / 60);
        const limMin = Math.round((meters.voice_seconds.limit || 60000) / 60);
        const pct = Math.min(100, (curMin / limMin) * 100).toFixed(1);
        document.getElementById('voiceValues').textContent = `${curMin} / ${limMin} min`;
        document.getElementById('voicePct').textContent = `${pct}% Utilized`;
        const bar = document.getElementById('voiceProgressBar');
        bar.style.width = `${pct}%`;
        if (pct >= 90) bar.className = 'progress-bar danger';
        else if (pct >= 80) { bar.className = 'progress-bar warning'; hasWarning = true; }
        else bar.className = 'progress-bar';
      }

      // API calls
      if (meters.api_calls) {
        const cur = meters.api_calls.current || 0;
        const lim = meters.api_calls.limit || 500000;
        const pct = Math.min(100, (cur / lim) * 100).toFixed(1);
        document.getElementById('apiValues').textContent = `${cur.toLocaleString()} / ${lim.toLocaleString()}`;
        document.getElementById('apiPct').textContent = `${pct}% Utilized`;
        const bar = document.getElementById('apiProgressBar');
        bar.style.width = `${pct}%`;
        if (pct >= 90) bar.className = 'progress-bar danger';
        else if (pct >= 80) { bar.className = 'progress-bar warning'; hasWarning = true; }
        else bar.className = 'progress-bar';
      }

      const warnBanner = document.getElementById('quotaWarningBanner');
      if (hasWarning) warnBanner.classList.remove('hidden');
      else warnBanner.classList.add('hidden');
    }

    function openQuotaModal() {
      document.getElementById('quotaModal').classList.remove('hidden');
    }

    function closeQuotaModal() {
      document.getElementById('quotaModal').classList.add('hidden');
    }

    async function handleQuotaSubmit(e) {
      e.preventDefault();
      const metric = document.getElementById('metricName').value;
      const limit = parseInt(document.getElementById('newLimit').value, 10);
      const reason = document.getElementById('quotaReason').value;

      try {
        const res = await SalesApi.fetch('/api/v1/saas/quotas/adjust', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ metric_name: metric, new_limit: limit, reason: reason })
        });
        if (res.ok) {
          alert('Quota successfully adjusted.');
          closeQuotaModal();
          fetchSaaSData();
        } else {
          alert('Adjustment failed: ' + (await res.text()));
        }
      } catch (err) {
        alert('Network or server error during quota adjustment');
      }
    }

    document.addEventListener('DOMContentLoaded', fetchSaaSData);
