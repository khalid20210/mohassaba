-- migrations/013_zatca_settings_and_security.sql
-- جدول إعدادات ZATCA لكل منشأة + تحسينات أمنية

-- ─── جدول إعدادات ZATCA ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS business_zatca_settings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id      INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    phase            INTEGER NOT NULL DEFAULT 1,           -- 1 أو 2
    csid             TEXT    NOT NULL DEFAULT '',           -- Compliance Security ID
    api_secret       TEXT    NOT NULL DEFAULT '',           -- API Secret (مشفر)
    is_sandbox       INTEGER NOT NULL DEFAULT 1,           -- 1=sandbox, 0=production
    is_active        INTEGER NOT NULL DEFAULT 1,
    registered_at    TEXT,                                  -- تاريخ التسجيل في ZATCA
    expires_at       TEXT,                                  -- تاريخ انتهاء الشهادة
    last_success_at  TEXT,                                  -- آخر إرسال ناجح
    last_error       TEXT,                                  -- آخر رسالة خطأ
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_zatca_settings_biz
    ON business_zatca_settings(business_id);

-- ─── جدول سجلات ZATCA التفصيلية ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS zatca_submission_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    invoice_id      INTEGER REFERENCES invoices(id),
    invoice_number  TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending',    -- pending/success/failed/skipped
    http_code       INTEGER,
    zatca_response  TEXT,                                  -- JSON response
    attempt_number  INTEGER NOT NULL DEFAULT 1,
    submitted_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_zatca_logs_biz_status
    ON zatca_submission_logs(business_id, status);

-- ─── جدول النسخ الاحتياطية المجدولة ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scheduled_backups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id  INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    frequency    TEXT    NOT NULL DEFAULT 'daily',         -- daily/weekly/monthly
    last_run_at  TEXT,
    next_run_at  TEXT,
    is_encrypted INTEGER NOT NULL DEFAULT 0,
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_scheduled_backups_biz
    ON scheduled_backups(business_id);

-- ─── عمود cancel_reason في invoices (إن لم يكن موجوداً) ─────────────────────
-- ALTER TABLE invoices ADD COLUMN cancel_reason TEXT;       -- يُفعّل عند الحاجة
-- ALTER TABLE invoices ADD COLUMN cancelled_at  TEXT;
-- ALTER TABLE invoices ADD COLUMN cancelled_by  INTEGER;

-- ─── فهارس لتحسين أداء صفحة الفواتير ────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_invoices_biz_type_status
    ON invoices(business_id, invoice_type, status);

CREATE INDEX IF NOT EXISTS idx_invoices_biz_date
    ON invoices(business_id, invoice_date);

CREATE INDEX IF NOT EXISTS idx_invoices_biz_party
    ON invoices(business_id, party_name);

-- ─── فهارس لتحسين أداء صفحة الوصفات ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_recipes_biz_cat
    ON recipes(business_id, category);

CREATE INDEX IF NOT EXISTS idx_recipes_biz_active
    ON recipes(business_id, is_active);
