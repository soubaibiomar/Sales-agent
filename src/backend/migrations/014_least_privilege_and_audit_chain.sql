-- =============================================================================
-- 014: Least-privilege application role and tamper-evident audit log
--      (inspection finding F-12)
-- =============================================================================
-- Before: sales_app_user had SELECT/INSERT/UPDATE/DELETE on all 84 tables. Because
-- foreign-key cascades bypass Row-Level Security, a single DELETE on `tenants`
-- (which has no RLS) erased every row of another tenant; audit rows could also be
-- rewritten or deleted.

BEGIN;

-- 1. Registry / catalog tables: the application never updates or deletes them.
--    Tenant provisioning (super_admin) still needs INSERT on tenants.
REVOKE UPDATE, DELETE ON tenants FROM sales_app_user;
REVOKE INSERT, UPDATE, DELETE ON roles, permissions, role_permissions FROM sales_app_user;

-- 2. Audit log: append-only for the application.
REVOKE UPDATE, DELETE ON audit_logs FROM sales_app_user;

-- 3. Per-tenant hash chain: each entry commits to the previous entry of the same tenant.
CREATE SEQUENCE IF NOT EXISTS audit_logs_chain_seq;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS chain_seq BIGINT;
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64);
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS entry_hash VARCHAR(64);
CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_chain ON audit_logs (tenant_id, chain_seq);

CREATE OR REPLACE FUNCTION audit_entry_digest(
    p_prev TEXT, p_id TEXT, p_tenant TEXT, p_actor TEXT, p_event TEXT, p_rtype TEXT,
    p_rid TEXT, p_action TEXT, p_payload TEXT, p_status TEXT, p_ts TIMESTAMPTZ
) RETURNS TEXT
LANGUAGE sql IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT encode(digest(
        coalesce(p_prev, '') || '|' || p_id || '|' || p_tenant || '|' || coalesce(p_actor, '') || '|' ||
        p_event || '|' || p_rtype || '|' || coalesce(p_rid, '') || '|' || p_action || '|' ||
        coalesce(p_payload, '') || '|' || p_status || '|' ||
        to_char(p_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
        'sha256'), 'hex');
$$;

CREATE OR REPLACE FUNCTION audit_logs_chain_before_insert() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    last_hash TEXT;
BEGIN
    -- Serialise appends per tenant so two concurrent inserts cannot fork the chain.
    PERFORM pg_advisory_xact_lock(hashtextextended('audit_chain:' || NEW.tenant_id, 0));
    SELECT a.entry_hash INTO last_hash
      FROM audit_logs a
     WHERE a.tenant_id = NEW.tenant_id AND a.entry_hash IS NOT NULL
     ORDER BY a.chain_seq DESC
     LIMIT 1;
    NEW.chain_seq := nextval('audit_logs_chain_seq');
    NEW.prev_hash := last_hash;
    NEW.entry_hash := audit_entry_digest(last_hash, NEW.id, NEW.tenant_id, NEW.actor_id, NEW.event_type,
        NEW.resource_type, NEW.resource_id, NEW.action, NEW.payload::text, NEW.status, NEW."timestamp");
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION audit_logs_block_mutation() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- Audit entries are never edited. Deletion is reserved to a superuser
    -- (e.g. court-ordered / DSAR tenant erasure, which cascades from tenants).
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'audit_logs is append-only (UPDATE rejected)';
    END IF;
    IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        RAISE EXCEPTION 'audit_logs is append-only (DELETE rejected for role %)', current_user;
    END IF;
    RETURN OLD;
END;
$$;

-- 4. Backfill the chain for existing rows (oldest first, per tenant).
DO $$
DECLARE
    t RECORD;
    r RECORD;
    h TEXT;
BEGIN
    FOR t IN SELECT DISTINCT tenant_id FROM audit_logs LOOP
        h := NULL;
        FOR r IN SELECT * FROM audit_logs WHERE tenant_id = t.tenant_id ORDER BY "timestamp", id LOOP
            UPDATE audit_logs
               SET chain_seq = nextval('audit_logs_chain_seq'),
                   prev_hash = h,
                   entry_hash = audit_entry_digest(h, r.id, r.tenant_id, r.actor_id, r.event_type, r.resource_type,
                                                   r.resource_id, r.action, r.payload::text, r.status, r."timestamp")
             WHERE id = r.id
         RETURNING entry_hash INTO h;
        END LOOP;
    END LOOP;
END;
$$;

DROP TRIGGER IF EXISTS trg_audit_logs_chain ON audit_logs;
CREATE TRIGGER trg_audit_logs_chain BEFORE INSERT ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_chain_before_insert();
DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs;
CREATE TRIGGER trg_audit_logs_immutable BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_block_mutation();

-- 5. Verification: recomputes the caller's own tenant chain (RLS context required).
CREATE OR REPLACE FUNCTION audit_verify_chain()
RETURNS TABLE (entries_checked BIGINT, is_intact BOOLEAN, first_broken_id VARCHAR)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_tenant TEXT := NULLIF(current_setting('app.current_tenant_id', true), '');
    r RECORD;
    h TEXT := NULL;
    n BIGINT := 0;
BEGIN
    IF v_tenant IS NULL THEN
        RAISE EXCEPTION 'audit_verify_chain requires a tenant context';
    END IF;
    FOR r IN SELECT * FROM audit_logs WHERE tenant_id = v_tenant ORDER BY chain_seq LOOP
        n := n + 1;
        IF r.prev_hash IS DISTINCT FROM h OR r.entry_hash IS DISTINCT FROM audit_entry_digest(
               h, r.id, r.tenant_id, r.actor_id, r.event_type, r.resource_type, r.resource_id,
               r.action, r.payload::text, r.status, r."timestamp") THEN
            RETURN QUERY SELECT n, false, r.id;
            RETURN;
        END IF;
        h := r.entry_hash;
    END LOOP;
    RETURN QUERY SELECT n, true, NULL::VARCHAR;
END;
$$;
REVOKE ALL ON FUNCTION audit_verify_chain() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION audit_verify_chain() TO sales_app_user;
GRANT USAGE ON SEQUENCE audit_logs_chain_seq TO sales_app_user;

COMMIT;
