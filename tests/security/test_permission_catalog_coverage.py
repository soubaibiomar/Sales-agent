"""
Permission catalog coverage (inspection finding F-34).

Every permission an API route requires must be
  1. seeded in the permission catalog (infra/init-db.sql), and
  2. granted to at least one non-super-admin default role,
otherwise the feature is silently reachable only by super_admin. The platform-level
wildcard '*' (tenant provisioning) is the only intentional super_admin-only gate.
"""
import re
from pathlib import Path

from fastapi.routing import APIRoute, APIWebSocketRoute

from src.backend.main import app
from src.backend.core.policy_service import DEFAULT_ROLE_PERMISSIONS

SUPER_ADMIN_ONLY = {"*"}


def _routes(routes):
    for r in routes:
        if isinstance(r, (APIRoute, APIWebSocketRoute)):
            yield r
        elif type(r).__name__ == "_IncludedRouter":
            yield from _routes(r.original_router.routes)


def _required_permissions(dependant, acc):
    for sub in dependant.dependencies:
        call = sub.call
        if getattr(call, "__name__", "") == "permission_checker" and call.__closure__:
            acc.update(c.cell_contents for c in call.__closure__ if isinstance(c.cell_contents, str))
        _required_permissions(sub, acc)
    return acc


def _route_permissions():
    used = {}
    for route in _routes(app.routes):
        for perm in _required_permissions(route.dependant, set()):
            used.setdefault(perm, []).append(route.path)
    return used


def test_routes_use_permissions_at_all():
    assert len(_route_permissions()) >= 30


def test_every_route_permission_is_granted_to_a_regular_role():
    granted = {p for role, perms in DEFAULT_ROLE_PERMISSIONS.items() if role != "super_admin" for p in perms}
    missing = {p: paths[:3] for p, paths in _route_permissions().items()
               if p not in granted and p not in SUPER_ADMIN_ONLY}
    assert not missing, f"Permissions only reachable by super_admin: {missing}"


def test_every_route_permission_is_in_the_seeded_catalog():
    sql = (Path(__file__).resolve().parents[2] / "infra" / "init-db.sql").read_text(encoding="utf-8")
    seeded = set(re.findall(r"\('perm_[a-z_]+', '([a-z_]+:[a-z_]+)'", sql))
    missing = sorted(set(_route_permissions()) - seeded - SUPER_ADMIN_ONLY)
    assert not missing, f"Route permissions missing from the permission catalog: {missing}"


def test_customer_role_cannot_reach_staff_apis():
    staff_only = {"crm:read", "orders:manage", "support:manage", "voice:copilot", "integrations:manage"}
    assert not staff_only & set(DEFAULT_ROLE_PERMISSIONS["customer"])
