-- ══════════════════════════════════════════════════════════════
-- 011_v2_engine.sql — محرك جنان بيز v2.0
-- سلة المهملات + نظام التنبيهات + سجل النسخ الاحتياطية
-- ══════════════════════════════════════════════════════════════

-- ─── سلة المهملات (Recycle Bin) ────────────────────────────────
-- كل حذف بواسطة مخوَّل يُسجَّل هنا بدل الحذف النهائي
CREATE TABLE IF NOT EXISTS recycle_bin (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id   INTEGER NOT NULL REFERENCES businesses(id),
    entity_type   TEXT    NOT NULL,          -- invoice | product | contact | journal_entry
    entity_id     INTEGER NOT NULL,
    entity_label  TEXT,                      -- وصف مختصر (رقم الفاتورة / اسم المنتج)
    entity_data   TEXT    NOT NULL,          -- JSON snapshot كامل قبل الحذف
    deleted_by    INTEGER REFERENCES users(id),
    deleted_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    delete_reason TEXT,
    restored_at   TEXT,
    restored_by   INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_recycle_business ON recycle_bin(business_id, deleted_at DESC);
CREATE INDEX IF NOT EXISTS idx_recycle_entity   ON recycle_bin(entity_type, entity_id);

-- ─── نظام التنبيهات والالتزامات (Reminders) ────────────────────
-- تنبيهات الأدمن: أقساط، تأمينات، إقرارات ضريبية، مخصص
CREATE TABLE IF NOT EXISTS reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    title           TEXT    NOT NULL,
    reminder_type   TEXT    NOT NULL DEFAULT 'custom',
    -- tax | insurance | installment | social_insurance | custom
    due_date        TEXT    NOT NULL,          -- YYYY-MM-DD
    amount          REAL,                      -- المبلغ المستحق (اختياري)
    notes           TEXT,
    is_recurring    INTEGER NOT NULL DEFAULT 0,
    recurrence_days INTEGER,                   -- التكرار كل كم يوم
    is_active       INTEGER NOT NULL DEFAULT 1,
    is_dismissed    INTEGER NOT NULL DEFAULT 0,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reminders_due      ON reminders(business_id, due_date, is_dismissed);
CREATE INDEX IF NOT EXISTS idx_reminders_type     ON reminders(business_id, reminder_type);

-- ─── سجل النسخ الاحتياطية (Backup Logs) ────────────────────────
CREATE TABLE IF NOT EXISTS backup_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    backup_type     TEXT    NOT NULL DEFAULT 'manual',  -- manual | scheduled
    format          TEXT    NOT NULL DEFAULT 'json',    -- json | csv
    file_size_kb    INTEGER,
    tables_included TEXT,                               -- JSON list
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ─── تحديث جدول المنتجات: متوسط التكلفة (إن لم يكن موجوداً) ──
-- avg_cost موجود في stock، لكن نضيفه للمنتج نفسه كقيمة مرجعية
-- لا نستخدم ALTER لتجنب الخطأ إذا كان العمود موجوداً
-- الـ supply/routes.py يحدّث stock.avg_cost عند كل شراء

-- ─── بيانات افتراضية: أنواع التنبيهات الشائعة للسعودية ─────────
-- (اختياري - يمكن إنشاؤها من الواجهة)
