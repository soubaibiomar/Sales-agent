"""Generate a Selia application page with the standard, CSP-clean skeleton.

Usage (from the repository root):
    python scripts/selia_page.py <page> "<Title>" <body_fragment.html> [--charts]

The fragment is placed inside <main class="content-wrapper">. The page loads, in order:
api_client.js (auth guard) -> data_views.js -> design_system.css + css/pages/<page>.css,
then charts.js (optional), app_shell.js and js/pages/<page>.js at the end of <body>.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "frontend"

TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <script src="js/api_client.js"></script>
  <script src="js/data_views.js"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Selia — {title}</title>
  <link rel="stylesheet" href="css/design_system.css">
  <link rel="stylesheet" href="css/pages/{page}.css">
</head>
<body>
  <div class="app-container">
    <aside class="sidebar"><div data-app-nav></div></aside>
    <div class="main-wrapper">
      <header class="topbar"></header>
      <main class="content-wrapper" id="main">
{body}
      </main>
    </div>
  </div>
{charts}  <script src="js/app_shell.js"></script>
  <script src="js/pages/{page}.js"></script>
</body>
</html>
"""


def build(page: str, title: str, body: str, charts: bool) -> Path:
    out = ROOT / f"{page}.html"
    body = "\n".join(("        " + line) if line.strip() else "" for line in body.strip("\n").splitlines())
    out.write_text(TEMPLATE.format(page=page, title=title, body=body,
                                   charts='  <script src="js/charts.js"></script>\n' if charts else ""),
                   encoding="utf-8")
    return out


if __name__ == "__main__":
    page, title, fragment = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    print(build(page, title, fragment.read_text(encoding="utf-8"), "--charts" in sys.argv))
