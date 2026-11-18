"""
Applies verified RLS policies to live PostgreSQL schema.
"""
import psycopg

PG_ADMIN_CONN = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"

def apply_rls():
    conn = psycopg.connect(PG_ADMIN_CONN)
    tables = [
        ("organization_sites", "tenant_isolation_sites"),
        ("users", "tenant_isolation_users"),
        ("user_roles", "tenant_isolation_user_roles"),
        ("session_revocations", "tenant_isolation_session_revocations"),
        ("audit_logs", "tenant_isolation_audit_logs"),
        ("feature_flags", "tenant_isolation_feature_flags"),
    ]
    with conn.cursor() as cur:
        for tbl, pname in tables:
            cur.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
            cur.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;")
            cur.execute(f"DROP POLICY IF EXISTS {pname} ON {tbl};")
            cur.execute(f"""
                CREATE POLICY {pname} ON {tbl}
                FOR ALL
                USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
                WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
            """)
        conn.commit()
    print("RLS policies applied successfully to all 6 tables.")
    conn.close()

if __name__ == "__main__":
    apply_rls()
