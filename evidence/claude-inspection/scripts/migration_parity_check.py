"""Fresh DB via the migration runner vs fresh DB via infra/init-db.sql: compare catalogs.
Also re-runs the runner (idempotence) and checks a tampered file is rejected. Drops both DBs."""
import json, re, sys, secrets, shutil, tempfile
from pathlib import Path
import psycopg
root = Path(sys.argv[1]); sys.path.insert(0, str(root))
from src.backend.migrations import runner

pw = re.search(r"POSTGRES_PASSWORD:-([^}]+)\}", (root / "infra/docker-compose.yml").read_text()).group(1)
base = f"postgresql://postgres:{pw}@127.0.0.1:5432/"
A, B = "mig_runner_check", "mig_initsql_check"

def q(db, s):
    with psycopg.connect(base + db) as c:
        return sorted(tuple(r) for r in c.execute(s).fetchall())

CAT = {
 "columns": "SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='public' AND table_name<>'schema_migrations'",
 "rls": "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relname<>'schema_migrations'",
 "policies": "SELECT tablename, policyname, permissive, array_to_string(roles, ','), cmd, qual, with_check FROM pg_policies WHERE schemaname='public'",
 "constraints": "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace='public'::regnamespace AND conrelid::regclass::text<>'schema_migrations'",
 "functions": "SELECT proname, prosecdef, pg_get_function_identity_arguments(oid) FROM pg_proc WHERE pronamespace='public'::regnamespace",
 "triggers": "SELECT tgrelid::regclass::text, tgname FROM pg_trigger WHERE NOT tgisinternal",
 "grants": "SELECT table_name, privilege_type FROM information_schema.role_table_grants WHERE grantee='sales_app_user'",
 "indexes": "SELECT tablename, indexname FROM pg_indexes WHERE schemaname='public' AND tablename<>'schema_migrations'",
 "seed_permissions": "SELECT id FROM permissions",
 "seed_roles": "SELECT name FROM roles",
}
out = {}
with psycopg.connect(base + "postgres", autocommit=True) as c:
    for d in (A, B):
        c.execute(f"DROP DATABASE IF EXISTS {d} WITH (FORCE)"); c.execute(f"CREATE DATABASE {d}")
try:
    app_pw = None  # roles are cluster-wide: never rotate the dev role here
    ran = runner.migrate(base + A, app_pw, log=lambda m: None)
    out["runner_applied"] = len(ran)
    out["rerun_applied"] = len(runner.migrate(base + A, None, log=lambda m: None))
    with psycopg.connect(base + B, autocommit=True) as c:
        c.execute((root / "infra/init-db.sql").read_text(encoding="utf-8"))
    diffs = {}
    for k, s in CAT.items():
        a, b = set(q(A, s)), set(q(B, s))
        diffs[k] = {"runner_only": sorted(map(str, a - b))[:200], "initsql_only": sorted(map(str, b - a))[:200], "count": len(a)}
    out["diff"] = diffs
    # tamper check
    tmp = Path(tempfile.mkdtemp())
    for p in runner.MIGRATIONS_DIR.glob("0*.sql"):
        shutil.copy(p, tmp / p.name)
    (tmp / "001_initial_schema.sql").write_text((tmp / "001_initial_schema.sql").read_text(encoding="utf-8") + "\n-- edited\n", encoding="utf-8")
    try:
        runner.migrate(base + A, None, directory=tmp, log=lambda m: None); out["tamper_rejected"] = False
    except runner.MigrationError as e:
        out["tamper_rejected"] = "checksum mismatch" in str(e)
    shutil.rmtree(tmp)
    # failing migration stops and is not recorded
    tmp = Path(tempfile.mkdtemp())
    for p in runner.MIGRATIONS_DIR.glob("0*.sql"):
        shutil.copy(p, tmp / p.name)
    (tmp / "999_broken.sql").write_text("CREATE TABLE ok_part(id int);\nSELECT * FROM no_such_table;\n", encoding="utf-8")
    try:
        runner.migrate(base + A, None, directory=tmp, log=lambda m: None); out["broken_stops_release"] = False
    except runner.MigrationError:
        out["broken_stops_release"] = True
    out["broken_rolled_back"] = q(A, "SELECT to_regclass('ok_part')::text") == [(None,)]
    out["broken_not_recorded"] = q(A, "SELECT count(*) FROM schema_migrations WHERE version='999'") == [(0,)]
    shutil.rmtree(tmp)
    out["app_role_flags"] = q(A, "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='sales_app_user'")
finally:
    with psycopg.connect(base + "postgres", autocommit=True) as c:
        for d in (A, B):
            c.execute(f"DROP DATABASE IF EXISTS {d} WITH (FORCE)")
print(json.dumps(out, indent=1, default=str))
