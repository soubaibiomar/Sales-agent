"""
Regression tests for the Selia UI rollout (owner design, 2026-11-25) and the bugs it exposed.
"""
import logging
import re
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "src" / "frontend"
DESIGNED = ["index", "clients", "pipeline", "quotes", "orders", "schedule", "analytics_dashboard", "profile", "inbox"]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("page", DESIGNED)
def test_designed_pages_use_selia_shell(page):
    html = read(FRONTEND / f"{page}.html")
    assert "<title>Selia" in html
    assert '<header class="topbar"></header>' in html  # topbar rendered by app_shell.js
    assert f'src="js/pages/{page}.js"' in html and (FRONTEND / "js" / "pages" / f"{page}.js").exists()
    assert (FRONTEND / "css" / "pages" / f"{page}.css").exists()


def test_shell_navigation_matches_design():
    shell = read(FRONTEND / "js" / "app_shell.js")
    for href, label in [("index.html", "Tableau de bord"), ("clients.html", "Clients"), ("pipeline.html", "Opportunités"),
                        ("quotes.html", "Devis"), ("orders.html", "Commandes"), ("schedule.html", "Rendez-vous"),
                        ("inbox.html", "Conversations"), ("analytics_dashboard.html", "Analyses")]:
        assert f"['{href}', '{label}'" in shell
    assert "Créer rapidement" in shell and "bottom-nav" in shell
    # the old shell's fabricated notifications are gone
    assert "3 non lues" not in shell and "DEV-2026-0933" not in shell


def test_design_tokens_present():
    css = read(FRONTEND / "css" / "design_system.css")
    for token in ("--s-olive: #5D7A2D", "--s-terra: #CF6639", "--s-bg: #F8F1E9"):
        assert token in css
    assert not re.search(r"minmax\([^()]*minmax\(", css)


@pytest.mark.parametrize("page", DESIGNED)
def test_designed_pages_show_no_invented_figures(page):
    text = read(FRONTEND / f"{page}.html")
    for fake in ("1 410 077", "256", "Atlas Services", "Salle LAHLOU", "+12,5", "Sarah"):
        assert fake not in text, f"{fake!r} hardcoded in {page}.html"


def test_access_log_arguments_keep_their_shape():
    """uvicorn's access formatter unpacks record.args: the redaction filter must not flatten them."""
    from src.backend.core.operations import RedactingFilter
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:5000", "GET", "/api?email=victim@example.com", "1.1", 200), None)
    assert RedactingFilter().filter(rec)
    client, method, path, version, code = rec.args
    assert "victim@example.com" not in path and code == 200


def test_profile_update_schema_accepts_only_display_name():
    from pydantic import ValidationError
    from src.backend.schemas.identity import MyProfileUpdateRequest
    assert MyProfileUpdateRequest(full_name="Sarah").full_name == "Sarah"
    for bad in ({"full_name": "x", "roles": ["tenant_admin"]}, {"full_name": "x", "is_active": False}, {"full_name": ""}):
        with pytest.raises(ValidationError):
            MyProfileUpdateRequest(**bad)


@pytest.mark.asyncio
async def test_profile_update_requires_authentication_and_assets_revalidate():
    from src.backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch("/api/v1/users/me", json={"full_name": "Mallory"})
        page = await c.get("/app/index.html")
    assert r.status_code == 401
    assert page.headers.get("Cache-Control") == "no-cache"


def test_profile_endpoint_builds_response_before_commit():
    src = read(ROOT / "src" / "backend" / "api" / "users.py")
    body = src[src.index("async def update_my_profile"):src.index('@router.get("", response_model=List[UserResponse])')]
    assert "db.refresh(user)" not in body
    assert body.index("response = UserResponse(") < body.index("await db.commit()")
