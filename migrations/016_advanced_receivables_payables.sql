-- ════════════════════════════════════════════════════════════════════════════
-- 016_advanced_receivables_payables.sql
-- نظام متقدم للذمم المدينة والدائنة مع التقادم والتحليلات
-- ════════════════════════════════════════════════════════════════════════════

-- ════════════════════════════════════════════════════════════════════════════
-- 1. جداول الذمم المتقدمة
-- ════════════════════════════════════════════════════════════════════════════

-- ── 1.1 أرصدة الذمم (Receivables/Payables Balances) ──────────────────────
CREATE TABLE IF NOT EXISTS receivables_payables_summary (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id             INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    contact_id              INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    summary_type            TEXT NOT NULL CHECK(summary_type IN ('receivable', 'payable')),
    -- الرصيد الحالي
    opening_balance         REAL DEFAULT 0,                 -- الرصيد الافتتاحي
    current_balance         REAL DEFAULT 0,                 -- الرصيد الحالي (ديناميكي)
    paid_amount             REAL DEFAULT 0,                 -- المبلغ المدفوع/المستلم
    -- الحسابات
    related_account_id      INTEGER REFERENCES accounts(id), -- حساب العميل/المورد
    -- الحالة
    is_overdue              INTEGER DEFAULT 0,              -- 1 = متأخر الدفع
    days_overdue            INTEGER DEFAULT 0,              -- عدد الأيام
    last_transaction_date   TEXT,                           -- آخر حركة
    last_payment_date       TEXT,                           -- آخر دفعة/استقبال
    -- التاريخ
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now')),
    UNIQUE(business_id, contact_id, summary_type)
);

CREATE INDEX IF NOT EXISTS idx_rps_business_type
    ON receivables_payables_summary(business_id, summary_type);
CREATE INDEX IF NOT EXISTS idx_rps_overdue
    ON receivables_payables_summary(business_id, is_overdue, days_overdue);
CREATE INDEX IF NOT EXISTS idx_rps_contact
    ON receivables_payables_summary(contact_id);

-- ── 1.2 حركات الذمم (Receivables/Payables Transactions) ────────────────────
CREATE TABLE IF NOT EXISTS receivables_payables_transactions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id             INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    contact_id              INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    transaction_type        TEXT NOT NULL CHECK(transaction_type IN ('invoice', 'payment', 'credit_memo', 'debit_memo', 'write_off')),
    summary_id              INTEGER REFERENCES receivables_payables_summary(id),
    -- معلومات الحركة
    reference_number        TEXT,                           -- رقم الفاتورة أو المدفوعة
    reference_id            INTEGER,                        -- معرف الفاتورة/الدفعة
    reference_type          TEXT,                           -- invoice, payment_receipt
    transaction_date        TEXT NOT NULL,                  -- تاريخ الحركة
    due_date                TEXT,                           -- تاريخ الاستحقاق
    amount                  REAL NOT NULL,                  -- المبلغ
    paid_amount             REAL DEFAULT 0,                 -- المبلغ المدفوع
    remaining_balance       REAL DEFAULT 0,                 -- الرصيد المتبقي
    -- التفاصيل
    description             TEXT,
    notes                   TEXT,
    -- الحالة
    status                  TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'partial', 'paid', 'written_off', 'cancelled')),
    -- تتبع الدفع
    posted_at               TEXT,
    posted_by               INTEGER REFERENCES users(id),
    -- التاريخ
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_rpt_business_contact
    ON receivables_payables_transactions(business_id, contact_id);
CREATE INDEX IF NOT EXISTS idx_rpt_status
    ON receivables_payables_transactions(status, due_date);
CREATE INDEX IF NOT EXISTS idx_rpt_reference
    ON receivables_payables_transactions(reference_type, reference_id);
CREATE INDEX IF NOT EXISTS idx_rpt_date
    ON receivables_payables_transactions(transaction_date);

-- ── 1.3 تفاصيل السدادات (Payment Allocations) ─────────────────────────────
CREATE TABLE IF NOT EXISTS payment_allocations (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id             INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    payment_id              INTEGER NOT NULL REFERENCES receivables_payables_transactions(id) ON DELETE CASCADE,
    transaction_id          INTEGER NOT NULL REFERENCES receivables_payables_transactions(id) ON DELETE CASCADE,
    -- المبلغ المخصص
    allocated_amount        REAL NOT NULL,                  -- المبلغ المتحسوب من الدفعة
    -- التاريخ
    created_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pa_payment ON payment_allocations(payment_id);
CREATE INDEX IF NOT EXISTS idx_pa_transaction ON payment_allocations(transaction_id);

-- ════════════════════════════════════════════════════════════════════════════
-- 2. تقارير التقادم (Aging Reports)
-- ════════════════════════════════════════════════════════════════════════════

-- ── 2.1 جدول مخزن مؤقتاً لتقارير التقادم (Aging Snapshot) ───────────────────
CREATE TABLE IF NOT EXISTS aging_snapshot (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id             INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    contact_id              INTEGER REFERENCES contacts(id),
    report_type             TEXT NOT NULL CHECK(report_type IN ('receivable', 'payable')),
    snapshot_date           TEXT NOT NULL,                  -- تاريخ التقرير
    -- التصنيفات العمرية
    current_0_to_30         REAL DEFAULT 0,                 -- 0-30 يوم
    overdue_31_to_60        REAL DEFAULT 0,                 -- 31-60 يوم
    overdue_61_to_90        REAL DEFAULT 0,                 -- 61-90 يوم
    overdue_over_90         REAL DEFAULT 0,                 -- فوق 90 يوم
    total_balance           REAL DEFAULT 0,
    -- الإحصائيات
    number_of_transactions  INTEGER DEFAULT 0,
    highest_overdue_days    INTEGER DEFAULT 0,
    -- التاريخ
    created_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_aging_business_date
    ON aging_snapshot(business_id, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_aging_contact
    ON aging_snapshot(contact_id);

-- ════════════════════════════════════════════════════════════════════════════
-- 3. إعدادات الذمم (Credit Policy Settings)
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS credit_policies (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id             INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    contact_id              INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    -- حدود الائتمان
    credit_limit            REAL DEFAULT 0,                 -- الحد الأقصى للرصيد
    credit_used             REAL DEFAULT 0,                 -- الرصيد المستخدم الحالي
    available_credit        REAL DEFAULT 0,                 -- الرصيد المتاح
    -- الشروط
    payment_terms_days      INTEGER DEFAULT 30,             -- شروط الدفع (بالأيام)
    discount_rate_early     REAL DEFAULT 0,                 -- نسبة الخصم للدفع المبكر
    discount_days           INTEGER DEFAULT 10,             -- أيام الخصم
    interest_rate_overdue   REAL DEFAULT 0,                 -- نسبة الفائدة على التأخر
    -- الحالة
    is_active               INTEGER DEFAULT 1,
    -- التاريخ
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now')),
    UNIQUE(business_id, contact_id)
);

CREATE INDEX IF NOT EXISTS idx_credit_policies_contact
    ON credit_policies(contact_id);

-- ════════════════════════════════════════════════════════════════════════════
-- 4. تحديثات الأداء (Performance Tracking)
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS receivables_performance_metrics (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id             INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    -- المقاييس
    dso                     REAL DEFAULT 0,                 -- Days Sales Outstanding
    dpo                     REAL DEFAULT 0,                 -- Days Payable Outstanding
    collection_rate         REAL DEFAULT 0,                 -- نسبة التحصيل %
    overdue_ratio           REAL DEFAULT 0,                 -- نسبة المتأخرات %
    bad_debt_percentage     REAL DEFAULT 0,                 -- نسبة الديون المعدومة %
    -- الإجماليات
    total_receivables       REAL DEFAULT 0,
    total_payables          REAL DEFAULT 0,
    total_overdue           REAL DEFAULT 0,
    total_bad_debts         REAL DEFAULT 0,
    -- التاريخ
    period_start            TEXT NOT NULL,                  -- بداية الفترة
    period_end              TEXT NOT NULL,                  -- نهاية الفترة
    snapshot_date           TEXT NOT NULL DEFAULT (datetime('now')),
    created_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_metrics_period
    ON receivables_performance_metrics(business_id, period_start, period_end);

-- ════════════════════════════════════════════════════════════════════════════
-- 5. إجراءات معالجة الديون المعدومة (Write-offs & Bad Debts)
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS bad_debt_write_offs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id             INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    transaction_id          INTEGER NOT NULL REFERENCES receivables_payables_transactions(id) ON DELETE CASCADE,
    write_off_date          TEXT NOT NULL,
    amount                  REAL NOT NULL,
    reason                  TEXT NOT NULL,                  -- insolvency, expired, fraud, etc.
    approved_by             INTEGER REFERENCES users(id),
    approval_date           TEXT,
    -- حساب المصروف
    expense_account_id      INTEGER REFERENCES accounts(id),
    journal_entry_id        INTEGER REFERENCES journal_entries(id),
    -- التاريخ
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_write_offs_business
    ON bad_debt_write_offs(business_id, write_off_date);

-- ════════════════════════════════════════════════════════════════════════════
-- 6. تنبيهات وإجراءات (Alerts & Actions)
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS receivables_alerts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id             INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    contact_id              INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    alert_type              TEXT NOT NULL CHECK(alert_type IN ('credit_limit_exceeded', 'payment_overdue', 'early_warning')),
    -- التفاصيل
    description             TEXT,
    transaction_id          INTEGER REFERENCES receivables_payables_transactions(id),
    -- الحالة
    status                  TEXT DEFAULT 'active' CHECK(status IN ('active', 'resolved', 'dismissed')),
    severity                TEXT DEFAULT 'warning' CHECK(severity IN ('info', 'warning', 'critical')),
    -- التاريخ
    triggered_at            TEXT DEFAULT (datetime('now')),
    resolved_at             TEXT,
    created_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_alerts_active
    ON receivables_alerts(business_id, status, alert_type);

-- ════════════════════════════════════════════════════════════════════════════
-- 7. تحديث جداول الاتصالات (Update Contacts Table)
-- ════════════════════════════════════════════════════════════════════════════

-- إضافة حقول ذكية للاتصالات (إذا لم تكن موجودة)
ALTER TABLE contacts ADD COLUMN credit_limit REAL DEFAULT 0;
ALTER TABLE contacts ADD COLUMN credit_used REAL DEFAULT 0;
ALTER TABLE contacts ADD COLUMN payment_terms_days INTEGER DEFAULT 30;
ALTER TABLE contacts ADD COLUMN last_transaction_date TEXT;
ALTER TABLE contacts ADD COLUMN total_receivable REAL DEFAULT 0;
ALTER TABLE contacts ADD COLUMN total_payable REAL DEFAULT 0;
ALTER TABLE contacts ADD COLUMN is_on_credit_hold INTEGER DEFAULT 0;
-- إضافة حقول ذكية للاتصالات (إذا لم تكن موجودة)
PRAGMA table_info(contacts);

-- محاولة إضافة الأعمدة بحذر
BEGIN;
ALTER TABLE contacts ADD COLUMN credit_limit REAL DEFAULT 0;
COMMIT;
BEGIN;
ALTER TABLE contacts ADD COLUMN credit_used REAL DEFAULT 0;
COMMIT;
BEGIN;
ALTER TABLE contacts ADD COLUMN payment_terms_days INTEGER DEFAULT 30;
COMMIT;
BEGIN;
ALTER TABLE contacts ADD COLUMN last_transaction_date TEXT;
COMMIT;
BEGIN;
ALTER TABLE contacts ADD COLUMN total_receivable REAL DEFAULT 0;
COMMIT;
BEGIN;
ALTER TABLE contacts ADD COLUMN total_payable REAL DEFAULT 0;
COMMIT;
BEGIN;
ALTER TABLE contacts ADD COLUMN is_on_credit_hold INTEGER DEFAULT 0;
COMMIT;

-- ════════════════════════════════════════════════════════════════════════════
-- تم! النظام جاهز الآن لإدارة الذمم المتقدمة
-- ════════════════════════════════════════════════════════════════════════════
