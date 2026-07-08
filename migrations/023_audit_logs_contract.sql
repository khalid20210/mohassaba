-- ══════════════════════════════════════════════════════════════
-- 023_audit_logs_contract.sql
-- توحيد عقد audit_logs وفق متطلبات الحوكمة (المرحلة 2)
-- ══════════════════════════════════════════════════════════════

-- Contract المطلوب:
-- id, user_id, action_type, entity_type, entity_id,
-- before_data(JSON), after_data(JSON), status(success/failed), created_at, ip_address

ALTER TABLE audit_logs ADD COLUMN action_type TEXT;
ALTER TABLE audit_logs ADD COLUMN before_data TEXT;
ALTER TABLE audit_logs ADD COLUMN after_data TEXT;
ALTER TABLE audit_logs ADD COLUMN status TEXT;

-- مزامنة البيانات القديمة مع العقد الجديد
UPDATE audit_logs
SET action_type = COALESCE(action_type, action)
WHERE action_type IS NULL;

UPDATE audit_logs
SET before_data = COALESCE(before_data, old_value)
WHERE before_data IS NULL;

UPDATE audit_logs
SET after_data = COALESCE(after_data, new_value)
WHERE after_data IS NULL;

UPDATE audit_logs
SET status = COALESCE(NULLIF(status, ''), 'success')
WHERE status IS NULL OR status = '';

CREATE INDEX IF NOT EXISTS idx_audit_action_type
    ON audit_logs(business_id, action_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_status
    ON audit_logs(business_id, status, created_at DESC);
