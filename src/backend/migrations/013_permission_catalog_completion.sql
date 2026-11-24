-- =============================================================================
-- 013: Permission catalog completion (inspection finding F-34)
-- =============================================================================
-- Every permission code required by an API route must exist in the catalog
-- (enforced by tests/security/test_permission_catalog_coverage.py).
INSERT INTO permissions (id, code, description, domain) VALUES
    ('perm_inventory_manage', 'inventory:manage', 'Manage warehouses, stock items and adjustments', 'INVENTORY'),
    ('perm_orders_manage', 'orders:manage', 'Create and manage sales orders, payment intents and refund requests', 'ORDERS'),
    ('perm_users_read', 'users:read', 'View tenant users', 'IAM'),
    ('perm_users_write', 'users:write', 'Create and update tenant users', 'IAM')
ON CONFLICT (code) DO NOTHING;
