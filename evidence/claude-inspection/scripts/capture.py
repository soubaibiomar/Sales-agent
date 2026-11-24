import subprocess, os, sys, tempfile, shutil, time, urllib.request
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
root = sys.argv[1]
pages = ("index pipeline inbox catalog quote_builder quote_view approvals orders checkout invoices inventory procurement "
         "logistics support schedule agent_workspace voice_agent voice_copilot voice_observability analytics_dashboard "
         "saas_admin_dashboard ai_governance ai_operations_dashboard workflows workflow_reliability_dashboard notifications "
         "integrations release_console").split()
for _ in range(30):
    try:
        urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2); urllib.request.urlopen("http://127.0.0.1:8790/index.html", timeout=2); break
    except Exception: time.sleep(1)
modes = {"served_8765": "http://127.0.0.1:8765/app/{}.html", "static_nocsp_8790": "http://127.0.0.1:8790/{}.html"}
ok = fail = 0
for mode, tpl in modes.items():
    d = os.path.join(root, "evidence", "claude-inspection", "screenshots", mode); os.makedirs(d, exist_ok=True)
    for p in pages:
        for w, h in ((1440, 900), (390, 844)):
            out = os.path.join(d, f"{p}_{w}x{h}.png")
            prof = tempfile.mkdtemp(prefix="edgecap_")
            try:
                subprocess.run([EDGE, "--headless=new", "--disable-gpu", f"--user-data-dir={prof}", "--hide-scrollbars",
                                "--virtual-time-budget=3000", f"--window-size={w},{h}", f"--screenshot={out}", tpl.format(p)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            except subprocess.TimeoutExpired:
                pass
            shutil.rmtree(prof, ignore_errors=True)
            if os.path.exists(out) and os.path.getsize(out) > 1000: ok += 1
            else: fail += 1; print("FAILED", mode, p, w)
print("ok", ok, "fail", fail)
