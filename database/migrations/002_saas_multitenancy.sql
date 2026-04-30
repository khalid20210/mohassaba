-- ============================================================
-- Migration 002: هيكلة SaaS / Multi-Tenant
-- التاريخ: 2026-04-28
-- الوصف:
--   1. إضافة industry_type لجدول businesses (المستأجرين)
--   2. إنشاء VIEW tenants كواجهة موحدة للمنشآت
--   3. إضافة مستخدم مدير افتراضي
--   4. فهارس أداء إضافية للبيئة متعددة المستأجرين
-- ============================================================

-- ============================================================
-- 1. إضافة نوع النشاط (industry_type) لجدول المنشآت
--    القيم المدعومة:
--    retail        = تجزئة
--    restaurant    = مطاعم
--    construction  = مقاولات
--    medical       = طبي / صيدليات
--    education     = تعليم
--    wholesale     = جملة
--    services      = خدمات
--    other         = أخرى
-- ============================================================
ALTER TABLE businesses ADD COLUMN industry_type TEXT DEFAULT 'retail';

-- تحديث المنشأة الافتراضية
UPDATE businesses SET industry_type = 'retail' WHERE id = 1;

-- ============================================================
-- 2. إنشاء VIEW tenants
--    يوحّد مصطلح tenant_id مع business_id للاستخدام في ORM
-- ============================================================
CREATE VIEW IF NOT EXISTS tenants AS
SELECT
    id                  AS tenant_id,
    id                  AS business_id,
    name,
    name_en,
    tax_number,
    cr_number,
    industry_type,
    currency,
    country,
    fiscal_year_start,
    phone,
    email,
    address,
    is_active,
    created_at,
    updated_at
FROM businesses;

-- ============================================================
-- 3. مستخدم مدير افتراضي (كلمة السر يجب تغييرها)
-- ============================================================
INSERT OR IGNORE INTO users (id, business_id, role_id, username, full_name, password_hash, is_active)
VALUES (1, 1, 1, 'admin', 'مدير النظام', 'CHANGE_ME_BEFORE_PRODUCTION', 1);

-- ============================================================
-- 4. إضافة أنواع النشاط كإعداد قابل للاستخدام من الواجهة
-- ============================================================
INSERT OR IGNORE INTO settings (business_id, key, value) VALUES
(1, 'industry_types', 'retail,restaurant,construction,medical,education,wholesale,services,other'),
(1, 'tenant_version', '2'),
(1, 'multitenancy_enabled', '1');

-- ============================================================
-- 5. فهارس أداء إضافية (Multi-Tenant)
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_accounts_business       ON accounts(business_id);
CREATE INDEX IF NOT EXISTS idx_journal_biz_date        ON journal_entries(business_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_invoices_biz_date       ON invoices(business_id, invoice_date);
CREATE INDEX IF NOT EXISTS idx_invoices_biz_status     ON invoices(business_id, status);
CREATE INDEX IF NOT EXISTS idx_users_business          ON users(business_id);
CREATE INDEX IF NOT EXISTS idx_contacts_biz_type       ON contacts(business_id, contact_type);
CREATE INDEX IF NOT EXISTS idx_stock_mvmt_biz_date     ON stock_movements(business_id, created_at);
CREATE INDEX IF NOT EXISTS idx_warehouses_business     ON warehouses(business_id);
CREATE INDEX IF NOT EXISTS idx_categories_business     ON product_categories(business_id);
