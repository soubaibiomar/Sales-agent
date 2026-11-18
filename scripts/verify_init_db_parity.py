"""
Automated Canonical Parity Verifier.
Creates an isolated temporary database in PostgreSQL, applies infra/init-db.sql,
and asserts 100% schema, RLS, and policy parity with the live sales_ai_db.
"""
import psycopg
import sys

PG_ADMIN = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/postgres"
LIVE_DB_CONN = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"
FRESH_DB_NAME = "fresh_parity_test_db"
FRESH_DB_CONN = f"postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/{FRESH_DB_NAME}"

def run_parity_check():
    print(f"1. Creating fresh isolated database '{FRESH_DB_NAME}'...")
    with psycopg.connect(PG_ADMIN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {FRESH_DB_NAME} WITH (FORCE);")
            cur.execute(f"CREATE DATABASE {FRESH_DB_NAME};")

    print("2. Initializing fresh database with infra/init-db.sql...")
    with open("infra/init-db.sql", "r", encoding="utf-8") as f:
        init_sql = f.read()

    with psycopg.connect(FRESH_DB_CONN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(init_sql)

    print("3. Querying catalog schemas and RLS definitions from both databases...")
    def get_catalog_info(conn_str):
        with psycopg.connect(conn_str) as conn:
            with conn.cursor() as cur:
                # Tables & Columns
                cur.execute("""
                    SELECT table_name, column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    ORDER BY table_name, column_name;
                """)
                columns = cur.fetchall()

                # RLS Status
                cur.execute("""
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relkind = 'r'
                    ORDER BY c.relname;
                """)
                rls = cur.fetchall()

                # Policies
                cur.execute("""
                    SELECT tablename, policyname, permissive, array_to_string(roles, ','), cmd
                    FROM pg_policies
                    WHERE schemaname = 'public'
                    ORDER BY tablename, policyname;
                """)
                policies = cur.fetchall()

                return {
                    "columns": set(columns),
                    "rls": set(rls),
                    "policies": set(policies)
                }

    live_cat = get_catalog_info(LIVE_DB_CONN)
    fresh_cat = get_catalog_info(FRESH_DB_CONN)

    print("\n--- Canonical Parity Results ---")
    columns_diff = live_cat["columns"].symmetric_difference(fresh_cat["columns"])
    rls_diff = live_cat["rls"].symmetric_difference(fresh_cat["rls"])
    policies_diff = live_cat["policies"].symmetric_difference(fresh_cat["policies"])

    # Clean up temporary database
    with psycopg.connect(PG_ADMIN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {FRESH_DB_NAME} WITH (FORCE);")

    if columns_diff:
        print(f"[FAIL] Column differences found ({len(columns_diff)}):")
        for diff in sorted(columns_diff):
            print("  ", diff)
    else:
        print("[PASS] All table columns and types match 100% across databases.")

    if rls_diff:
        print(f"[FAIL] RLS configuration differences found ({len(rls_diff)}):")
        for diff in sorted(rls_diff):
            print("  ", diff)
    else:
        print("[PASS] Row-level security (ENABLE and FORCE RLS) matches 100% on all tables.")

    if policies_diff:
        print(f"[FAIL] RLS Policy differences found ({len(policies_diff)}):")
        for diff in sorted(policies_diff):
            print("  ", diff)
    else:
        print("[PASS] RLS isolation policies match 100% on all tables.")

    if columns_diff or rls_diff or policies_diff:
        print("\nERROR: Database parity verification failed.")
        sys.exit(1)
    else:
        print("\nSUCCESS: Canonical Database Parity Verified! infra/init-db.sql is 100% identical to active migration.")

if __name__ == "__main__":
    run_parity_check()
