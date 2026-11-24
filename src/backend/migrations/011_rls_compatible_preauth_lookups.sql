-- =============================================================================
-- 011: RLS-compatible pre-authentication lookups (inspection finding F-09)
-- =============================================================================
-- Under FORCE ROW LEVEL SECURITY the least-privileged application role
-- (sales_app_user) cannot read `users` before a tenant is known, so login could
-- only work when the API connected as a superuser (which bypasses RLS).
-- This function exposes the minimum needed for login: the tenant ids of ACTIVE
-- users with a given email. It returns no password hashes, MFA secrets or PII.
-- It is SECURITY DEFINER (runs as the table owner) with a pinned search_path.

CREATE OR REPLACE FUNCTION auth_resolve_login_tenants(p_email TEXT, p_tenant_id TEXT DEFAULT NULL)
RETURNS TABLE (tenant_id VARCHAR)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT u.tenant_id
    FROM users u
    JOIN tenants t ON t.id = u.tenant_id
    WHERE lower(u.email) = lower(p_email)
      AND u.is_active = true
      AND t.is_active = true
      AND (p_tenant_id IS NULL OR u.tenant_id = p_tenant_id)
    LIMIT 2;
$$;

REVOKE ALL ON FUNCTION auth_resolve_login_tenants(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_resolve_login_tenants(TEXT, TEXT) TO sales_app_user;
