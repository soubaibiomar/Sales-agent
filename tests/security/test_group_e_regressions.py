"""
Regression tests for remediation group E of the independent inspection
(F-20 frontend: login, API wiring, strict CSP; F-32 UI defects; F-15 browser voice).

These are static checks over the served frontend plus the CSP header of the real app.
"""
import re
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "src" / "frontend"
PAGES = sorted(FRONTEND.glob("*.html"))
PUBLIC_PAGES = {"login.html", "quote_view.html"}
SCRIPTS = sorted((FRONTEND / "js").rglob("*.js"))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_pages_exist():
    assert len(PAGES) >= 28
    assert (FRONTEND / "login.html").exists()


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_inline_script_or_style_blocks(page):
    html = read(page)
    # Every <script> must load an external same-origin file; no inline code.
    for tag in re.findall(r"<script\b[^>]*>", html, flags=re.I):
        assert re.search(r'\bsrc="(?!https?:|//)[^"]+\.js"', tag), f"inline or external-origin script in {page.name}: {tag}"
    for body in re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.I | re.S):
        assert not body.strip(), f"inline script body in {page.name}"
    assert "<style" not in html.lower(), f"inline <style> block in {page.name}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_inline_event_handlers_or_js_urls(page):
    html = read(page)
    assert not re.search(r"\son[a-z]+\s*=\s*[\"']", html, flags=re.I), f"inline on* handler in {page.name}"
    assert "javascript:" not in html.lower(), f"javascript: URL in {page.name}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_third_party_resources(page):
    html = read(page)
    assert not re.search(r'(?:src|href)="(?:https?:)?//', html), f"third-party resource in {page.name}"


def test_stylesheets_have_no_third_party_imports():
    for css in (FRONTEND / "css").rglob("*.css"):
        assert "fonts.googleapis" not in read(css), css.name
        assert not re.search(r"@import\s+url\(['\"]?https?:", read(css)), css.name


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_every_page_loads_api_client_first(page):
    html = read(page)
    scripts = re.findall(r'<script\b[^>]*src="([^"]+)"', html)
    assert scripts and scripts[0] == "js/api_client.js", f"{page.name} must load api_client.js first"
    assert "js/data_views.js" in scripts


@pytest.mark.parametrize("page", [p for p in PAGES if p.name not in PUBLIC_PAGES], ids=lambda p: p.name)
def test_app_pages_use_shared_navigation(page):
    html = read(page)
    assert "data-app-nav" in html, f"{page.name} must use the shared navigation placeholder"
    assert "js/app_shell.js" in html


def test_auth_guard_protects_all_but_public_pages():
    js = read(FRONTEND / "js" / "api_client.js")
    m = re.search(r"PUBLIC_PAGES\s*=\s*\[([^\]]*)\]", js)
    assert m, "api_client.js must declare PUBLIC_PAGES"
    public = set(re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)))
    assert public == PUBLIC_PAGES
    assert "'?next='" in js and "goToLogin()" in js


@pytest.mark.parametrize("path", [*PAGES, *SCRIPTS], ids=lambda p: p.name)
def test_no_hardcoded_tenant_or_tokens(path):
    text = read(path)
    for needle in ("tenant-acme-corp", "mock-manager-token", "default-tenant", "Atlas Commerce", "Omar A.", "Bonjour Omar"):
        assert needle not in text, f"{needle!r} hardcoded in {path.name}"


@pytest.mark.parametrize("path", [p for p in SCRIPTS if p.name != "api_client.js"], ids=lambda p: p.name)
def test_scripts_never_send_client_tenant_header(path):
    assert not re.search(r"X-Tenant-I[dD]", read(path)), f"{path.name} sets a client tenant header"


def test_api_client_strips_client_identity_headers():
    js = read(FRONTEND / "js" / "api_client.js")
    assert "headers.delete('X-Tenant-ID')" in js
    assert "sessionStorage" in js and "localStorage.setItem" not in js


def test_template_interpolations_are_escaped():
    """Every ${...} inside an HTML template literal goes through SalesViews.esc / V.esc / V.money etc."""
    unsafe = []
    for path in SCRIPTS:
        src = read(path)
        for tpl in re.findall(r"`([^`]*<[^`]*)`", src):
            for expr in re.findall(r"\$\{([^}]*)\}", tpl):
                e = expr.strip()
                if re.match(r"^(SalesViews|V)\.(esc|money|date)\(", e) or "esc(" in e:
                    continue
                if re.fullmatch(r"[\w.]+\s*\?\s*'[^']*'\s*:\s*'[^']*'", e) or re.fullmatch(r"\d+", e):
                    continue  # constant class names / numbers
                if e.endswith(".join('')") or ".map(" in e:
                    continue  # nested templates are checked on their own
                unsafe.append(f"{path.name}: ${{{e}}}")
    assert not unsafe, "unescaped template interpolations:\n" + "\n".join(unsafe)


def test_voice_agent_uses_real_capture_and_signed_stream():
    js = read(FRONTEND / "js" / "pages" / "voice_agent.js")
    assert "getUserMedia" in js and "AudioWorkletNode" in js
    assert "js/audio/pcm-capture-worklet.js" in js
    assert "/api/v1/voice/ws/" in js and "session_token" in js
    assert "innerHTML" not in js and "innerText" not in js, "voice transcripts must render via textContent"
    worklet = read(FRONTEND / "js" / "audio" / "pcm-capture-worklet.js")
    assert "registerProcessor('pcm-capture'" in worklet and "Int16Array" in worklet


def test_voice_agent_page_has_single_script_and_no_seeded_caller():
    html = read(FRONTEND / "voice_agent.html")
    assert html.count('src="js/pages/voice_agent.js"') == 1  # F-32: no duplicated handler block
    assert 'value="+212' not in html


def test_quote_builder_never_computes_money_client_side():
    js = read(FRONTEND / "js" / "pages" / "quote_builder.js")
    html = read(FRONTEND / "quote_builder.html")
    assert "/api/v1/quotes" in js and "/items" in js
    # Totals come from the server response fields, not arithmetic on prices.
    for field in ("subtotal_cents", "tax_total_cents", "grand_total_cents", "discount_total_cents"):
        assert f"quote.{field}" in js
    assert not re.search(r"base_price_cents\s*\*", js), "client-side price arithmetic"
    for demo in ("Atlas Services", "Q-2026-0158", "154 900,00"):
        assert demo not in html


@pytest.mark.parametrize("page", [p for p in PAGES if p.name != "login.html"], ids=lambda p: p.name)
def test_pages_without_api_calls_are_labelled_as_demo(page):
    """A page that never calls the API must not pass off its static content as live data."""
    stem = page.stem
    scripts = [read(p) for p in (FRONTEND / "js" / "pages").glob(stem + "*.js")]
    calls_api = any(re.search(r"SalesApi\.fetch\(|getJson\(", s) for s in scripts)
    if not calls_api:
        assert "<body data-demo-page>" in read(page), f"{page.name} shows static data without a demo label"


def test_demo_widgets_are_labelled():
    views = read(FRONTEND / "js" / "data_views.js")
    assert "markDemo" in views and "Données d'exemple" in views


@pytest.mark.asyncio
async def test_served_app_sends_strict_csp():
    from src.backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/app/login.html")
    assert r.status_code == 200
    csp = r.headers["Content-Security-Policy"]
    directives = {d.split()[0]: d.split()[1:] for d in (x.strip() for x in csp.split(";")) if d}
    assert directives["script-src"] == ["'self'"]
    assert directives["style-src"] == ["'self'"]
    assert directives["object-src"] == ["'none'"]
    assert directives["frame-ancestors"] == ["'none'"]
    assert "'unsafe-eval'" not in csp
    assert "microphone=(self)" in r.headers["Permissions-Policy"]
