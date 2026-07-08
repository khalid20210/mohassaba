-- ══════════════════════════════════════════════════════════════
-- 024_approval_policies_contract.sql
-- عقد المرحلة 3: approval_policies
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS approval_policies (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id        INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    entity_type        TEXT NOT NULL,
    action_type        TEXT NOT NULL,
    requires_approval  INTEGER NOT NULL DEFAULT 0,
    conditions         TEXT,      -- JSON
    role_based_rules   TEXT,      -- JSON
    is_active          INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(business_id, entity_type, action_type)
);

CREATE INDEX IF NOT EXISTS idx_approval_policies_biz_entity_action
    ON approval_policies(business_id, entity_type, action_type);

CREATE INDEX IF NOT EXISTS idx_approval_policies_active
    ON approval_policies(business_id, is_active);

-- مزامنة بيانات مبدئية من operation_policies (إن وجدت)
INSERT INTO approval_policies (
    business_id, entity_type, action_type,
    requires_approval, conditions, role_based_rules, is_active
)
SELECT
    op.business_id,
    CASE
        WHEN instr(op.operation_key, '.') > 0 THEN substr(op.operation_key, 1, instr(op.operation_key, '.') - 1)
        ELSE op.operation_key
    END AS entity_type,
    CASE
        WHEN instr(op.operation_key, '.') > 0 THEN substr(op.operation_key, instr(op.operation_key, '.') + 1)
        ELSE 'default'
    END AS action_type,
    op.requires_approval,
    json_object('min_approvals', op.min_approvals),
    json_object('permission_key', op.permission_key, 'owner_only', op.owner_only),
    op.is_active
FROM operation_policies op
WHERE op.operation_key IS NOT NULL
ON CONFLICT(business_id, entity_type, action_type) DO NOTHING;
