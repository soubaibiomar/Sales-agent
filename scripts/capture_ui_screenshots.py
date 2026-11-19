#!/usr/bin/env python3
"""
SALES AI MANAGEMENT PLATFORM — UI/UX SCREENSHOT CAPTURE & VERIFICATION
Captures automated Chrome headless screenshots for Desktop (1440x900) and
Mobile (390x844) viewport breakpoints, storing them in evidence/frontend-ui-ux/.
"""

import os
import subprocess

CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EVIDENCE_DIR = r"C:\Users\omar\Documents\Sales agent\evidence\frontend-ui-ux"
FRONTEND_DIR = r"C:\Users\omar\Documents\Sales agent\src\frontend"

os.makedirs(EVIDENCE_DIR, exist_ok=True)

TARGETS = [
    ("index.html", "dashboard_desktop.png", "1440,900"),
    ("index.html", "dashboard_mobile.png", "390,844"),
    ("inbox.html", "inbox_desktop.png", "1440,900"),
    ("inbox.html", "inbox_mobile.png", "390,844"),
    ("quote_builder.html", "quote_builder_desktop.png", "1440,900"),
    ("quote_builder.html", "quote_builder_mobile.png", "390,844"),
    ("pipeline.html", "pipeline_desktop.png", "1440,900"),
    ("catalog.html", "catalog_desktop.png", "1440,900"),
    ("orders.html", "orders_desktop.png", "1440,900"),
    ("approvals.html", "approvals_desktop.png", "1440,900")
]

def capture_screenshots():
    print(f"Starting automated UI screenshot capture via Google Chrome headless...")
    for html_file, out_name, size in TARGETS:
        html_path = os.path.join(FRONTEND_DIR, html_file)
        out_path = os.path.join(EVIDENCE_DIR, out_name)
        url = f"file:///{html_path.replace(os.sep, '/')}"

        cmd = [
            CHROME_EXE,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            f"--screenshot={out_path}",
            f"--window-size={size}",
            "--virtual-time-budget=2000",
            url
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if os.path.exists(out_path):
            file_size = os.path.getsize(out_path)
            print(f"  [OK] {out_name:28} ({size}) -> {file_size:,} bytes")
        else:
            print(f"  [FAIL] {out_name} failed: {res.stderr}")

if __name__ == "__main__":
    capture_screenshots()
