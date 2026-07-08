-- ══════════════════════════════════════════════════════════════
-- 026_rbac_normalized.sql
-- RBAC normalized contract with backward-compatible sync
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS permissions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id       INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (role_id, permission_id)
);

CREATE INDEX IF NOT EXISTS idx_role_permissions_permission
    ON role_permissions(permission_id);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_roles_role
    ON user_roles(role_id);

INSERT OR IGNORE INTO permissions (name) VALUES
    ('all'),
    ('sales'),
    ('purchases'),
    ('warehouse'),
    ('contacts'),
    ('pos'),
    ('accounting'),
    ('reports'),
    ('analytics'),
    ('settings'),
    ('invoice_edit'),
    ('invoice_cancel'),
    ('invoice_delete'),
    ('invoice_reason_optional'),
    ('business_profile_edit'),
    ('business_profile_reason_optional'),
    ('inventory');

INSERT OR IGNORE INTO user_roles (user_id, role_id)
SELECT id, role_id
FROM users
WHERE role_id IS NOT NULL;

INSERT OR IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p
JOIN json_each(CASE
    WHEN r.permissions IS NULL OR TRIM(r.permissions) = '' THEN '{}'
    ELSE r.permissions
END) je
ON p.name = je.key
WHERE COALESCE(je.value, 0) IN (1, '1', 'true', 'TRUE');
