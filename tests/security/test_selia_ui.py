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


# ---------------------------------------------------------------- module pages (batches 1-3)
ALL_PAGES = sorted(FRONTEND.glob("*.html"))


@pytest.mark.parametrize("page", ALL_PAGES, ids=lambda p: p.name)
def test_every_page_is_selia_and_has_no_legacy_handlers(page):
    html = read(page)
    assert "<title>Selia" in html
    assert ".handlers.js" not in html
    assert "alert(" not in html


def test_no_legacy_handler_scripts_or_alerts_left():
    assert not list((FRONTEND / "js" / "pages").glob("*.handlers.js"))
    for js in (FRONTEND / "js").rglob("*.js"):
        assert "alert(" not in read(js), f"alert() in {js.name}"


def test_integrations_page_uses_existing_endpoints():
    js = read(FRONTEND / "js" / "pages" / "integrations.js")
    assert "/api/v1/integrations/outbox/dlq" in js and "/api/v1/integrations/status" in js
    assert not re.search(r"/integrations/outbox['\"]", js)


def test_public_quote_page_performs_real_decisions():
    js = read(FRONTEND / "js" / "pages" / "quote_view.js")
    assert "/public?token=" in js and "'/' + kind" in js and "acceptance_token" in js


def test_quota_adjustment_requires_admin_and_mfa():
    src = read(ROOT / "src" / "backend" / "api" / "saas_admin.py")
    body = src[src.index('@router.post("/quotas/adjust")'):]
    assert 'require_permission("saas:manage")' in body.split("):")[0] + "):"
    assert "require_privileged_mfa" in body.split('"""')[0]


def test_ai_health_is_not_public():
    src = read(ROOT / "src" / "backend" / "api" / "ai_governance.py")
    sig = src[src.index('@router.get("/health")'):src.index('@router.post("/generate"')]
    assert 'require_permission("ai:manage")' in sig


@pytest.mark.asyncio
async def test_public_quote_view_rejects_bad_links_and_quota_needs_auth():
    from src.backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        bad = await c.get("/api/v1/quotes/q_does_not_exist/public", params={"token": "not-a-valid-signed-token"})
        quota = await c.post("/api/v1/saas/quotas/adjust", json={"max_seats": 999})
    assert bad.status_code == 401
    assert quota.status_code == 401


def test_role_matrix_has_no_manage_without_read_gaps():
    """A role that can manage/create a domain must also be able to read and create in it."""
    from src.backend.core.policy_service import DEFAULT_ROLE_PERMISSIONS as R
    assert {"procurement:read", "quotes:create"} <= set(R["tenant_admin"])
    assert "quotes:create" in R["sales_manager"]
    for role, perms in R.items():
        for p in perms:
            if p.endswith(":manage"):
                domain = p.split(":")[0]
                if domain in ("procurement", "logistics", "support", "workflows"):
                    assert any(q in perms for q in (domain + ":read", domain + ":manage")), (role, domain)


def test_procurement_api_only_calls_existing_service_methods():
    """The list endpoints used to call ProcurementService methods that did not exist (500s)."""
    from src.backend.domains.procurement.service import ProcurementService
    api = read(ROOT / "src" / "backend" / "api" / "procurement.py")
    for meth in set(re.findall(r"service\.([a-z_]+)\(", api)):
        assert hasattr(ProcurementService, meth), meth


@pytest.mark.asyncio
async def test_duplicate_key_is_a_409_not_a_500():
    from sqlalchemy.exc import IntegrityError
    from src.backend.main import integrity_error_handler

    class _Orig(Exception):
        sqlstate = "23505"

    class _OrigFk(Exception):
        sqlstate = "23503"

    dup = await integrity_error_handler(None, IntegrityError("INSERT", {}, _Orig("violates unique constraint uq_secret_name")))
    fk = await integrity_error_handler(None, IntegrityError("INSERT", {}, _OrigFk("violates foreign key fk_secret")))
    assert dup.status_code == 409 and b"uq_secret_name" not in dup.body
    assert fk.status_code == 422 and b"fk_secret" not in fk.body


@pytest.mark.asyncio
async def test_agent_activity_route_is_not_shadowed_by_role_lookup():
    from src.backend.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/agents/activity")
    assert r.status_code == 401  # reaches the activity endpoint's auth, not "role 'activity' not found"
    src = read(ROOT / "src" / "backend" / "api" / "agent_ecosystem.py")
    assert src.index('@router.get("/activity"') < src.index('@router.get("/{role_id}"')
