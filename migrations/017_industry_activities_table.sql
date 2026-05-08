-- Migration 017: جدول تعريفات الأنشطة الدائمة
-- يُخزّن الأنشطة الـ 196 في قاعدة البيانات بدلاً من الكود فقط
-- يعمل مرة واحدة فقط (idempotent)

CREATE TABLE IF NOT EXISTS industry_activities (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT UNIQUE NOT NULL,   -- مثل: retail_fnb_supermarket
    name_ar      TEXT NOT NULL,
    name_en      TEXT,
    category     TEXT,                  -- retail | wholesale | food | services ...
    sub_category TEXT,
    is_active    INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ia_code     ON industry_activities(code);
CREATE INDEX IF NOT EXISTS idx_ia_category ON industry_activities(category);
