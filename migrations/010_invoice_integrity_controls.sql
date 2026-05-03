-- ══════════════════════════════════════════════════════════════
-- 010_invoice_integrity_controls.sql
-- ضوابط سلامة الفاتورة: لا حذف نهائي، إلغاء موثق فقط
-- ══════════════════════════════════════════════════════════════

-- حقول توثيق الإلغاء على الفاتورة (Immutable-friendly)
ALTER TABLE invoices ADD COLUMN cancel_reason TEXT;
ALTER TABLE invoices ADD COLUMN cancelled_at TEXT;
ALTER TABLE invoices ADD COLUMN cancelled_by INTEGER REFERENCES users(id);

-- فهارس لتسريع تقارير الرقابة
CREATE INDEX IF NOT EXISTS idx_invoices_status_business ON invoices(business_id, status);
CREATE INDEX IF NOT EXISTS idx_invoices_cancelled_at ON invoices(cancelled_at);
