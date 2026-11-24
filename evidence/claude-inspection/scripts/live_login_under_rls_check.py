"""
Post-remediation live check (F-09): the real API, connected as the least-privileged
RLS role, can log a user in and serve authenticated data. Creates a throwaway tenant
and user, exercises the HTTP API, then deletes them. Prints no secrets.
"""
import json, re, sys, time, uuid
from pathlib import Path
import httpx, psycopg

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from src.backend.core.security import SecurityService  # noqa: E402

su_pw = re.search(r"POSTGRES_PASSWORD:-([^}]+)\}", (root / "infra/docker-compose.yml").read_text()).group(1)
su = psycopg.connect(f"postgresql://postgres:{su_pw}@127.0.0.1:5432/sales_ai_db", autocommit=True)
tenant, user = "t_live_" + uuid.uuid4().hex[:8], "u_live_" + uuid.uuid4().hex[:8]
email, password = f"{user}@live-check.example.com", "Live-Check-" + uuid.uuid4().hex[:12]
out = {}
try:
    su.execute("INSERT INTO tenants(id,name,slug) VALUES (%s,%s,%s)", (tenant, tenant, tenant))
    su.execute("INSERT INTO users(id,tenant_id,email,hashed_password,full_name) VALUES (%s,%s,%s,%s,'Live Check')",
               (user, tenant, email, SecurityService.hash_password(password)))
    for _ in range(30):
        try:
            if httpx.get("http://127.0.0.1:8765/health", timeout=2).status_code == 200:
                break
        except Exception:
            time.sleep(1)
    with httpx.Client(base_url="http://127.0.0.1:8765", timeout=10) as c:
        r = c.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password-123"})
        out["login_wrong_password_status"] = r.status_code
        r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
        out["login_status"] = r.status_code
        tok = r.json().get("access_token") if r.status_code == 200 else None
        out["access_token_issued"] = bool(tok)
        if tok:
            r = c.get("/api/v1/voice/callbacks", headers={"Authorization": f"Bearer {tok}"})
            out["authenticated_call_status"] = r.status_code
            out["authenticated_call_tenant_matches"] = r.json().get("tenant_id") == tenant
        r = c.get("/api/v1/notifications/history", headers={"X-Tenant-ID": tenant})
        out["header_only_call_status"] = r.status_code
finally:
    su.execute("DELETE FROM audit_logs WHERE tenant_id=%s", (tenant,))
    su.execute("DELETE FROM users WHERE id=%s", (user,))
    su.execute("DELETE FROM tenants WHERE id=%s", (tenant,))
    su.close()
print(json.dumps(out, indent=1))
