"""
Applies Step 03 Omnichannel schema migration and RLS policies to live PostgreSQL database.
"""
import psycopg

PG_ADMIN_CONN = "postgresql://postgres:postgres_dev_password_change_in_prod@127.0.0.1:5432/sales_ai_db"

def apply_omnichannel_migration():
    print("Connecting to live PostgreSQL database to apply Step 03 migration...")
    conn = psycopg.connect(PG_ADMIN_CONN)
    with conn.cursor() as cur:
        # 1. Read and execute migration SQL
        with open("src/backend/migrations/002_omnichannel_schema.sql", "r", encoding="utf-8") as f:
            migration_sql = f.read()
        cur.execute(migration_sql)
        print("Schema tables created.")

        # 2. Configure RLS and Policies
        omnichannel_tables = [
            ("contacts", "tenant_isolation_contacts"),
            ("channel_identities", "tenant_isolation_channel_identities"),
            ("conversations", "tenant_isolation_conversations"),
            ("inbound_raw_events", "tenant_isolation_inbound_raw_events"),
            ("conversation_messages", "tenant_isolation_conversation_messages"),
            ("message_attachments", "tenant_isolation_message_attachments"),
            ("outbox_events", "tenant_isolation_outbox_events"),
        ]
        for tbl, pname in omnichannel_tables:
            cur.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
            cur.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;")
            cur.execute(f"DROP POLICY IF EXISTS {pname} ON {tbl};")
            cur.execute(f"""
                CREATE POLICY {pname} ON {tbl}
                AS PERMISSIVE
                FOR ALL
                TO PUBLIC
                USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''))
                WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), ''));
            """)

        # 3. Grant DML permissions to sales_app_user
        cur.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sales_app_user;")
        cur.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sales_app_user;")
        conn.commit()
    print("Step 03 Omnichannel schema and RLS successfully applied to live database!")
    conn.close()

if __name__ == "__main__":
    apply_omnichannel_migration()
