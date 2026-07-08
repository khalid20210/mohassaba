-- ══════════════════════════════════════════════════════════════
-- 022_approval_requests_contract.sql
-- توحيد عقد approval_requests وفق الحقول المطلوبة
-- ══════════════════════════════════════════════════════════════

-- الحقول المطلوبة بالعقد الجديد:
-- id, action_type, entity_type, entity_id, requested_by,
-- status (pending/approved/rejected), approved_by, approved_at, payload

ALTER TABLE approval_requests ADD COLUMN action_type TEXT;
ALTER TABLE approval_requests ADD COLUMN approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE approval_requests ADD COLUMN approved_at TEXT;
ALTER TABLE approval_requests ADD COLUMN payload TEXT;

-- مزامنة أولية للبيانات من الحقول القديمة (إن وجدت)
UPDATE approval_requests
SET action_type = COALESCE(action_type, operation_key)
WHERE action_type IS NULL;

UPDATE approval_requests
SET payload = COALESCE(payload, payload_json)
WHERE payload IS NULL;

UPDATE approval_requests
SET approved_by = COALESCE(approved_by, resolved_by)
WHERE approved_by IS NULL;

UPDATE approval_requests
SET approved_at = COALESCE(approved_at, resolved_at)
WHERE approved_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_approval_requests_action_type
    ON approval_requests(business_id, action_type, status);

-- ملاحظة: تقييد status يُفرض من طبقة الخدمة/API حالياً لضمان
-- التوافق مع migration_runner (لا يدعم TRIGGER متعدد الجمل بصيغته الحالية).
