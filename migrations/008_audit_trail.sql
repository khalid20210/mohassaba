-- ══════════════════════════════════════════════════════════════
-- 008_audit_trail.sql — سجل العمليات الكامل (Audit Trail)
-- يُسجل كل حدث: دخول، بيع، تعديل، حذف مع المستخدم والتوقيت والـ IP
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS audit_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id  INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_name   TEXT    DEFAULT '',        -- اسم المستخدم وقت الحدث
    actor_role   TEXT    DEFAULT '',        -- دوره
    action       TEXT    NOT NULL,          -- login | logout | create | update | delete | pos_sale | ...
    entity_type  TEXT,                      -- invoice | product | contact | agent | user | ...
    entity_id    INTEGER,                   -- معرف السجل المتأثر
    old_value    TEXT,                      -- JSON قبل التغيير (للتعديل/الحذف)
    new_value    TEXT,                      -- JSON بعد التغيير
    ip_address   TEXT    DEFAULT '',
    user_agent   TEXT    DEFAULT '',
    created_at   TEXT    DEFAULT (datetime('now'))
);

-- فهارس للأداء (البحث متعدد الأبعاد)
CREATE INDEX IF NOT EXISTS idx_audit_business    ON audit_logs(business_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user        ON audit_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action      ON audit_logs(business_id, action);
CREATE INDEX IF NOT EXISTS idx_audit_entity      ON audit_logs(business_id, entity_type, entity_id);
