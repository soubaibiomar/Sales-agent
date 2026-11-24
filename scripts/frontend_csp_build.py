"""
One-time, reproducible frontend migration for a strict Content-Security-Policy
(inspection findings F-20 / F-32). Idempotent: already-migrated pages are skipped.

For each src/frontend/*.html page:
  1. <style> blocks           -> css/pages/<page>.css   (<link rel="stylesheet">)
  2. inline <script> blocks   -> js/pages/<page>.js     (<script src> at the same place);
     near-identical duplicate blocks (copy-paste of the UI redesign, which bound every
     listener twice) are dropped.
  3. on<event>="code" handlers -> data-on-<event>="hN" attributes, bound with
     addEventListener by js/pages/<page>.handlers.js (same `this`/`event` semantics).
  4. the per-page sidebar markup (6 inconsistent variants) -> <div data-app-nav></div>,
     rendered by js/app_shell.js from a single navigation definition.
  5. Google Fonts links removed (blocked by the CSP; the system font stack is used).
  6. js/api_client.js (auth + API client) loaded first, in <head>.
The result needs no 'unsafe-inline' / 'unsafe-eval' / 'unsafe-hashes' for scripts.

Usage: python scripts/frontend_csp_build.py
"""
import difflib
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "frontend"))
MARKER = "<!-- csp-build: migrated -->"


def migrate(path: str) -> dict:
    page = os.path.splitext(os.path.basename(path))[0]
    html = open(path, encoding="utf-8").read()
    if MARKER in html:
        return {"page": page, "skipped": True}
    os.makedirs(os.path.join(ROOT, "css", "pages"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "js", "pages"), exist_ok=True)
    stats = {"page": page, "styles": 0, "scripts": 0, "duplicate_scripts_removed": 0, "handlers": 0, "sidebar": False}

    # 1. <style> blocks
    styles = re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)
    if styles:
        with open(os.path.join(ROOT, "css", "pages", f"{page}.css"), "w", encoding="utf-8") as f:
            f.write(f"/* Extracted from {page}.html by scripts/frontend_csp_build.py */\n" + "\n".join(s.strip() + "\n" for s in styles))
        first = [True]

        def _style(m):
            if first[0]:
                first[0] = False
                return f'<link rel="stylesheet" href="css/pages/{page}.css">'
            return ""
        html = re.sub(r"<style[^>]*>.*?</style>", _style, html, flags=re.S)
        stats["styles"] = len(styles)

    # 2. inline scripts (dedupe near-identical copies)
    kept = []

    def _script(m):
        body = m.group(1)
        if not body.strip():
            return ""
        for prev in kept:
            if difflib.SequenceMatcher(None, prev, body).ratio() > 0.98:
                stats["duplicate_scripts_removed"] += 1
                return ""
        kept.append(body)
        name = f"{page}.js" if len(kept) == 1 else f"{page}.{len(kept)}.js"
        with open(os.path.join(ROOT, "js", "pages", name), "w", encoding="utf-8") as f:
            f.write(f"/* Extracted from {page}.html by scripts/frontend_csp_build.py */\n{body.strip()}\n")
        return f'<script src="js/pages/{name}"></script>'
    html = re.sub(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", _script, html, flags=re.S)
    stats["scripts"] = len(kept)

    # 3. inline event handlers
    handlers = {}

    def _handler(m):
        event, code = m.group(1), m.group(2)
        hid = f"h{len(handlers) + 1}"
        handlers[hid] = (event, code.replace("&quot;", '"').replace("&#39;", "'").replace("&amp;", "&"))
        return f' data-on-{event}="{hid}"'
    html = re.sub(r'\son([a-z]+)="([^"]*)"', _handler, html)
    if handlers:
        lines = [f"/* Event handlers extracted from {page}.html (scripts/frontend_csp_build.py). */",
                 "(function () {", "  'use strict';", "  var H = {"]
        for hid, (event, code) in handlers.items():
            body = code.strip().rstrip(";")
            lines.append(f"    {json.dumps(hid)}: function (event) {{ {body}; }},")
        lines += ["  };",
                  "  function bind() {",
                  "    Object.keys(H).forEach(function (hid) {",
                  "      document.querySelectorAll('[data-on-click=\"' + hid + '\"],[data-on-change=\"' + hid + '\"],"
                  "[data-on-submit=\"' + hid + '\"],[data-on-input=\"' + hid + '\"]').forEach(function (el) {",
                  "        ['click', 'change', 'submit', 'input'].forEach(function (evt) {",
                  "          if (el.getAttribute('data-on-' + evt) === hid) {",
                  "            el.addEventListener(evt, function (e) { return H[hid].call(el, e); });",
                  "          }",
                  "        });",
                  "      });",
                  "    });",
                  "  }",
                  "  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', bind); } else { bind(); }",
                  "})();", ""]
        with open(os.path.join(ROOT, "js", "pages", f"{page}.handlers.js"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        html = html.replace("</head>", f'  <script src="js/pages/{page}.handlers.js" defer></script>\n</head>', 1)
        stats["handlers"] = len(handlers)

    # 4. shared sidebar
    new_html, n = re.subn(r'(<aside class="sidebar"[^>]*>).*?(</aside>)', r'\1<div data-app-nav></div>\2', html, count=1, flags=re.S)
    if n:
        html, stats["sidebar"] = new_html, True

    # 5. Google Fonts
    html = re.sub(r'\s*<link[^>]*fonts\.(googleapis|gstatic)\.com[^>]*>', "", html)

    # 6. API client first
    if "js/api_client.js" not in html:
        html = re.sub(r"(<head[^>]*>)", r'\1\n  <script src="js/api_client.js"></script>', html, count=1)

    html = html.replace("</html>", f"{MARKER}\n</html>", 1)
    open(path, "w", encoding="utf-8").write(html)
    return stats


if __name__ == "__main__":
    results = [migrate(os.path.join(ROOT, f)) for f in sorted(os.listdir(ROOT)) if f.endswith(".html")]
    print(json.dumps(results, indent=1))
    sys.exit(0)
